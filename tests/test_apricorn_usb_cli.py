from __future__ import annotations

from _pytest.monkeypatch import MonkeyPatch
from pytest import CaptureFixture

from drive_qual.integrations.apricorn.usb_cli import (
    ApricornDevice,
    device_identity,
    find_apricorn_device,
    is_same_device,
    list_apricorn_devices,
    select_apricorn_device,
)
from drive_qual.platforms.windows.power_measurements import (
    _confirm_selected_device,
    _wait_for_confirmed_device_present,
    _wait_for_device_present,
    _wait_for_device_removed,
)


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
                    "blockDevice": "/dev/sda",
                }
            },
        ]
    }

    devices = list_apricorn_devices(payload)

    assert len(devices) == 1
    assert devices[0].iProduct == "Secure Key 3.0"
    assert devices[0].driveLetter == "D:"
    assert devices[0].blockDevice == "/dev/sda"


def test_find_apricorn_device_returns_first_filtered_apricorn(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "devices": [
            {"usb0": {"iManufacturer": "Generic", "iProduct": "Thumb Drive", "driveLetter": "F:"}},
            {"usb1": {"iManufacturer": "Apricorn", "iProduct": "Secure Key 3.0", "driveLetter": "D:"}},
        ]
    }
    monkeypatch.setattr("drive_qual.integrations.apricorn.usb_cli.get_usb_payload", lambda: payload)
    monkeypatch.setattr("builtins.input", lambda _: "1")

    device = find_apricorn_device()

    assert device is not None
    assert device.iProduct == "Secure Key 3.0"


def test_is_same_device_prefers_serial_number() -> None:
    expected = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:", blockDevice="/dev/sda")
    same = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="E:", blockDevice="/dev/sdb")
    different = ApricornDevice(iProduct="Secure Key 3.0", iSerial="XYZ999", driveLetter="D:", blockDevice="/dev/sda")

    assert is_same_device(expected, same) is True
    assert is_same_device(expected, different) is False


def test_is_same_device_uses_block_device_when_present() -> None:
    expected = ApricornDevice(iProduct="Secure Key 3.0", blockDevice="/dev/sda")
    same = ApricornDevice(iProduct="Secure Key 3.0", blockDevice="/dev/sda")
    different = ApricornDevice(iProduct="Secure Key 3.0", blockDevice="/dev/sdb")

    assert is_same_device(expected, same) is True
    assert is_same_device(expected, different) is False


def test_wait_for_device_removed_tracks_specific_device(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    expected = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:")
    polls = iter(
        [
            {
                "devices": [
                    {
                        "usb0": {
                            "iManufacturer": "Apricorn",
                            "iProduct": "Secure Key 3.0",
                            "iSerial": "ABC123",
                            "driveLetter": "D:",
                        }
                    }
                ]
            },
            {
                "devices": [
                    {
                        "usb0": {
                            "iManufacturer": "Apricorn",
                            "iProduct": "Secure Key 3.0",
                            "iSerial": "OTHER",
                            "driveLetter": "E:",
                        }
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.get_usb_payload", lambda: next(polls))

    _wait_for_device_removed(expected, "Remove Apricorn device..")

    captured = capsys.readouterr()
    assert "Remove Apricorn device.. Waiting on Secure Key 3.0, serial=ABC123, drive=D:" in captured.out


def test_wait_for_device_present_requires_same_device_reconnect(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    expected = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:")
    polls = iter(
        [
            {
                "devices": [
                    {
                        "usb0": {
                            "iManufacturer": "Apricorn",
                            "iProduct": "Secure Key 3.0",
                            "iSerial": "OTHER",
                            "driveLetter": "E:",
                        }
                    }
                ]
            },
            {
                "devices": [
                    {
                        "usb0": {
                            "iManufacturer": "Apricorn",
                            "iProduct": "Secure Key 3.0",
                            "iSerial": "ABC123",
                            "driveLetter": "D:",
                        }
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.get_usb_payload", lambda: next(polls))

    device = _wait_for_device_present("Reconnect Apricorn device..", expected=expected)

    captured = capsys.readouterr()
    assert "Reconnect Apricorn device.. Waiting on Secure Key 3.0, serial=ABC123, drive=D:" in captured.out
    assert device.iSerial == "ABC123"


def test_select_apricorn_device_prompts_with_numbered_list(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
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


def test_confirm_selected_device_accepts_yes(monkeypatch: MonkeyPatch) -> None:
    device = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:")
    monkeypatch.setattr("builtins.input", lambda _: "y")

    assert _confirm_selected_device(device) is True


def test_wait_for_confirmed_device_present_retries_after_rejection(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    first = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:")
    second = ApricornDevice(iProduct="Secure Key 3.0", iSerial="XYZ999", driveLetter="E:")
    devices = iter([first, second])
    confirmations = iter([False, True])

    monkeypatch.setattr(
        "drive_qual.platforms.windows.power_measurements._wait_for_device_present", lambda prompt: next(devices)
    )
    monkeypatch.setattr(
        "drive_qual.platforms.windows.power_measurements._confirm_selected_device", lambda dut: next(confirmations)
    )

    selected = _wait_for_confirmed_device_present("Unlock Apricorn device..")

    captured = capsys.readouterr()
    assert "Select or connect the correct Apricorn device." in captured.out
    assert selected == second
