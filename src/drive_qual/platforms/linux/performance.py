from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drive_qual.core.dut_selection import dut_names_from_equipment
from drive_qual.core.io_utils import mk_dir
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.storage_paths import artifact_dir, localize_windows_path
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice
from drive_qual.platforms.performance_common import resolve_or_bind_dut_device, resolve_report_dut_name

LINUX_DISKS_BENCHMARK_TIMEOUT: float | None = None
LINUX_DISKS_TOOL_NAME = "Disks (native)"
LINUX_DISKS_ARTIFACT_CATEGORY = "Disks"


@dataclass(frozen=True)
class LinuxPerformanceDeps:
    software_entries_for_current_host: Callable[[dict[str, Any]], list[dict[str, Any]]]
    run_manual_performance_flow: Callable[[Path, dict[str, Any], dict[str, Any]], None]
    resolve_report_dut_name: Callable[[Path], str]
    resolve_or_bind_dut_device: Callable[[Path, str, str, tuple[str, ...]], ApricornDevice]
    resolve_report_dut_key: Callable[[dict[str, Any], str], str | None]
    to_float: Callable[[str | None], float | None]


def _linux_disks_artifact_paths(part_number: str, dut_name: str) -> tuple[Path, Path]:
    output_dir = localize_windows_path(Path(artifact_dir(part_number, "Linux", LINUX_DISKS_ARTIFACT_CATEGORY)))
    mk_dir(output_dir)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return (
        output_dir / f"{dut_name}_{timestamp}.json",
        output_dir / f"{dut_name}_{timestamp}.csv",
    )


