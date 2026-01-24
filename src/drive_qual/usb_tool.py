from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class ApricornDevice:
    bcdUSB: float | None = None
    idVendor: str | None = None
    idProduct: str | None = None
    bcdDevice: str | None = None
    iManufacturer: str | None = None
    iProduct: str | None = None
    iSerial: str | None = None
    SCSIDevice: bool | None = None
    driveSizeGB: str | None = None
    mediaType: str | None = None
    usbController: str | None = None
    busNumber: int | None = None
    deviceAddress: int | None = None
    physicalDriveNum: int | None = None
    readOnly: bool | None = None
    scbPartNumber: str | None = None
    hardwareVersion: str | None = None
    modelID: str | None = None
    mcuFW: str | None = None
    driveLetter: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], drive_letter: str | None = None) -> ApricornDevice:
        physical_drive_num = raw.get("physicalDriveNum")
        physical_drive_num = physical_drive_num if isinstance(physical_drive_num, int) else None
        normalized_drive_letter = raw.get("driveLetter")
        return cls(
            bcdUSB=raw.get("bcdUSB"),
            idVendor=raw.get("idVendor"),
            idProduct=raw.get("idProduct"),
            bcdDevice=raw.get("bcdDevice"),
            iManufacturer=raw.get("iManufacturer"),
            iProduct=raw.get("iProduct"),
            iSerial=raw.get("iSerial"),
            SCSIDevice=raw.get("SCSIDevice"),
            driveSizeGB=raw.get("driveSizeGB"),
            mediaType=raw.get("mediaType"),
            usbController=raw.get("usbController"),
            busNumber=raw.get("busNumber"),
            deviceAddress=raw.get("deviceAddress"),
            physicalDriveNum=physical_drive_num,
            readOnly=raw.get("readOnly"),
            scbPartNumber=raw.get("scbPartNumber"),
            hardwareVersion=raw.get("hardwareVersion"),
            modelID=raw.get("modelID"),
            mcuFW=raw.get("mcuFW"),
            driveLetter=drive_letter or normalized_drive_letter,
        )


def _extract_json(payload: str) -> dict[str, Any] | None:
    start = payload.find("{")
    end = payload.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return cast(dict[str, Any], json.loads(payload[start : end + 1]))
    except json.JSONDecodeError:
        return None


def get_usb_payload() -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            ["usb", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    return _extract_json(result.stdout)


def list_usb_devices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    devices = payload.get("devices")
    if not isinstance(devices, list) or not devices:
        return []

    device_infos: list[dict[str, Any]] = []
    for entry in devices:
        if not isinstance(entry, dict) or not entry:
            continue
        device_info = next(iter(entry.values()))
        if isinstance(device_info, dict):
            device_infos.append(device_info)
    return device_infos


def find_apricorn_device() -> ApricornDevice | None:
    """Return the first detected Apricorn device using the `usb --json` CLI output."""
    data = get_usb_payload()
    if not data:
        return None

    device_infos = list_usb_devices(data)
    if not device_infos:
        return None

    device_info = device_infos[0]

    return ApricornDevice.from_dict(device_info)
