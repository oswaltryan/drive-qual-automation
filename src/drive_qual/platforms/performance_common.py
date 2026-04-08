from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from drive_qual.core.report_session import load_report, report_path_for
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice, find_apricorn_device

HOST_OS_NAMES: dict[str, str] = {
    "windows_host": "Windows",
    "linux_host": "Linux",
    "macos_host": "macOS",
}


def software_entries_for_host(equipment: dict[str, Any], host_key: str) -> list[dict[str, Any]]:
    host_data = equipment.get(host_key, {})
    if not isinstance(host_data, dict):
        return []
    software = host_data.get("software", [])
    if not isinstance(software, list):
        return []
    return [entry for entry in software if isinstance(entry, dict)]


def find_report_dut_key(performance: dict[str, Any], dut_name: str) -> str | None:
    dut_cf = dut_name.casefold()
    for key in performance:
        key_cf = key.casefold()
        if key_cf in dut_cf or dut_cf in key_cf:
            return key
    return None


def resolve_report_dut_key(performance: dict[str, Any], dut_name: str) -> str | None:
    report_dut_key = find_report_dut_key(performance, dut_name)
    if report_dut_key is not None:
        return report_dut_key
    if len(performance) == 1:
        return next(iter(performance))
    return None


def to_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        clean_val = "".join(c for k, c in enumerate(val) if c.isdigit() or c == "." or (c == "-" and k == 0))
        return float(clean_val)
    except (ValueError, TypeError):
        return None


def wait_for_device_present(prompt: str) -> ApricornDevice:
    dut = find_apricorn_device()
    if dut is None:
        print(f"\n{prompt}")
    while dut is None:
        time.sleep(1)
        dut = find_apricorn_device()
    return dut


def sync_performance_section(data: dict[str, Any], equipment: dict[str, Any]) -> None:
    performance = data.setdefault("performance", {})
    duts = equipment.get("dut", [])
    for dut in duts:
        perf_dut = performance.setdefault(dut, {"Windows": {}, "Linux": {}, "macOS": {}})
        for host_key, os_key in HOST_OS_NAMES.items():
            os_perf = perf_dut.setdefault(os_key, {})
            for software in software_entries_for_host(equipment, host_key):
                name = software.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                if name == "CrystalDiskInfo":
                    cdi_dict = os_perf.setdefault(name, {"screenshot": None})
                    cdi_dict.pop("read", None)
                    cdi_dict.pop("write", None)
                    continue
                os_perf.setdefault(name, {"read": None, "write": None})


def load_part_number_and_report(folder_name: str) -> tuple[str, Path]:
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    drive_info = data.get("drive_info")
    part_number = folder_name
    if isinstance(drive_info, dict):
        raw = drive_info.get("apricorn_part_number")
        if isinstance(raw, str) and raw.strip():
            part_number = raw.strip()
    return part_number, report_path
