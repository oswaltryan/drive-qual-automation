from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from logging import Logger, getLogger
from pathlib import Path, PureWindowsPath
from types import ModuleType
from typing import Any, Protocol, cast

from drive_qual import benchmarks as benchmark
from drive_qual.core import native_disk_ops
from drive_qual.core.io_utils import mk_dir
from drive_qual.core.power_measurements import extract_power_values_from_csv, update_power_measurements_from_saved_csvs
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.storage_paths import artifact_dir, artifact_file, localize_windows_path
from drive_qual.integrations.apricorn.usb_cli import (
    ApricornDevice,
    device_identity,
    find_apricorn_device,
    get_usb_payload,
    is_same_device,
    list_apricorn_devices,
)
from drive_qual.integrations.instruments import tektronix

DRIVE_TOKEN_WITH_COLON_LEN = 2
SAFE_EJECT_SCRIPT = Path("tools") / "safe_eject.ps1"
DISK_OPS_DIR = Path(__file__).resolve().parents[4] / "tools"
DISK_OPS_PATH = DISK_OPS_DIR / "disk_ops.py"
COMPATIBILITY_SLOTS = ("linux", "macos", "windows")
ARTIFACT_OS_NAME_BY_SLOT = {
    "linux": "Linux",
    "macos": "macOS",
    "windows": "Windows",
}


class _FormatDiskFn(Protocol):
    def __call__(
        self,
        adapter: object,
        device: object,
        label: str = "DUT",
        drive_letter: str | None = None,
        filesystem: str | None = None,
        partition_scheme: str | None = None,
    ) -> bool: ...


