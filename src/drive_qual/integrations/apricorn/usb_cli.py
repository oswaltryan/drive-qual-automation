from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, cast

APRICON_NAME = "apricorn"
MIN_USB_3_BCD = 3.0


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
    blockDevice: str | None = None
    diskIdentifier: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], drive_letter: str | None = None) -> ApricornDevice:
        physical_drive_num = raw.get("physicalDriveNum")
        physical_drive_num = physical_drive_num if isinstance(physical_drive_num, int) else None
        normalized_drive_letter = raw.get("driveLetter")
        bcd_usb = _coerce_bcd_usb(raw.get("bcdUSB"))
        return cls(
            bcdUSB=bcd_usb,
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
            blockDevice=raw.get("blockDevice"),
            diskIdentifier=raw.get("diskIdentifier"),
        )


def _coerce_bcd_usb(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _normalized_serial(value: str | None) -> str:
    return (value or "").strip().casefold()


def device_identity(device: ApricornDevice) -> str:
    details: list[str] = []
    if device.iProduct:
        details.append(device.iProduct)
    if device.iSerial:
        details.append(f"serial={device.iSerial}")
    if device.driveLetter:
        details.append(f"drive={device.driveLetter}")
    if device.physicalDriveNum is not None:
        details.append(f"disk={device.physicalDriveNum}")
    if device.blockDevice:
        details.append(f"block={device.blockDevice}")
    if device.busNumber is not None and device.deviceAddress is not None:
        details.append(f"usb={device.busNumber}:{device.deviceAddress}")
    if not details:
        return "unknown Apricorn device"
    return ", ".join(details)


def _is_apricorn_device(raw: dict[str, Any]) -> bool:
    manufacturer = raw.get("iManufacturer")
    if isinstance(manufacturer, str) and APRICON_NAME in manufacturer.casefold():
        return True
    scb_part_number = raw.get("scbPartNumber")
    if isinstance(scb_part_number, str) and scb_part_number.strip():
        return True
    model_id = raw.get("modelID")
    return isinstance(model_id, str) and bool(model_id.strip())


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


def list_apricorn_devices(payload: dict[str, Any]) -> list[ApricornDevice]:
    devices: list[ApricornDevice] = []
    for device_info in list_usb_devices(payload):
        if not _is_apricorn_device(device_info):
            continue
        devices.append(ApricornDevice.from_dict(device_info))
    return devices


def find_apricorn_device_by_serial(devices: list[ApricornDevice], serial: str | None) -> ApricornDevice | None:
    normalized_target = _normalized_serial(serial)
    if not normalized_target:
        return None
    for device in devices:
        if _normalized_serial(device.iSerial) == normalized_target:
            return device
    return None


def resolve_apricorn_device_by_serial(payload: dict[str, Any], serial: str | None) -> ApricornDevice | None:
    devices = list_apricorn_devices(payload)
    return find_apricorn_device_by_serial(devices, serial)


def select_apricorn_device(devices: list[ApricornDevice]) -> ApricornDevice | None:
    if not devices:
        return None
    if len(devices) == 1:
        return devices[0]

    print("Multiple Apricorn devices detected:")
    for index, device in enumerate(devices, start=1):
        print(f"{index}. {device_identity(device)}")

    while True:
        entry = input("Select Apricorn device number: ").strip()
        try:
            selection = int(entry)
        except ValueError:
            continue
        if 1 <= selection <= len(devices):
            return devices[selection - 1]


def is_same_device(expected: ApricornDevice, current: ApricornDevice) -> bool:
    if expected.iSerial and current.iSerial:
        return expected.iSerial == current.iSerial
    if expected.physicalDriveNum is not None and current.physicalDriveNum is not None:
        return expected.physicalDriveNum == current.physicalDriveNum
    if expected.blockDevice and current.blockDevice:
        return expected.blockDevice == current.blockDevice
    if expected.driveLetter and current.driveLetter:
        return expected.driveLetter == current.driveLetter
    if (
        expected.busNumber is not None
        and current.busNumber is not None
        and expected.deviceAddress is not None
        and current.deviceAddress is not None
    ):
        return expected.busNumber == current.busNumber and expected.deviceAddress == current.deviceAddress
    return (
        expected.idVendor == current.idVendor
        and expected.idProduct == current.idProduct
        and expected.iProduct == current.iProduct
    )


def usb_generation_label(device: ApricornDevice) -> str:
    if device.bcdUSB is None:
        return "unknown USB version"
    return f"USB {device.bcdUSB:.2f}"


def is_usb_3x(device: ApricornDevice) -> bool:
    bcd_usb = device.bcdUSB
    return bcd_usb is not None and bcd_usb >= MIN_USB_3_BCD


def missing_required_fields(device: ApricornDevice, required_fields: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for field_name in required_fields:
        value = getattr(device, field_name)
        if isinstance(value, str):
            if value.strip():
                continue
            missing.append(field_name)
            continue
        if value is None:
            missing.append(field_name)
    return missing


def find_apricorn_device() -> ApricornDevice | None:
    """Return the selected detected Apricorn device using the `usb --json` CLI output."""
    data = get_usb_payload()
    if not data:
        return None

    devices = list_apricorn_devices(data)
    return select_apricorn_device(devices)
