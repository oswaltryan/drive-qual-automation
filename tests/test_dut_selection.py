from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core.dut_selection import _select_usb_3x_device_for_binding, _wait_for_serial_as_usb_3x


def test_unbound_dut_binding_fails_fast_when_usb_inventory_unavailable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("drive_qual.core.dut_selection.get_usb_payload", lambda: None)

    with pytest.raises(RuntimeError, match=r"usb --json"):
        _select_usb_3x_device_for_binding(
            dut_name="Padlock DT FIPS",
            prompt="Unlock Apricorn device..",
            poll_interval_seconds=0,
            max_polls=1,
        )


def test_bound_dut_wait_fails_fast_when_usb_inventory_unavailable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("drive_qual.core.dut_selection.get_usb_payload", lambda: None)

    with pytest.raises(RuntimeError, match=r"usb --json"):
        _wait_for_serial_as_usb_3x(
            serial_number="ABC123",
            dut_name="Padlock DT FIPS",
            prompt="Unlock Apricorn device..",
            poll_interval_seconds=0,
            max_polls=1,
            required_fields=(),
        )