def _load_disk_ops_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("drive_qual_disk_ops", DISK_OPS_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load disk ops module from {_display_path(DISK_OPS_PATH)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _format_disk() -> _FormatDiskFn:
    module = _load_disk_ops_module()
    return cast(_FormatDiskFn, module._format_disk)


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


class _DiskOpsAdapter:
    def __init__(self, dut: ApricornDevice) -> None:
        self.dut = dut
        self.logger: Logger = getLogger("drive_qual.platforms.windows.power_measurements.disk_ops")

    def _normalize_windows_drive_letter(self, drive_letter: str | None) -> str | None:
        if not drive_letter:
            return None
        token = drive_letter.split(",")[0].strip().replace("\\", "").replace("/", "")
        if token.endswith(":"):
            token = token[:-1]
        if len(token) != 1 or not token.isalpha():
            return None
        return f"{token.upper()}:"

    def _resolve_serial_reference(self) -> str | None:
        return self.dut.iSerial

    def _update_dut_from_device_info(
        self,
        _device_info: object,
        *,
        stage: str,
        volume_present: bool,
        refresh_from_tool: bool,
        serial_number: str | None,
    ) -> None:
        del _device_info, stage, volume_present, refresh_from_tool, serial_number


def _partition_and_format_drive(dut: ApricornDevice) -> bool:
    if dut.physicalDriveNum is None:
        print(f"Skipping partition/format; disk number unavailable for {device_identity(dut)}")
        return False

    adapter = _DiskOpsAdapter(dut)
    drive_letter = adapter._normalize_windows_drive_letter(dut.driveLetter)
    return bool(
        _format_disk()(
            adapter,
            dut.physicalDriveNum,
            label="DUT",
            drive_letter=drive_letter,
        )
    )


def _prompt_disk_management_visible(dut: ApricornDevice) -> bool:
    print(f"\nLaunching Disk Management for {device_identity(dut)}...")
    try:
        subprocess.Popen(["diskmgmt.msc"], shell=True)
    except Exception as exc:
        print(f"Failed to launch Disk Management: {exc}")

    prompt = f"Can the drive be seen in Disk Management for {device_identity(dut)}? [true/false]: "
    while True:
        response = input(prompt).strip().casefold()
        if response == "true":
            return True
        if response == "false":
            return False


def _refresh_device_after_format(
    expected: ApricornDevice, *, attempts: int = 20, delay_seconds: float = 0.5
) -> ApricornDevice:
    for _ in range(attempts):
        current = _find_matching_device(expected)
        if current is not None and current.driveLetter:
            return current
        if current is not None:
            expected = current
        time.sleep(delay_seconds)
    return expected


def _run_safe_eject_script(dut: ApricornDevice) -> bool:
    if dut.physicalDriveNum is None:
        print(f"Skipping safe eject; disk number unavailable for {device_identity(dut)}")
        return False

    script_path = SAFE_EJECT_SCRIPT.resolve()
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-DiskNumber",
        str(dut.physicalDriveNum),
    ]
    print(f"Running safe eject script for {device_identity(dut)}")
    result = subprocess.run(command, check=False)
    if result.returncode == 0:
        return True

    print(f"Safe eject script failed with return code {result.returncode}")
    return False


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


def _normalize_drive_target(raw: str | None) -> str:
    if raw is None or not raw.strip():
        raise RuntimeError("Drive letter not available for device.")
    token = raw.strip()
    if len(token) == 1 and token.isalpha():
        return f"{token}:\\"
    if len(token) == DRIVE_TOKEN_WITH_COLON_LEN and token[1] == ":" and token[0].isalpha():
        return f"{token}\\"
    return token


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


def _prompt_yes_no(prompt: str) -> bool:
    while True:
        response = input(prompt).strip().casefold()
        if response in {"y", "yes", "true"}:
            return True
        if response in {"n", "no", "false"}:
            return False


def _prompt_benchmark_target_directory() -> str:
    prompt = "Benchmark target directory on the mounted device: "
    while True:
        response = input(prompt).strip()
        if not response:
            print("Enter the mounted device directory for fio.")
            continue
        target = Path(response).expanduser()
        if target.exists() and target.is_dir():
            return str(target)
        print(f"Benchmark target directory does not exist: {target}")


def _confirm_safe_removal_non_windows(dut: ApricornDevice) -> bool:
    prompt = f"Safely eject/remove {device_identity(dut)} before disconnecting it? [y/n]: "
    return _prompt_yes_no(prompt)


def _ensure_local_artifact_dir(part_number: str, category: str) -> None:
    win_dir = artifact_dir(part_number, _current_artifact_os_name(), category)
    mk_dir(localize_windows_path(Path(win_dir)))


async def _run_max_io_benchmark(dut: ApricornDevice, report_path: Path) -> ApricornDevice:  # noqa: PLR0915
    if sys.platform == "win32":
        partition_and_format_ok = _partition_and_format_drive(dut)
        _set_current_host_compatibility(report_path, "partition_drive", partition_and_format_ok)
        _set_current_host_compatibility(report_path, "format_drive", partition_and_format_ok)
        if not partition_and_format_ok:
            raise RuntimeError("Partition/format step failed.")

        refreshed_dut = _refresh_device_after_format(dut)
        disk_mgmt_visible = _prompt_disk_management_visible(refreshed_dut)
        _set_windows_compatibility(report_path, "device_manager_disk_mgmt", disk_mgmt_visible)
        target_dir = _normalize_drive_target(refreshed_dut.driveLetter)
    else:
        refreshed_dut = dut
        try:
            prepared = native_disk_ops.prepare_device_for_benchmark(dut)
        except Exception:
            _set_current_host_compatibility(report_path, "partition_drive", False)
            _set_current_host_compatibility(report_path, "format_drive", False)
            raise
        _mark_current_host_compatibility(report_path, "partition_drive")
        _mark_current_host_compatibility(report_path, "format_drive")
        target_dir = prepared.mount_point

    benchmark_file = benchmark.benchmark_file_path(target_dir, "benchmark_file.dat")
    write_ret = await benchmark.run_fio(target_dir, "write", 10, 100)
    if write_ret == 0:
        _mark_current_host_compatibility(report_path, "copy_to_drive")
    read_ret = await benchmark.run_fio(target_dir, "read", 10, 100)
    if read_ret == 0:
        _mark_current_host_compatibility(report_path, "copy_from_drive")
    cleanup_ok = _cleanup_test_file(benchmark_file)
    if cleanup_ok:
        _mark_current_host_compatibility(report_path, "delete_data")
    _report_benchmark_results(write_ret, read_ret)
    return refreshed_dut


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
    dut = _wait_for_confirmed_device_present("Unlock Apricorn device..")
    _mark_current_host_compatibility(report_path, "recognized_by_os")
    tektronix.recall_setup(setup_type="Max IO", device_type=_device_type_for_scope(dut))
    _ensure_local_artifact_dir(part_number, "Max IO")

    try:
        dut = await _run_max_io_benchmark(dut, report_path)
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
            if _run_safe_eject_script(dut):
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

    dut = _wait_for_device_present("Reconnect Apricorn device..", expected=expected_dut)
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