def _write_linux_disks_csv(csv_path: Path, metrics: dict[str, str]) -> None:
    rows = [
        ("Minimum Read Rate", metrics.get("minimum_read_rate")),
        ("Average Read Rate", metrics.get("average_read_rate")),
        ("Maximum Read Rate", metrics.get("maximum_read_rate")),
        ("Minimum Write Rate", metrics.get("minimum_write_rate")),
        ("Average Write Rate", metrics.get("average_write_rate")),
        ("Maximum Write Rate", metrics.get("maximum_write_rate")),
        ("Average Access Time", metrics.get("average_access_time")),
        ("Last Benchmark", metrics.get("last_benchmark")),
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Metric", "Value"])
        writer.writerows(rows)


def _linux_disks_wrapper_script_path() -> Path:
    return Path(__file__).resolve().parents[4] / "tools" / "linux" / "disks-benchmark-like.py"


def _format_rate_mb_s(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f} MB/s"
    return None


def _summary_rate_bound_mb_s(summary: dict[str, Any], summary_key: str, bound: str) -> str | None:
    stats = summary.get(summary_key)
    if not isinstance(stats, dict):
        return None
    value = stats.get(bound)
    if not isinstance(value, (int, float)):
        return None
    return f"{float(value) * 1.048576:.2f} MB/s"


def _linux_disks_metrics_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    metrics: dict[str, str] = {}

    gui_average = payload.get("gui_average")
    if isinstance(gui_average, dict):
        read_rate = _format_rate_mb_s(gui_average.get("read_MB_s"))
        write_rate = _format_rate_mb_s(gui_average.get("write_MB_s"))
        access_ms = gui_average.get("access_msec")
        if read_rate is not None:
            metrics["average_read_rate"] = read_rate
        if write_rate is not None:
            metrics["average_write_rate"] = write_rate
        if isinstance(access_ms, (int, float)):
            metrics["average_access_time"] = f"{float(access_ms):.2f} ms"

    summary = payload.get("summary")
    if isinstance(summary, dict):
        for summary_key, metric_min, metric_max in (
            ("read_mib_per_sec", "minimum_read_rate", "maximum_read_rate"),
            ("write_mib_per_sec", "minimum_write_rate", "maximum_write_rate"),
        ):
            min_value = _summary_rate_bound_mb_s(summary, summary_key, "min")
            max_value = _summary_rate_bound_mb_s(summary, summary_key, "max")
            if min_value is not None:
                metrics[metric_min] = min_value
            if max_value is not None:
                metrics[metric_max] = max_value

    timestamp_usec = payload.get("timestamp_usec")
    if isinstance(timestamp_usec, (int, float, str)):
        metrics["last_benchmark"] = str(timestamp_usec)

    return metrics


def _run_benchmark_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=LINUX_DISKS_BENCHMARK_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Linux benchmark wrapper timed out.") from exc


def _benchmark_detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip()


def _is_blocked_sudo(detail: str) -> bool:
    detail_cf = detail.casefold()
    return "a password is required" in detail_cf or "no tty present" in detail_cf or "terminal is required" in detail_cf


def _authenticate_sudo() -> None:
    try:
        result = subprocess.run(
            ["sudo", "-v"],
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out waiting for sudo authentication.") from exc

    if result.returncode != 0:
        raise RuntimeError("Linux benchmark wrapper requires sudo authentication.")


def _lsblk_device_tree(disk_path: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["lsblk", "-J", "-o", "PATH", disk_path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    devices = payload.get("blockdevices", [])
    if not isinstance(devices, list) or not devices:
        return None
    root = devices[0]
    if not isinstance(root, dict):
        return None
    return root


def _append_lsblk_paths_depth_first(entry: dict[str, Any], paths: list[str]) -> None:
    children = entry.get("children", [])
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _append_lsblk_paths_depth_first(child, paths)

    path = entry.get("path")
    if isinstance(path, str) and path:
        paths.append(path)


def _linux_unmount_candidates(disk_path: str) -> list[str]:
    tree = _lsblk_device_tree(disk_path)
    if tree is None:
        return [disk_path]

    collected: list[str] = []
    _append_lsblk_paths_depth_first(tree, collected)

    deduped: list[str] = []
    seen: set[str] = set()
    for path in collected:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)

    if disk_path not in seen:
        deduped.append(disk_path)
    return deduped


def _with_optional_sudo(command: list[str], *, use_sudo: bool) -> list[str]:
    if use_sudo:
        return ["sudo", "-n", *command]
    return command


def _prepare_linux_device_for_raw_benchmark(disk_path: str, *, use_sudo: bool) -> None:
    for block_path in _linux_unmount_candidates(disk_path):
        result = subprocess.run(
            _with_optional_sudo(["udisksctl", "unmount", "-b", block_path], use_sudo=use_sudo),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                _with_optional_sudo(["umount", block_path], use_sudo=use_sudo),
                check=False,
                capture_output=True,
                text=True,
            )


def _prepare_linux_disks_command(base_command: list[str], disk_path: str) -> list[str]:
    requires_sudo = _effective_uid() != 0
    if requires_sudo:
        _authenticate_sudo()

    _prepare_linux_device_for_raw_benchmark(disk_path, use_sudo=requires_sudo)
    return _with_optional_sudo(base_command, use_sudo=requires_sudo)


def _effective_uid() -> int:
    getter = getattr(os, "geteuid", None)
    if callable(getter):
        return int(getter())
    return 0


def _run_linux_disks_benchmark(dut: ApricornDevice, part_number: str) -> tuple[dict[str, str], Path, Path]:
    disk_path = (dut.blockDevice or "").strip()
    if not disk_path:
        raise RuntimeError("Could not determine the Linux block device for the connected Apricorn device.")

    json_path, csv_path = _linux_disks_artifact_paths(part_number, (dut.iProduct or "unknown_device").strip())
    wrapper_path = _linux_disks_wrapper_script_path()
    if not wrapper_path.exists():
        raise RuntimeError(f"Linux benchmark wrapper script not found: {wrapper_path}")

    base_command = [
        sys.executable,
        str(wrapper_path),
        "--device",
        disk_path,
        "--json-out",
        str(json_path),
        "--allow-buffered",
    ]

    command = _prepare_linux_disks_command(base_command, disk_path)
    print(f"Running Linux Disks benchmark on {disk_path}. This can take several minutes...")

    result = _run_benchmark_command(command)
    detail = _benchmark_detail(result)

    if result.returncode != 0:
        if _is_blocked_sudo(detail):
            raise RuntimeError(
                "Linux benchmark wrapper could not run with sudo. "
                "Authenticate with sudo and rerun the performance step."
            )
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Linux benchmark wrapper failed{suffix}")

    payload_text = json_path.read_text(encoding="utf-8") if json_path.exists() else result.stdout
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Linux benchmark wrapper returned invalid JSON output.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Linux benchmark wrapper returned an invalid payload.")

    metrics = _linux_disks_metrics_from_payload(payload)
    if "average_read_rate" not in metrics or "average_write_rate" not in metrics:
        raise RuntimeError("Linux benchmark wrapper output is missing average read/write rates.")

    _write_linux_disks_csv(csv_path, metrics)
    return metrics, json_path, csv_path


def run_linux_performance_flow(
    part_number: str,
    report_path: Path,
    data: dict[str, Any],
    equipment: dict[str, Any],
    *,
    deps: LinuxPerformanceDeps,
) -> None:
    software_entries = deps.software_entries_for_current_host(equipment)
    if not any(entry.get("name") == LINUX_DISKS_TOOL_NAME for entry in software_entries):
        deps.run_manual_performance_flow(report_path, data, equipment)
        return

    performance = data.setdefault("performance", {})
    if not isinstance(performance, dict):
        raise ValueError("Missing or invalid 'performance' section in report.")

    dut_name = deps.resolve_report_dut_name(report_path)
    dut_info = deps.resolve_or_bind_dut_device(
        report_path,
        dut_name,
        "Connect the Apricorn device to continue...",
        ("blockDevice",),
    )
    report_dut_key = deps.resolve_report_dut_key(performance, dut_name)
    if report_dut_key is None:
        raise RuntimeError(f"Could not map performance results for DUT {dut_name!r}.")

    metrics, json_path, csv_path = _run_linux_disks_benchmark(dut_info, part_number)
    os_perf = performance.setdefault(report_dut_key, {"Windows": {}, "Linux": {}, "macOS": {}}).setdefault("Linux", {})
    entry = os_perf.setdefault(LINUX_DISKS_TOOL_NAME, {"read": None, "write": None})
    if not isinstance(entry, dict):
        entry = {"read": None, "write": None}
        os_perf[LINUX_DISKS_TOOL_NAME] = entry
    entry["read"] = deps.to_float(metrics.get("average_read_rate"))
    entry["write"] = deps.to_float(metrics.get("average_write_rate"))

    save_report(report_path, data)
    print(f"Saved Linux benchmark JSON to: {json_path}")
    print(f"Saved Linux benchmark CSV to: {csv_path}")
    chart_path = json_path.with_name(f"{json_path.stem}_gnome_disks_like.png")
    if chart_path.exists():
        print(f"Saved Linux benchmark chart to: {chart_path}")
    print(f"Updated Linux performance in {report_path}")


def _software_entries_for_current_host(equipment: dict[str, Any]) -> list[dict[str, Any]]:
    host_data = equipment.get("linux_host", {})
    if not isinstance(host_data, dict):
        return []
    software = host_data.get("software", [])
    if not isinstance(software, list):
        return []
    return [entry for entry in software if isinstance(entry, dict)]


def _resolve_report_dut_key(performance: dict[str, Any], dut_name: str) -> str | None:
    for key in performance:
        key_cf = key.casefold()
        dut_cf = dut_name.casefold()
        if key_cf in dut_cf or dut_cf in key_cf:
            return key
    if len(performance) == 1:
        return next(iter(performance))
    return None


def _to_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        clean_val = "".join(c for k, c in enumerate(val) if c.isdigit() or c == "." or (c == "-" and k == 0))
        return float(clean_val)
    except (ValueError, TypeError):
        return None


def _prompt_manual_float(label: str, current: float | None) -> float | None:
    current_text = "" if current is None else str(current)
    prompt = f"{label} [{current_text}]: " if current_text else f"{label}: "
    while True:
        response = input(prompt).strip()
        if not response:
            return current
        value = _to_float(response)
        if value is not None:
            return value
        print("Enter a numeric value in MB/s or leave the field blank to keep the current value.")


def _run_manual_performance_flow(report_path: Path, data: dict[str, Any], equipment: dict[str, Any]) -> None:
    software_entries = _software_entries_for_current_host(equipment)
    if not software_entries:
        print("No performance software configured for Linux.")
        return

    performance = data.setdefault("performance", {})
    if not isinstance(performance, dict):
        raise ValueError("Missing or invalid 'performance' section in report.")

    dut_name = resolve_report_dut_name(report_path)
    resolve_or_bind_dut_device(
        report_path,
        dut_name,
        prompt="Connect the Apricorn device to continue...",
        required_fields=("blockDevice",),
    )
    report_dut_key = _resolve_report_dut_key(performance, dut_name)
    if report_dut_key is None:
        raise RuntimeError(f"Could not map performance results for DUT {dut_name!r}.")

    os_perf = performance.setdefault(report_dut_key, {"Windows": {}, "Linux": {}, "macOS": {}}).setdefault("Linux", {})
    for software in software_entries:
        name = software.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        entry = os_perf.setdefault(name, {"read": None, "write": None})
        if not isinstance(entry, dict):
            entry = {"read": None, "write": None}
            os_perf[name] = entry
        current_read = entry.get("read") if isinstance(entry.get("read"), (int, float)) else None
        current_write = entry.get("write") if isinstance(entry.get("write"), (int, float)) else None
        entry["read"] = _prompt_manual_float(f"Linux {name} read MB/s for {dut_name}", current_read)
        entry["write"] = _prompt_manual_float(f"Linux {name} write MB/s for {dut_name}", current_write)

    save_report(report_path, data)
    print(f"Updated Linux performance in {report_path}")


def _sync_performance_section(data: dict[str, Any], equipment: dict[str, Any]) -> None:
    performance = data.setdefault("performance", {})
    host_map = {"windows_host": "Windows", "linux_host": "Linux", "macos_host": "macOS"}
    for dut in dut_names_from_equipment(equipment):
        perf_dut = performance.setdefault(dut, {"Windows": {}, "Linux": {}, "macOS": {}})
        for host_key, os_key in host_map.items():
            host_data = equipment.get(host_key, {})
            sw_list = host_data.get("software", [])
            if isinstance(sw_list, list):
                os_perf = perf_dut.setdefault(os_key, {})
                for sw in sw_list:
                    if isinstance(sw, dict) and sw.get("name"):
                        name = sw.get("name")
                        if name == "CrystalDiskInfo":
                            cdi_dict = os_perf.setdefault(name, {"screenshot": None})
                            cdi_dict.pop("read", None)
                            cdi_dict.pop("write", None)
                        else:
                            os_perf.setdefault(name, {"read": None, "write": None})


def _load_part_number_and_report(folder_name: str) -> tuple[str, Path]:
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    drive_info = data.get("drive_info")
    part_number = folder_name
    if isinstance(drive_info, dict):
        raw = drive_info.get("apricorn_part_number")
        if isinstance(raw, str) and raw.strip():
            part_number = raw.strip()
    return part_number, report_path


def _resolve_or_bind_dut_device_for_deps(
    report_path: Path, dut_name: str, prompt: str, required_fields: tuple[str, ...]
) -> ApricornDevice:
    return resolve_or_bind_dut_device(
        report_path,
        dut_name,
        prompt=prompt,
        required_fields=required_fields,
    )


def run_software_step(part_number: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    actual_pn, report_path = _load_part_number_and_report(folder_name)
    data = load_report(report_path)
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section.")

    _sync_performance_section(data, equipment)
    save_report(report_path, data)
    print(f"\nSync complete. Updated report at {report_path}")

    run_linux_performance_flow(
        actual_pn,
        report_path,
        data,
        equipment,
        deps=LinuxPerformanceDeps(
            software_entries_for_current_host=_software_entries_for_current_host,
            run_manual_performance_flow=_run_manual_performance_flow,
            resolve_report_dut_name=resolve_report_dut_name,
            resolve_or_bind_dut_device=_resolve_or_bind_dut_device_for_deps,
            resolve_report_dut_key=_resolve_report_dut_key,
            to_float=_to_float,
        ),
    )
