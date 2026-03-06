from __future__ import annotations

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.apricorn_usb_cli import (
    ApricornDevice,
    device_identity,
    find_apricorn_device,
    is_same_device,
    list_apricorn_devices,
    select_apricorn_device,
)
from drive_qual.power_measurements_step import _wait_for_device_removed


def test_list_apricorn_devices_filters_non_apricorn_entries() -> None:
    payload = {
        "devices": [
            {"usb0": {"iManufacturer": "Generic", "iProduct": "Thumb Drive", "driveLetter": "F:"}},
            {
                "usb1": {
                    "iManufacturer": "Apricorn",
                    "iProduct": "Secure Key 3.0",
                    "iSerial": "ABC123",
                    "driveLetter": "D:",
                }
            },
        ]
    }

    devices = list_apricorn_devices(payload)

    assert len(devices) == 1
    assert devices[0].iProduct == "Secure Key 3.0"
    assert devices[0].driveLetter == "D:"


def test_find_apricorn_device_returns_first_filtered_apricorn(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "devices": [
            {"usb0": {"iManufacturer": "Generic", "iProduct": "Thumb Drive", "driveLetter": "F:"}},
            {"usb1": {"iManufacturer": "Apricorn", "iProduct": "Secure Key 3.0", "driveLetter": "D:"}},
        ]
    }
    monkeypatch.setattr("drive_qual.apricorn_usb_cli.get_usb_payload", lambda: payload)
    monkeypatch.setattr("builtins.input", lambda _: "1")

    device = find_apricorn_device()

    assert device is not None
    assert device.iProduct == "Secure Key 3.0"


def test_is_same_device_prefers_serial_number() -> None:
    expected = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:")
    same = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="E:")
    different = ApricornDevice(iProduct="Secure Key 3.0", iSerial="XYZ999", driveLetter="D:")

    assert is_same_device(expected, same) is True
    assert is_same_device(expected, different) is False


def test_wait_for_device_removed_tracks_specific_device(monkeypatch: MonkeyPatch, capsys) -> None:
    expected = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:")
    polls = iter(
        [
            {"devices": [{"usb0": {"iManufacturer": "Apricorn", "iProduct": "Secure Key 3.0", "iSerial": "ABC123", "driveLetter": "D:"}}]},
            {"devices": [{"usb0": {"iManufacturer": "Apricorn", "iProduct": "Secure Key 3.0", "iSerial": "OTHER", "driveLetter": "E:"}}]},
        ]
    )
    monkeypatch.setattr("drive_qual.power_measurements_step.get_usb_payload", lambda: next(polls))

    _wait_for_device_removed(expected, "Remove Apricorn device..")

    captured = capsys.readouterr()
    assert "Remove Apricorn device.. Waiting on Secure Key 3.0, serial=ABC123, drive=D:" in captured.out


def test_select_apricorn_device_prompts_with_numbered_list(monkeypatch: MonkeyPatch, capsys) -> None:
    devices = [
        ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:"),
        ApricornDevice(iProduct="Secure Key 3.0", iSerial="XYZ999", driveLetter="E:"),
    ]
    monkeypatch.setattr("builtins.input", lambda _: "2")

    selected = select_apricorn_device(devices)

    captured = capsys.readouterr()
    assert "Multiple Apricorn devices detected:" in captured.out
    assert "1. Secure Key 3.0, serial=ABC123, drive=D:" in captured.out
    assert "2. Secure Key 3.0, serial=XYZ999, drive=E:" in captured.out
    assert selected == devices[1]


def test_device_identity_includes_key_fields() -> None:
    device = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:", physicalDriveNum=2)

    assert device_identity(device) == "Secure Key 3.0, serial=ABC123, drive=D:, disk=2"
