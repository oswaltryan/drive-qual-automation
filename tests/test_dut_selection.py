from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core.dut_selection import _select_usb_3x_device_for_binding, _wait_for_serial_as_usb_3x
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice


def test_unbound_dut_binding_fails_fast_when_usb_inventory_unavailable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("drive_qual.core.dut_selection.get_usb_payload", lambda: None)

    with pytest.raises(RuntimeError, match=r"usb --json"):
        _select_usb_3x_device_for_binding(
            dut_name="Padlock DT",
            prompt="Unlock Apricorn device..",
            poll_interval_seconds=0,
            max_polls=1,
        )


def test_bound_dut_wait_fails_fast_when_usb_inventory_unavailable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("drive_qual.core.dut_selection.get_usb_payload", lambda: None)

    with pytest.raises(RuntimeError, match=r"usb --json"):
        _wait_for_serial_as_usb_3x(
            serial_number="ABC123",
            dut_name="Padlock DT",
            prompt="Unlock Apricorn device..",
            poll_interval_seconds=0,
            max_polls=1,
            required_fields=(),
        )


def test_bound_dut_wait_polls_until_required_fields_are_available(monkeypatch: MonkeyPatch) -> None:
    devices = iter(
        [
            [ApricornDevice(iProduct="Padlock DT", iSerial="ABC123", bcdUSB=3.2)],
            [ApricornDevice(iProduct="Padlock DT", iSerial="ABC123", bcdUSB=3.2, driveLetter="G:")],
        ]
    )
    monkeypatch.setattr(
        "drive_qual.core.dut_selection._current_apricorn_devices", lambda require_payload=False: next(devices)
    )

    device = _wait_for_serial_as_usb_3x(
        serial_number="ABC123",
        dut_name="Padlock DT",
        prompt="Unlock Apricorn device..",
        poll_interval_seconds=0,
        max_polls=2,
        required_fields=("driveLetter",),
    )

    assert device.driveLetter == "G:"
