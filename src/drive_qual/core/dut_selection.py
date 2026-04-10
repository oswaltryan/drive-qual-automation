from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from drive_qual.core.report_session import load_report, save_report
from drive_qual.integrations.apricorn.usb_cli import (
    ApricornDevice,
    device_identity,
    find_apricorn_device_by_serial,
    get_usb_payload,
    is_usb_3x,
    list_apricorn_devices,
    missing_required_fields,
    select_apricorn_device,
    usb_generation_label,
)

DutBindings = dict[str, dict[str, Any]]


def _normalized_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalized_serial(value: Any) -> str | None:
    serial = _normalized_optional_string(value)
    if serial is None:
        return None
    return serial


def normalize_dut_bindings(raw: Any) -> DutBindings:
    if isinstance(raw, list):
        normalized: DutBindings = {}
        for value in raw:
            dut_name = _normalized_optional_string(value)
            if dut_name is None:
                continue
            normalized[dut_name] = {"serial_number": None}
        return normalized

    if not isinstance(raw, dict):
        return {}

    normalized = {}
    for key, value in raw.items():
        dut_name = _normalized_optional_string(key)
        if dut_name is None:
            continue
        if isinstance(value, dict):
            entry = dict(value)
            entry["serial_number"] = _normalized_serial(entry.get("serial_number"))
            normalized[dut_name] = entry
            continue
        normalized[dut_name] = {"serial_number": _normalized_serial(value)}
    return normalized


def coerce_equipment_dut_bindings(equipment: dict[str, Any]) -> tuple[DutBindings, bool]:
    current = equipment.get("dut")
    normalized = normalize_dut_bindings(current)
    changed = current != normalized
    equipment["dut"] = normalized
    return normalized, changed


def dut_names_from_equipment(equipment: dict[str, Any]) -> list[str]:
    normalized = normalize_dut_bindings(equipment.get("dut"))
    return list(normalized)


def _poll_limit_exceeded(poll_count: int, max_polls: int | None) -> bool:
    if max_polls is None:
        return False
    return poll_count >= max_polls


def _current_apricorn_devices() -> list[ApricornDevice]:
    payload = get_usb_payload()
    if not isinstance(payload, dict):
        return []
    return list_apricorn_devices(payload)


def _select_dut_name_from_prompt(dut_bindings: DutBindings, present_serials: set[str]) -> str:
    print("Multiple report DUT entries detected:")
    names = list(dut_bindings)
    for index, dut_name in enumerate(names, start=1):
        serial = _normalized_serial(dut_bindings[dut_name].get("serial_number"))
        if serial is None:
            status = "unbound"
        elif serial.casefold() in present_serials:
            status = f"serial={serial}, present"
        else:
            status = f"serial={serial}, not present"
        print(f"{index}. {dut_name} ({status})")

    while True:
        entry = input("Select DUT number: ").strip()
        try:
            selection = int(entry)
        except ValueError:
            continue
        if 1 <= selection <= len(names):
            return names[selection - 1]


def select_report_dut_name(report_path: Path) -> str:
    data = load_report(report_path)
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section in report.")

    dut_bindings, changed = coerce_equipment_dut_bindings(equipment)
    if changed:
        save_report(report_path, data)

    if not dut_bindings:
        raise ValueError("Missing or invalid 'equipment.dut' section in report.")
    if len(dut_bindings) == 1:
        return next(iter(dut_bindings))

    devices = _current_apricorn_devices()
    serials_present = {
        serial.casefold() for serial in (_normalized_serial(device.iSerial) for device in devices) if serial is not None
    }
    auto_matched = [
        dut_name
        for dut_name, binding in dut_bindings.items()
        if (_normalized_serial(binding.get("serial_number")) or "").casefold() in serials_present
    ]
    if len(auto_matched) == 1:
        return auto_matched[0]

    return _select_dut_name_from_prompt(dut_bindings, serials_present)


def _wait_for_serial_as_usb_3x(
    *,
    serial_number: str,
    dut_name: str,
    prompt: str,
    poll_interval_seconds: float,
    max_polls: int | None,
    required_fields: tuple[str, ...],
) -> ApricornDevice:
    poll_count = 0
    state = "initial"

    while True:
        device = find_apricorn_device_by_serial(_current_apricorn_devices(), serial_number)
        if device is None:
            if state != "missing":
                print(prompt)
                print(f"Waiting for DUT '{dut_name}' with serial {serial_number} to enumerate.")
            state = "missing"
        elif not is_usb_3x(device):
            if state != "usb2":
                print(
                    f"DUT '{dut_name}' ({device_identity(device)}) is currently {usb_generation_label(device)}. "
                    "Terminate and reconnect as USB 3.x."
                )
            state = "usb2"
        else:
            missing = missing_required_fields(device, required_fields)
            if missing:
                fields = ", ".join(missing)
                raise RuntimeError(f"DUT '{dut_name}' is missing required usb --json fields for this step: {fields}.")
            return device

        poll_count += 1
        if _poll_limit_exceeded(poll_count, max_polls):
            raise RuntimeError(
                f"Timed out waiting for DUT '{dut_name}' serial {serial_number} to enumerate as USB 3.x."
            )
        time.sleep(poll_interval_seconds)


