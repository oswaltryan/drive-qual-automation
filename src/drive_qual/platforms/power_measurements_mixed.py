from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from drive_qual import benchmarks as benchmark
from drive_qual.core import native_disk_ops
from drive_qual.core.dut_selection import (
    find_report_dut_name_by_serial,
    refresh_report_dut_device,
    resolve_or_bind_report_dut_device,
    select_report_dut_name,
)
from drive_qual.core.io_utils import mk_dir
from drive_qual.core.power_measurements import extract_power_values_from_csv, update_power_measurements_from_saved_csvs
from drive_qual.core.report_session import (
    load_report,
    report_path_for,
    resolve_folder_name,
    sanitize_dir_name,
    save_report,
    set_current_session,
)
from drive_qual.core.storage_paths import artifact_dir, artifact_file, localize_windows_path
from drive_qual.integrations.apricorn.usb_cli import (
    ApricornDevice,
    device_identity,
    find_apricorn_device,
    find_apricorn_device_by_serial,
    get_usb_payload,
    is_same_device,
    is_usb_3x,
    list_apricorn_devices,
)
from drive_qual.integrations.instruments import tektronix

COMPATIBILITY_SLOTS = ("linux", "macos", "windows")
ARTIFACT_OS_NAME_BY_SLOT = {
    "linux": "Linux",
    "macos": "macOS",
    "windows": "Windows",
}


def _display_path(path: str | Path) -> str:
    return PureWindowsPath(str(path)).as_posix()


def _current_report_os_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    return "windows"


def _current_artifact_os_name() -> str:
    return ARTIFACT_OS_NAME_BY_SLOT[_current_report_os_key()]


def _compatibility_field_template(field_name: str) -> dict[str, bool | None]:
    if field_name == "device_manager_disk_mgmt":
        return {"windows": None}
    return {slot: None for slot in COMPATIBILITY_SLOTS}


def _set_compatibility_for_slot(report_path: Path, field_name: str, slot: str, value: bool) -> None:
    data = load_report(report_path)
    compatibility = data.setdefault("compatibility", {})
    if not isinstance(compatibility, dict):
        raise ValueError("Missing or invalid 'compatibility' section in report.")

    field = compatibility.setdefault(field_name, _compatibility_field_template(field_name))
    if not isinstance(field, dict):
        field = _compatibility_field_template(field_name)
        compatibility[field_name] = field

    if slot not in field:
        field[slot] = None
    if field.get(slot) is value:
        return

    field[slot] = value
    save_report(report_path, data)


def _set_windows_compatibility(report_path: Path, field_name: str, value: bool) -> None:
    _set_compatibility_for_slot(report_path, field_name, "windows", value)


def _mark_windows_compatibility(report_path: Path, field_name: str) -> None:
    _set_windows_compatibility(report_path, field_name, True)


def _set_current_host_compatibility(report_path: Path, field_name: str, value: bool) -> None:
    _set_compatibility_for_slot(report_path, field_name, _current_report_os_key(), value)


def _mark_current_host_compatibility(report_path: Path, field_name: str) -> None:
    _set_current_host_compatibility(report_path, field_name, True)


def _refresh_device_after_format(
    expected: ApricornDevice, *, attempts: int = 20, delay_seconds: float = 0.5
) -> ApricornDevice:
    for _ in range(attempts):
        payload = get_usb_payload()
        devices = list_apricorn_devices(payload) if payload else []
        current = find_apricorn_device_by_serial(devices, expected.iSerial)
        if current is None:
            current = _find_matching_device(expected)
        if current is not None and current.driveLetter and is_usb_3x(current):
            return current
        if current is not None:
            expected = current
        time.sleep(delay_seconds)
    return expected


def _required_device_fields_for_current_host() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("physicalDriveNum",)
    if sys.platform.startswith("linux"):
        return ("blockDevice",)
    return ()


def _select_report_dut_name(report_path: Path) -> str:
    return select_report_dut_name(report_path)


def _resolve_device_for_report_dut(
    report_path: Path,
    dut_name: str,
    prompt: str,
    *,
    required_fields: tuple[str, ...] | None = None,
) -> ApricornDevice:
    fields = _required_device_fields_for_current_host() if required_fields is None else required_fields
    device = resolve_or_bind_report_dut_device(
        report_path,
        dut_name,
        prompt=prompt,
        required_fields=fields,
    )
    print(f"Tracking Apricorn device: {device_identity(device)}")
    return device


def _refresh_device_for_report_dut(
    report_path: Path,
    dut_name: str,
    prompt: str,
    *,
    required_fields: tuple[str, ...] | None = None,
) -> ApricornDevice:
    fields = _required_device_fields_for_current_host() if required_fields is None else required_fields
    device = refresh_report_dut_device(
        report_path,
        dut_name,
        prompt=prompt,
        required_fields=fields,
    )
    print(f"Tracking Apricorn device: {device_identity(device)}")
    return device


