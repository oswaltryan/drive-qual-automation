from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, TextIO

from drive_qual.core import temperature as temperature_plotter
from drive_qual.core.dut_selection import select_report_dut_name
from drive_qual.core.io_utils import mk_dir
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, localize_windows_path
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice, device_identity
from drive_qual.integrations.instruments.watlow import DEFAULT_F4T_IP, F4TController
from drive_qual.platforms.performance_common import (
    refresh_dut_device,
    resolve_or_bind_dut_device,
    resolve_report_dut_name,
)

LOW_TEMPERATURE_C = 20.000
HIGH_TEMPERATURE_C = 30.000
AMBIENT_TEMPERATURE_C = 25.000
TEMPERATURE_SETPOINTS_C: tuple[float, ...] = (LOW_TEMPERATURE_C, HIGH_TEMPERATURE_C)
SETPOINT_TOLERANCE_C = 0.4
SETPOINT_SOAK_SECONDS = 60.0
SNAPSHOT_INTERVAL_SECONDS = 2.0
DISK_TESTER_STOP_TIMEOUT_SECONDS = 15.0
TEMPERATURE_ARTIFACT_CATEGORY = "Temperature"
TEMPERATURE_CHART_SUFFIX = "Temperature Data.png"
TEMPERATURE_PROFILE_CSV_FIELDS: tuple[str, ...] = ("TempRounded", "Operation", "SpeedMiB", "Mode")
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_. -]+")

SNAPSHOT_CSV_FIELDS: tuple[str, ...] = (
    "timestamp",
    "temperature_c",
    "temperature_f",
)


@dataclass(frozen=True)
class TemperatureRunArtifacts:
    snapshot_csv: Path
    performance_csv: Path
    disk_tester_log: Path
    disk_tester_stdout: Path
    disk_tester_stderr: Path


@dataclass(frozen=True)
class TemperatureTarget:
    drive_target: str
    dut_name: str


def _part_number_from_report(data: dict[str, Any], fallback: str) -> str:
    drive_info = data.get("drive_info")
    if isinstance(drive_info, dict):
        value = drive_info.get("apricorn_part_number")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _timestamp_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _phase_name(setpoint_c: float) -> str:
    return f"{setpoint_c:g}c"


def _safe_filename_component(value: str) -> str:
    return SAFE_FILENAME_RE.sub("_", value).strip(" ._")


def _temperature_artifact_dir(part_number: str) -> Path:
    path = PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, TEMPERATURE_ARTIFACT_CATEGORY)
    local_path = localize_windows_path(Path(str(path)))
    mk_dir(local_path)
    return local_path


def _temperature_chart_path(part_number: str, dut_name: str) -> Path:
    safe_dut = _safe_filename_component(dut_name) or "DUT"
    return _temperature_artifact_dir(part_number) / f"{safe_dut} {TEMPERATURE_CHART_SUFFIX}"


def _temperature_artifacts(part_number: str) -> TemperatureRunArtifacts:
    artifact_dir = _temperature_artifact_dir(part_number)
    timestamp = _timestamp_for_filename()
    return TemperatureRunArtifacts(
        snapshot_csv=artifact_dir / f"temperature_snapshots_{timestamp}.csv",
        performance_csv=artifact_dir / f"temperature_performance_{timestamp}.csv",
        disk_tester_log=artifact_dir / f"disk_tester_temperature_{timestamp}.log",
        disk_tester_stdout=artifact_dir / f"disk_tester_temperature_{timestamp}.stdout.log",
        disk_tester_stderr=artifact_dir / f"disk_tester_temperature_{timestamp}.stderr.log",
    )


def _disk_tester_command(target_path: str, log_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "drive_qual.benchmarks.disk_tester",
        "temp",
        "--path",
        target_path,
        "--log",
        str(log_path),
    ]


def _normalize_drive_letter(raw: str) -> str:
    token = raw.strip().replace("\\", "").replace("/", "")
    if token.endswith(":"):
        token = token[:-1]
    if len(token) != 1 or not token.isalpha():
        raise RuntimeError(f"Invalid drive letter for temperature testing: {raw!r}")
    return f"{token.upper()}:"


def _drive_letter_or_none(dut: ApricornDevice) -> str | None:
    if dut.driveLetter is None:
        return None
    try:
        return _normalize_drive_letter(dut.driveLetter)
    except RuntimeError:
        return None


def _format_temperature_target(dut: ApricornDevice) -> None:
    if sys.platform != "win32":
        raise RuntimeError(f"usb --json did not include a usable driveLetter for {device_identity(dut)}.")

    from drive_qual.platforms.windows.power_measurements import partition_and_format_drive

    print(f"No usable drive letter found for {device_identity(dut)}; partitioning and formatting DUT.")
    if not partition_and_format_drive(dut):
        raise RuntimeError(f"Partition/format failed for {device_identity(dut)}.")


