from __future__ import annotations

from typing import Any

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


def test_select_linux_candidate_uses_device_block_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123", blockDevice="/dev/sda")

    monkeypatch.setattr(
        native_disk_ops,
        "_run_command",
        lambda *args, **kwargs: type(
            "Result",
            (),
            {"stdout": '{"blockdevices":[{"path":"/dev/sda","serial":"ABC123","model":"Padlock 3.0","type":"disk"}]}'},
        )(),
    )

    selected = native_disk_ops._select_linux_candidate(device)

    assert selected.disk_path == "/dev/sda"


def test_linux_disk_path_for_device_refreshes_from_usb_payload(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123")
    payload = {
        "devices": [
            {
                "1": {
                    "iManufacturer": "Apricorn",
                    "iProduct": "Padlock 3.0",
                    "iSerial": "ABC123",
                    "blockDevice": "/dev/sda",
                }
            }
        ]
    }

    monkeypatch.setattr(native_disk_ops, "get_usb_payload", lambda: payload)

    assert native_disk_ops._linux_disk_path_for_device(device) == "/dev/sda"


def test_linux_partition_path_uses_first_partition_for_sd_devices() -> None:
    assert native_disk_ops._linux_partition_path("/dev/sda") == "/dev/sda1"


def test_linux_partition_path_uses_p1_for_nvme_devices() -> None:
    assert native_disk_ops._linux_partition_path("/dev/nvme0n1") == "/dev/nvme0n1p1"


def test_prepare_linux_device_takes_mount_ownership(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123", blockDevice="/dev/sda")
    calls: list[str] = []

    monkeypatch.setattr(
        native_disk_ops,
        "_select_linux_candidate",
        lambda device: native_disk_ops.NativeDiskCandidate("/dev/sda", "disk"),
    )
    monkeypatch.setattr(native_disk_ops, "_linux_unmount_disk", lambda disk_path: None)
    monkeypatch.setattr(native_disk_ops, "_linux_wait_for_partition", lambda disk_path: "/dev/sda1")
    monkeypatch.setattr(native_disk_ops, "_linux_mount_partition", lambda partition_path: "/media/test/DUT")
    monkeypatch.setattr(native_disk_ops, "_with_linux_privilege", lambda command: command)

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        calls.append(" ".join(command))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    prepared = native_disk_ops._prepare_linux_device(device)

    assert prepared.mount_point == "/media/test/DUT"
    assert any(command.startswith("chown ") and "/media/test/DUT" in command for command in calls)


def test_safe_remove_linux_device_uses_linux_privilege(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123", blockDevice="/dev/sda")
    commands: list[list[str]] = []

    monkeypatch.setattr(
        native_disk_ops,
        "_select_linux_candidate",
        lambda device: native_disk_ops.NativeDiskCandidate("/dev/sda", "disk"),
    )
    monkeypatch.setattr(native_disk_ops, "_linux_unmount_disk", lambda disk_path: None)
    monkeypatch.setattr(native_disk_ops, "_with_linux_privilege", lambda command: ["sudo", *command])

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        commands.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    assert native_disk_ops._safe_remove_linux_device(device) is True
    assert commands == [["sudo", "udisksctl", "power-off", "-b", "/dev/sda"]]