def _find_matching_device(expected: ApricornDevice | None) -> ApricornDevice | None:
    if expected is None:
        return find_apricorn_device()

    payload = get_usb_payload()
    devices = list_apricorn_devices(payload) if payload else []
    for device in devices:
        if is_same_device(expected, device):
            return device
    return None


def _wait_for_device_present(prompt: str, expected: ApricornDevice | None = None) -> ApricornDevice:
    dut = _find_matching_device(expected)
    if dut is None:
        if expected is None:
            print(prompt)
        else:
            print(f"{prompt} Waiting on {device_identity(expected)}")
    while dut is None:
        dut = _find_matching_device(expected)
    print(f"Tracking Apricorn device: {device_identity(dut)}")
    return dut


def _confirm_selected_device(dut: ApricornDevice) -> bool:
    prompt = f"Use Apricorn device {device_identity(dut)}? [y/n]: "
    while True:
        response = input(prompt).strip().casefold()
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False


def _wait_for_confirmed_device_present(prompt: str) -> ApricornDevice:
    while True:
        dut = _wait_for_device_present(prompt)
        if _confirm_selected_device(dut):
            return dut
        print("Select or connect the correct Apricorn device.")


def _wait_for_device_removed(expected: ApricornDevice, prompt: str) -> None:
    payload = get_usb_payload()
    devices = list_apricorn_devices(payload) if payload else []
    if any(is_same_device(expected, device) for device in devices):
        print(f"{prompt} Waiting on {device_identity(expected)}")
    while any(is_same_device(expected, device) for device in devices):
        payload = get_usb_payload()
        devices = list_apricorn_devices(payload) if payload else []


def _cleanup_test_file(path: str) -> bool:
    try:
        os.remove(path)
        print(f"\nCleaned up test file: {path}")
        return True
    except OSError as exc:
        print(f"\nError cleaning up test file: {exc}")
        return False


def _report_benchmark_results(write_ret: int, read_ret: int) -> None:
    if write_ret == 0 and read_ret == 0:
        print("\nBenchmark completed successfully")
    else:
        print(f"\nBenchmark failed - Write: {write_ret}, Read: {read_ret}")


def _device_type_for_scope(dut: ApricornDevice) -> str:
    product = (dut.iProduct or "").strip().lower()
    if "dt" in product:
        return "DT"
    return "generic"


def _dut_label(dut: ApricornDevice) -> str:
    label = (dut.iProduct or "").strip()
    return label or "unknown_device"


def _ensure_local_artifact_dir(part_number: str, category: str) -> None:
    win_dir = artifact_dir(part_number, _current_artifact_os_name(), category)
    mk_dir(localize_windows_path(Path(win_dir)))


def _prepare_benchmark_target(
    dut: ApricornDevice,
    report_path: Path,
    *,
    dut_name: str | None,
) -> tuple[ApricornDevice, str]:
    if sys.platform == "win32":
        from drive_qual.platforms.windows.power_measurements import (
            normalize_drive_target,
            partition_and_format_drive,
            prompt_disk_management_visible,
        )

        partition_and_format_ok = partition_and_format_drive(dut)
        _set_current_host_compatibility(report_path, "partition_drive", partition_and_format_ok)
        _set_current_host_compatibility(report_path, "format_drive", partition_and_format_ok)
        if not partition_and_format_ok:
            raise RuntimeError("Partition/format step failed.")

        if dut_name is None:
            refreshed_dut = _refresh_device_after_format(dut)
        else:
            refreshed_dut = _refresh_device_for_report_dut(
                report_path,
                dut_name,
                "Waiting for DUT to re-enumerate after format...",
                required_fields=("physicalDriveNum", "driveLetter"),
            )
        disk_mgmt_visible = prompt_disk_management_visible(refreshed_dut)
        _set_windows_compatibility(report_path, "device_manager_disk_mgmt", disk_mgmt_visible)
        target_dir = normalize_drive_target(refreshed_dut.driveLetter)
        return refreshed_dut, target_dir

    try:
        prepared = native_disk_ops.prepare_device_for_benchmark(dut)
    except Exception:
        _set_current_host_compatibility(report_path, "partition_drive", False)
        _set_current_host_compatibility(report_path, "format_drive", False)
        raise

    _mark_current_host_compatibility(report_path, "partition_drive")
    _mark_current_host_compatibility(report_path, "format_drive")
    return dut, prepared.mount_point


async def _run_max_io_benchmark(dut: ApricornDevice, report_path: Path, dut_name: str | None = None) -> ApricornDevice:
    # Fail fast before partition/format operations if fio is unavailable.
    benchmark.require_fio()
    refreshed_dut, target_dir = _prepare_benchmark_target(dut, report_path, dut_name=dut_name)

    benchmark_file = benchmark.benchmark_file_path(target_dir, "benchmark_file.dat")
    write_ret = await benchmark.run_fio(target_dir, "write", 10, 100)
    _set_current_host_compatibility(report_path, "copy_to_drive", write_ret == 0)
    read_ret = await benchmark.run_fio(target_dir, "read", 10, 100)
    _set_current_host_compatibility(report_path, "copy_from_drive", read_ret == 0)
    cleanup_ok = _cleanup_test_file(benchmark_file)
    _set_current_host_compatibility(report_path, "delete_data", cleanup_ok)
    _report_benchmark_results(write_ret, read_ret)
    return refreshed_dut


