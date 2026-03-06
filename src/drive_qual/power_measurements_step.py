from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from drive_qual import benchmark, tektronix
from drive_qual.apricorn_usb_cli import (
    ApricornDevice,
    device_identity,
    find_apricorn_device,
    get_usb_payload,
    is_same_device,
    list_apricorn_devices,
)
from drive_qual.io_utils import mk_dir
from drive_qual.power_measurements import extract_power_values_from_csv, update_power_measurements_from_saved_csvs
from drive_qual.report_session import load_report, report_path_for, resolve_folder_name
from drive_qual.storage_paths import artifact_dir, artifact_file

DRIVE_TOKEN_WITH_COLON_LEN = 2


def _wait_for_device_present(prompt: str) -> ApricornDevice:
    dut = find_apricorn_device()
    if dut is None:
        print(prompt)
    while dut is None:
        dut = find_apricorn_device()
    print(f"Tracking Apricorn device: {device_identity(dut)}")
    return dut


def _wait_for_device_removed(expected: ApricornDevice, prompt: str) -> None:
    payload = get_usb_payload()
    devices = list_apricorn_devices(payload) if payload else []
    if any(is_same_device(expected, device) for device in devices):
        print(f"{prompt} Waiting on {device_identity(expected)}")
    while any(is_same_device(expected, device) for device in devices):
        payload = get_usb_payload()
        devices = list_apricorn_devices(payload) if payload else []


def _cleanup_test_file(path: str) -> None:
    try:
        os.remove(path)
        print(f"\nCleaned up test file: {path}")
    except OSError as exc:
        print(f"\nError cleaning up test file: {exc}")


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
    if "secure key" in product:
        return "Secure Key"
    return "Portable"


def _dut_label(dut: ApricornDevice) -> str:
    label = (dut.iProduct or "").strip()
    return label or "unknown_device"


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
    print(f"Wrote capture backup entry to {backup_path}")


async def _run_max_io(part_number: str, report_path: Path) -> None:
    dut = _wait_for_device_present("Unlock Apricorn device..")
    tektronix.recall_setup(setup_type="Max IO", device_type=_device_type_for_scope(dut))
    mk_dir(artifact_dir(part_number, "Windows", "Max IO"))

    try:
        target_dir = _normalize_drive_target(dut.driveLetter)
        benchmark_file = benchmark.benchmark_file_path(target_dir, "benchmark_file.dat")
        write_ret = await benchmark.run_fio(target_dir, "write", 10, 100)
        read_ret = await benchmark.run_fio(target_dir, "read", 10, 100)
        _cleanup_test_file(benchmark_file)
        _report_benchmark_results(write_ret, read_ret)
    except Exception as exc:
        print(f"Critical error during Max IO benchmark: {exc}")
    finally:
        device_label = _dut_label(dut)
        csv_path = artifact_file(part_number, "Windows", "Max IO", f"{device_label}.csv")
        tektronix.stop_run()
        parsed_csv_path = tektronix.save_measurements(csv_path)
        tektronix.backup_session(artifact_file(part_number, "Windows", "Max IO", f"{device_label}.png"))
        _write_measurement_backup(report_path, parsed_csv_path, "Max IO")
        _wait_for_device_removed(dut, "Remove Apricorn device..")
        print("")


async def _run_in_rush(part_number: str, report_path: Path) -> None:
    probe = find_apricorn_device()
    device_type = _device_type_for_scope(probe) if probe else "Portable"
    tektronix.recall_setup(setup_type="InRush", device_type=device_type)
    mk_dir(artifact_dir(part_number, "Windows", "In Rush Current"))

    dut = _wait_for_device_present("Unlock Apricorn device..")
    device_label = _dut_label(dut)
    csv_path = artifact_file(part_number, "Windows", "In Rush Current", f"{device_label}.csv")
    tektronix.stop_run()
    parsed_csv_path = tektronix.save_measurements(csv_path)
    tektronix.backup_session(artifact_file(part_number, "Windows", "In Rush Current", f"{device_label}.png"))
    _write_measurement_backup(report_path, parsed_csv_path, "In Rush Current")


def run_power_measurements_step() -> None:
    folder_name = resolve_folder_name(None)
    part_number, report_path = _load_part_number_and_report(folder_name)

    asyncio.run(_run_max_io(part_number, report_path))
    asyncio.run(_run_in_rush(part_number, report_path))

    # Final pass re-reads all CSVs to ensure report JSON is consistent.
    update_power_measurements_from_saved_csvs(part_number=part_number)