def _resolve_temperature_target(report_path: Path) -> TemperatureTarget:
    dut_name = resolve_report_dut_name(report_path)
    dut_info = resolve_or_bind_dut_device(
        report_path,
        dut_name,
        prompt="Connect the Apricorn device to continue temperature testing...",
        required_fields=("physicalDriveNum",) if sys.platform == "win32" else (),
    )

    drive_letter = _drive_letter_or_none(dut_info)
    if drive_letter is None:
        _format_temperature_target(dut_info)
        dut_info = refresh_dut_device(
            report_path,
            dut_name,
            prompt="Waiting for DUT to re-enumerate after format...",
            required_fields=("physicalDriveNum", "driveLetter") if sys.platform == "win32" else ("driveLetter",),
        )
        drive_letter = _drive_letter_or_none(dut_info)

    if drive_letter is None:
        raise RuntimeError(f"usb --json did not include a usable driveLetter for {device_identity(dut_info)}.")
    return TemperatureTarget(drive_target=drive_letter, dut_name=dut_name)


def _resolve_drive_target(report_path: Path) -> str:
    return _resolve_temperature_target(report_path).drive_target


def _start_disk_tester(
    *,
    target_path: str,
    artifacts: TemperatureRunArtifacts,
    stdout: TextIO,
    stderr: TextIO,
) -> subprocess.Popen[str]:
    command = _disk_tester_command(target_path, artifacts.disk_tester_log)
    print(f"Starting disk tester: {' '.join(command)}")
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)


def _setpoint_reached(*, measured_c: float, setpoint_c: float) -> bool:
    return abs(measured_c - setpoint_c) <= SETPOINT_TOLERANCE_C


def _write_snapshot_and_check_setpoint(
    writer: csv.DictWriter[str],
    *,
    controller: F4TController,
    setpoint_target_c: float,
) -> bool:
    try:
        snapshot = controller.read_snapshot()
    except Exception as exc:
        print(f"Warning: could not read Watlow temperature snapshot: {exc}")
        writer.writerow(
            {
                "timestamp": _timestamp(),
                "temperature_c": "",
                "temperature_f": "",
            }
        )
        return False

    writer.writerow(
        {
            "timestamp": snapshot.timestamp,
            "temperature_c": f"{snapshot.temperature_c:.3f}",
            "temperature_f": f"{snapshot.temperature_f:.3f}",
        }
    )
    print(f"Temperature snapshot: {snapshot.timestamp}, {snapshot.temperature_c:.3f} C, {snapshot.temperature_f:.3f} F")
    return _setpoint_reached(measured_c=snapshot.temperature_c, setpoint_c=setpoint_target_c)


def _update_temperature_report_from_profile(data: dict[str, Any], dut_name: str, profile_csv: Path) -> None:
    temperature = data.get("temperature")
    if not isinstance(temperature, dict):
        raise ValueError("Invalid 'temperature' section; expected object.")

    dut_temperature = temperature.get(dut_name)
    if not isinstance(dut_temperature, dict):
        raise ValueError(f"Invalid temperature contract for DUT {dut_name!r}; expected object.")

    performance = dut_temperature.get("performance")
    if not isinstance(performance, dict):
        raise ValueError(f"Invalid temperature performance contract for DUT {dut_name!r}; expected object.")

    with profile_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            mode = (row.get("Mode") or "").strip().casefold()
            if mode and mode != "sequential":
                continue
            operation = (row.get("Operation") or "").strip().casefold()
            if operation not in {"read", "write"}:
                continue
            try:
                temp_c = int(round(float(row.get("TempRounded") or "")))
                speed_mib = float(row.get("SpeedMiB") or "")
            except ValueError:
                continue

            entry = performance.get(f"{temp_c}c")
            if not isinstance(entry, dict):
                continue
            entry[f"{operation}_mb_s"] = speed_mib


def _finalize_temperature_results(
    *,
    folder_name: str,
    dut_name: str,
    artifacts: TemperatureRunArtifacts,
) -> None:
    data = load_report(report_path_for(folder_name))
    actual_part_number = _part_number_from_report(data, folder_name)
    chart_path = _temperature_chart_path(actual_part_number, dut_name)
    profile_df = temperature_plotter.write_snapshot_log_chart_outputs(
        snapshot_csv=artifacts.snapshot_csv,
        log_path=artifacts.disk_tester_log,
        profile_csv=artifacts.performance_csv,
        chart_png=chart_path,
    )
    if profile_df.empty:
        raise RuntimeError(f"No temperature/performance rows could be derived from {artifacts.disk_tester_log}.")
    _update_temperature_report_from_profile(data, dut_name, artifacts.performance_csv)
    save_report(report_path_for(folder_name), data)
    print(f"Saved temperature chart to: {chart_path}")


