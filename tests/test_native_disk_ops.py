from __future__ import annotations

from drive_qual.core import native_disk_ops
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice


def test_select_candidate_prefers_serial_match() -> None:
    candidates = [
        native_disk_ops.NativeDiskCandidate("/dev/sdb", "disk one", serial="OTHER", model="Generic"),
        native_disk_ops.NativeDiskCandidate("/dev/sdc", "disk two", serial="ABC123", model="Padlock DT"),
    ]
    device = ApricornDevice(iProduct="Padlock DT", iSerial="ABC123")

    selected = native_disk_ops._select_candidate(candidates, device)

    assert selected.disk_path == "/dev/sdc"


def test_select_candidate_falls_back_to_product_match() -> None:
    candidates = [
        native_disk_ops.NativeDiskCandidate("/dev/sdb", "disk one", serial=None, model="Padlock DT"),
        native_disk_ops.NativeDiskCandidate("/dev/sdc", "disk two", serial=None, model="Something Else"),
    ]
    device = ApricornDevice(iProduct="Padlock DT")

    selected = native_disk_ops._select_candidate(candidates, device)

    assert selected.disk_path == "/dev/sdb"
