from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class ApricornDevice:
    iProduct: str
    physicalDriveNum: int | None
    driveLetter: str | None


def _extract_json(payload: str) -> dict[str, Any] | None:
    start = payload.find("{")
    end = payload.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return cast(dict[str, Any], json.loads(payload[start : end + 1]))
    except json.JSONDecodeError:
        return None


def _drive_letter_from_physical(physical_drive_num: int) -> str | None:
    command = (
        f"(Get-Disk -Number {physical_drive_num} | "
        "Get-Partition | Get-Volume | "
        "Select -ExpandProperty DriveLetter) -join ''"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    letter = result.stdout.strip()
    if not letter:
        return None
    return f"{letter}:\\"


def find_apricorn_device() -> ApricornDevice | None:
    """Return the first detected Apricorn device using the `usb --json` CLI output."""
    try:
        result = subprocess.run(
            ["usb", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    data = _extract_json(result.stdout)
    if not data:
        return None

    devices = data.get("devices")
    if not isinstance(devices, list) or not devices:
        return None

    device_entry = devices[0]
    if not isinstance(device_entry, dict) or not device_entry:
        return None

    device_info = next(iter(device_entry.values()))
    if not isinstance(device_info, dict):
        return None

    i_product = str(device_info.get("iProduct", "")).strip()
    physical_drive_num = device_info.get("physicalDriveNum")
    physical_drive_num = physical_drive_num if isinstance(physical_drive_num, int) else None

    drive_letter = device_info.get("driveLetter")
    if isinstance(drive_letter, str) and drive_letter:
        if len(drive_letter) == 1:
            drive_letter = f"{drive_letter}:\\"
        elif len(drive_letter) == 2 and drive_letter[1] == ":":
            drive_letter = f"{drive_letter}\\"
    else:
        drive_letter = _drive_letter_from_physical(physical_drive_num) if physical_drive_num is not None else None

    return ApricornDevice(
        iProduct=i_product,
        physicalDriveNum=physical_drive_num,
        driveLetter=drive_letter,
    )