def _run_snapshot_phase(
    *,
    controller: F4TController,
    writer: csv.DictWriter[str],
    csv_handle: TextIO,
    disk_tester: subprocess.Popen[str],
    setpoint_c: float,
) -> None:
    phase = _phase_name(setpoint_c)
    soak_started_at: float | None = None
    print(f"Setting chamber setpoint to {setpoint_c:g} C.")
    controller.write_setpoint_c(setpoint_c)

    while True:
        if disk_tester.poll() is not None:
            raise RuntimeError(f"disk_tester.py exited early with code {disk_tester.returncode}.")
        reached = _write_snapshot_and_check_setpoint(
            writer,
            controller=controller,
            setpoint_target_c=setpoint_c,
        )
        csv_handle.flush()
        now = time.monotonic()
        if reached:
            if soak_started_at is None:
                soak_started_at = now
                if SETPOINT_SOAK_SECONDS > 0:
                    print(f"Chamber reached {phase}; soaking for {SETPOINT_SOAK_SECONDS:g} seconds.")
            if now - soak_started_at >= SETPOINT_SOAK_SECONDS:
                print(f"Chamber completed {phase} soak within {SETPOINT_TOLERANCE_C:g} C.")
                return
        elif soak_started_at is not None:
            print(f"Chamber drifted outside {phase} tolerance; restarting soak timer.")
            soak_started_at = None
        time.sleep(SNAPSHOT_INTERVAL_SECONDS)


def _return_chamber_to_ambient(controller: F4TController) -> None:
    print(f"Returning chamber setpoint to ambient ({AMBIENT_TEMPERATURE_C:g} C).")
    controller.write_setpoint_c(AMBIENT_TEMPERATURE_C)


def run_temperature_step(part_number: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    artifacts = _temperature_artifacts(folder_name)
    target = _resolve_temperature_target(report_path)
    controller = F4TController(ip=DEFAULT_F4T_IP)

    print(f"Writing temperature snapshots to: {artifacts.snapshot_csv}")
    print(f"Writing temperature performance rows to: {artifacts.performance_csv}")
    print(f"Writing disk tester log to: {artifacts.disk_tester_log}")
    print(f"Using Watlow F4T IP: {DEFAULT_F4T_IP}")

    with ExitStack() as stack:
        csv_handle = stack.enter_context(artifacts.snapshot_csv.open("w", newline="", encoding="utf-8"))
        stdout = stack.enter_context(artifacts.disk_tester_stdout.open("a", encoding="utf-8"))
        stderr = stack.enter_context(artifacts.disk_tester_stderr.open("a", encoding="utf-8"))
        writer = csv.DictWriter(csv_handle, fieldnames=SNAPSHOT_CSV_FIELDS)
        writer.writeheader()
        csv_handle.flush()

        disk_tester = _start_disk_tester(
            target_path=target.drive_target,
            artifacts=artifacts,
            stdout=stdout,
            stderr=stderr,
        )
        try:
            for setpoint_c in TEMPERATURE_SETPOINTS_C:
                _run_snapshot_phase(
                    controller=controller,
                    writer=writer,
                    csv_handle=csv_handle,
                    disk_tester=disk_tester,
                    setpoint_c=setpoint_c,
                )
        except KeyboardInterrupt:
            print("Temperature workflow interrupted; stopping disk tester.")
            raise
        finally:
            _stop_process(disk_tester)

    _return_chamber_to_ambient(controller)
    _finalize_temperature_results(folder_name=folder_name, dut_name=target.dut_name, artifacts=artifacts)
    print(f"Temperature workflow complete. Snapshot CSV: {artifacts.snapshot_csv}")


def post_process_temperature_data(
    *,
    part_number: str | None = None,
    dut_name: str | None = None,
    performance_csv: Path | None = None,
    chart: Path | None = None,
    chart_title: str = "Temperature vs Speed",
) -> Path:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    resolved_dut_name = dut_name or select_report_dut_name(report_path)
    actual_part_number = _part_number_from_report(data, folder_name)

    if performance_csv is not None:
        _update_temperature_report_from_profile(data, resolved_dut_name, performance_csv)
        if chart is None:
            generated_chart = _temperature_chart_path(actual_part_number, resolved_dut_name)
            temperature_plotter.plot_profile_csv(performance_csv, generated_chart, title=chart_title)
            print(f"Saved temperature chart to: {generated_chart}")

    if chart is not None:
        copied_chart = _temperature_chart_path(actual_part_number, resolved_dut_name)
        copied_chart.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chart, copied_chart)
        print(f"Saved temperature chart to: {copied_chart}")

    save_report(report_path, data)
    print(f"Updated temperature data in {report_path}")
    return report_path