def _load_part_number_and_report(folder_name: str) -> tuple[str, Path]:
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    drive_info = data.get("drive_info")
    part_number = folder_name
    report_folder = folder_name
    if isinstance(drive_info, dict):
        raw = drive_info.get("apricorn_part_number")
        if isinstance(raw, str) and raw.strip():
            part_number = raw.strip()
            sanitized = sanitize_dir_name(part_number)
            if sanitized:
                report_folder = sanitized

    canonical_report_path = report_path_for(report_folder)
    if canonical_report_path != report_path:
        save_report(canonical_report_path, data)
        set_current_session(report_folder)
        report_path = canonical_report_path

    return part_number, report_path


def _write_measurement_backup(report_path: Path, csv_path: str, measurement_group: str) -> None:
    backup_path = report_path.parent / "power_measurements_backup.json"
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "csv_path": csv_path,
        "group": measurement_group,
        "values": extract_power_values_from_csv(csv_path),
    }
    payload: dict[str, Any] = {"captures": []}
    if backup_path.exists():
        try:
            loaded = json.loads(backup_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {"captures": []}
    captures = payload.get("captures")
    if not isinstance(captures, list):
        captures = []
        payload["captures"] = captures
    captures.append(entry)
    backup_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote capture backup entry to {_display_path(backup_path)}")


async def _run_max_io(part_number: str, report_path: Path) -> ApricornDevice:
    dut_name = _select_report_dut_name(report_path)
    dut = _resolve_device_for_report_dut(report_path, dut_name, "Unlock Apricorn device..")
    _mark_current_host_compatibility(report_path, "recognized_by_os")
    tektronix.recall_setup(setup_type="Max IO", device_type=_device_type_for_scope(dut))
    _ensure_local_artifact_dir(part_number, "Max IO")

    try:
        dut = await _run_max_io_benchmark(dut, report_path, dut_name=dut_name)
    except Exception as exc:
        print(f"Critical error during Max IO benchmark: {exc}")
    finally:
        device_label = _dut_label(dut)
        artifact_os = _current_artifact_os_name()
        csv_path = artifact_file(part_number, artifact_os, "Max IO", f"{device_label}.csv")
        tektronix.stop_run()
        parsed_csv_path = tektronix.save_measurements(csv_path)
        tektronix.backup_session(artifact_file(part_number, artifact_os, "Max IO", f"{device_label}.png"))
        _write_measurement_backup(report_path, parsed_csv_path, "Max IO")
        if sys.platform == "win32":
            from drive_qual.platforms.windows.power_measurements import run_safe_eject_script

            if run_safe_eject_script(dut):
                _mark_current_host_compatibility(report_path, "safely_remove")
        elif native_disk_ops.safe_remove_device(dut):
            _mark_current_host_compatibility(report_path, "safely_remove")
        _wait_for_device_removed(dut, "Remove Apricorn device..")
        print("")
    return dut


async def _run_in_rush(part_number: str, report_path: Path, expected_dut: ApricornDevice) -> None:
    device_type = _device_type_for_scope(expected_dut)
    tektronix.recall_setup(setup_type="InRush", device_type=device_type)
    _ensure_local_artifact_dir(part_number, "In Rush Current")

    dut_name = find_report_dut_name_by_serial(report_path, expected_dut.iSerial)
    if dut_name is None:
        dut_name = _select_report_dut_name(report_path)
    dut = _refresh_device_for_report_dut(report_path, dut_name, "Reconnect Apricorn device..")
    _mark_current_host_compatibility(report_path, "hot_pluggable")
    device_label = _dut_label(dut)
    artifact_os = _current_artifact_os_name()
    csv_path = artifact_file(part_number, artifact_os, "In Rush Current", f"{device_label}.csv")
    tektronix.stop_run()
    parsed_csv_path = tektronix.save_measurements(csv_path)
    tektronix.backup_session(artifact_file(part_number, artifact_os, "In Rush Current", f"{device_label}.png"))
    _write_measurement_backup(report_path, parsed_csv_path, "In Rush Current")


def run_power_measurements_step() -> None:
    folder_name = resolve_folder_name(None)
    part_number, report_path = _load_part_number_and_report(folder_name)

    dut = asyncio.run(_run_max_io(part_number, report_path))
    asyncio.run(_run_in_rush(part_number, report_path, dut))

    # Final pass re-reads all CSVs to ensure report JSON is consistent.
    update_power_measurements_from_saved_csvs(part_number=part_number)