def _select_usb_3x_device_for_binding(
    *,
    dut_name: str,
    prompt: str,
    poll_interval_seconds: float,
    max_polls: int | None,
) -> ApricornDevice:
    poll_count = 0
    state = "initial"

    while True:
        devices = _current_apricorn_devices()
        usb_3x_devices = [device for device in devices if is_usb_3x(device)]
        if usb_3x_devices:
            selected = select_apricorn_device(usb_3x_devices)
            if selected is None:
                raise RuntimeError("No Apricorn device selected.")
            if _normalized_serial(selected.iSerial) is None:
                print(f"Selected device is missing a serial number in usb --json: {device_identity(selected)}")
            else:
                return selected
            state = "selected_without_serial"
        elif not devices:
            if state != "missing":
                print(prompt)
                print(f"Waiting for Apricorn device enumeration to bind DUT '{dut_name}'.")
            state = "missing"
        else:
            if state != "usb2":
                print("Detected Apricorn devices are not enumerated as USB 3.x. Reconnect as USB 3.x to continue.")
            state = "usb2"

        poll_count += 1
        if _poll_limit_exceeded(poll_count, max_polls):
            raise RuntimeError(f"Timed out while binding DUT '{dut_name}' to a USB 3.x Apricorn device.")
        time.sleep(poll_interval_seconds)


def _load_report_with_dut_bindings(report_path: Path) -> tuple[dict[str, Any], DutBindings]:
    data = load_report(report_path)
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section in report.")
    bindings, changed = coerce_equipment_dut_bindings(equipment)
    if changed:
        save_report(report_path, data)
    return data, bindings


def _bound_serial_for_dut(bindings: DutBindings, dut_name: str) -> str | None:
    binding = bindings.get(dut_name)
    if not isinstance(binding, dict):
        return None
    return _normalized_serial(binding.get("serial_number"))


def resolve_or_bind_report_dut_device(
    report_path: Path,
    dut_name: str,
    *,
    prompt: str,
    poll_interval_seconds: float = 1.0,
    max_polls: int | None = None,
    required_fields: tuple[str, ...] = (),
) -> ApricornDevice:
    data, bindings = _load_report_with_dut_bindings(report_path)
    if dut_name not in bindings:
        available = ", ".join(bindings) if bindings else "<none>"
        raise ValueError(f"Unknown DUT '{dut_name}'. Available DUT keys: {available}")

    serial_number = _bound_serial_for_dut(bindings, dut_name)
    if serial_number is None:
        selected = _select_usb_3x_device_for_binding(
            dut_name=dut_name,
            prompt=prompt,
            poll_interval_seconds=poll_interval_seconds,
            max_polls=max_polls,
        )
        serial_number = _normalized_serial(selected.iSerial)
        if serial_number is None:
            raise RuntimeError(f"Selected DUT '{dut_name}' device is missing serial number.")
        bindings[dut_name]["serial_number"] = serial_number
        save_report(report_path, data)

    return _wait_for_serial_as_usb_3x(
        serial_number=serial_number,
        dut_name=dut_name,
        prompt=prompt,
        poll_interval_seconds=poll_interval_seconds,
        max_polls=max_polls,
        required_fields=required_fields,
    )


def refresh_report_dut_device(
    report_path: Path,
    dut_name: str,
    *,
    prompt: str,
    poll_interval_seconds: float = 1.0,
    max_polls: int | None = None,
    required_fields: tuple[str, ...] = (),
) -> ApricornDevice:
    _data, bindings = _load_report_with_dut_bindings(report_path)
    serial_number = _bound_serial_for_dut(bindings, dut_name)
    if serial_number is None:
        raise RuntimeError(f"DUT '{dut_name}' has no persisted serial_number in equipment.dut.")
    return _wait_for_serial_as_usb_3x(
        serial_number=serial_number,
        dut_name=dut_name,
        prompt=prompt,
        poll_interval_seconds=poll_interval_seconds,
        max_polls=max_polls,
        required_fields=required_fields,
    )


def find_report_dut_name_by_serial(report_path: Path, serial_number: str | None) -> str | None:
    normalized_serial = _normalized_serial(serial_number)
    if normalized_serial is None:
        return None
    _data, bindings = _load_report_with_dut_bindings(report_path)
    for dut_name, binding in bindings.items():
        if _bound_serial_for_dut(bindings, dut_name) is None:
            continue
        bound_serial = _normalized_serial(binding.get("serial_number"))
        if bound_serial is not None and bound_serial.casefold() == normalized_serial.casefold():
            return dut_name
    return None
