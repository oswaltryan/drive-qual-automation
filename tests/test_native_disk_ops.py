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


def test_prepare_linux_device_takes_mount_ownership(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123", blockDevice="/dev/sda")
    calls: list[list[str]] = []

    monkeypatch.setattr(
        native_disk_ops,
        "_select_linux_candidate",
        lambda device: native_disk_ops.NativeDiskCandidate("/dev/sda", "disk"),
    )
    monkeypatch.setattr(native_disk_ops, "_linux_prepare_for_repartition", lambda disk_path: None)
    monkeypatch.setattr(native_disk_ops, "_linux_mount_block_device", lambda block_path: "/media/test/DUT")
    monkeypatch.setattr(native_disk_ops, "_with_linux_privilege", lambda command: command)

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    prepared = native_disk_ops._prepare_linux_device(device)

    assert prepared.partition_path == "/dev/sda"
    assert prepared.mount_point == "/media/test/DUT"
    assert ["mkfs", "-text4", "-F", "-L", "DUT", "/dev/sda"] in calls
    assert not any(command and command[0] == "parted" for command in calls)
    assert any(command and command[0] == "chown" and "/media/test/DUT" in command for command in calls)


def test_prepare_linux_device_retries_when_mkfs_reports_busy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123", blockDevice="/dev/sda")
    commands: list[list[str]] = []
    unmount_calls: list[str] = []
    mkfs_attempts = 0

    monkeypatch.setattr(
        native_disk_ops,
        "_select_linux_candidate",
        lambda device: native_disk_ops.NativeDiskCandidate("/dev/sda", "disk"),
    )
    monkeypatch.setattr(native_disk_ops, "_linux_prepare_for_repartition", lambda disk_path: None)
    monkeypatch.setattr(native_disk_ops, "_linux_mount_block_device", lambda block_path: "/media/test/DUT")
    monkeypatch.setattr(native_disk_ops, "_with_linux_privilege", lambda command: command)
    monkeypatch.setattr(native_disk_ops, "_linux_unmount_disk", lambda disk_path: unmount_calls.append(disk_path))
    monkeypatch.setattr("drive_qual.core.native_disk_ops.time.sleep", lambda _: None)

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        nonlocal mkfs_attempts
        commands.append(command)
        if command and command[0] == "mkfs":
            mkfs_attempts += 1
            if mkfs_attempts == 1:
                return type(
                    "Result",
                    (),
                    {"returncode": 1, "stdout": "", "stderr": "/dev/sda is apparently in use by the system"},
                )()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    expected_attempts = 2
    expected_settle_calls = 2

    native_disk_ops._prepare_linux_device(device)

    assert mkfs_attempts == expected_attempts
    assert unmount_calls == ["/dev/sda"]
    assert commands.count(["udevadm", "settle"]) == expected_settle_calls


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


def test_linux_unmount_disk_unmounts_partitions_then_disk(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    monkeypatch.setattr(native_disk_ops, "_linux_partition_paths", lambda disk_path: ["/dev/sda1", "/dev/sda2"])
    monkeypatch.setattr(native_disk_ops, "_linux_unmount_block_device", lambda path: calls.append(path))

    native_disk_ops._linux_unmount_disk("/dev/sda")

    assert calls == ["/dev/sda1", "/dev/sda2", "/dev/sda"]


def test_linux_unmount_block_device_falls_back_to_privileged_umount(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commands: list[list[str]] = []

    monkeypatch.setattr(native_disk_ops, "_with_linux_privilege", lambda command: ["sudo", *command])

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        commands.append(command)
        return_code = 1 if command == ["udisksctl", "unmount", "-b", "/dev/sda1"] else 0
        return type("Result", (), {"returncode": return_code, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    native_disk_ops._linux_unmount_block_device("/dev/sda1")

    assert commands == [
        ["udisksctl", "unmount", "-b", "/dev/sda1"],
        ["sudo", "umount", "/dev/sda1"],
    ]


def test_linux_prepare_for_repartition_clears_partition_signatures(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commands: list[list[str]] = []

    monkeypatch.setattr(native_disk_ops, "_linux_unmount_disk", lambda disk_path: None)
    monkeypatch.setattr(native_disk_ops, "_linux_partition_paths", lambda disk_path: ["/dev/sda1", "/dev/sda2"])
    monkeypatch.setattr(native_disk_ops, "_with_linux_privilege", lambda command: ["sudo", *command])

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        commands.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    native_disk_ops._linux_prepare_for_repartition("/dev/sda")

    assert commands == [
        ["sudo", "swapoff", "/dev/sda1"],
        ["sudo", "wipefs", "--all", "--force", "/dev/sda1"],
        ["sudo", "swapoff", "/dev/sda2"],
        ["sudo", "wipefs", "--all", "--force", "/dev/sda2"],
        ["sudo", "wipefs", "--all", "--force", "/dev/sda"],
        ["sudo", "udevadm", "settle"],
    ]


def test_prepare_macos_device_creates_no_index_marker(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123")
    marker_calls: list[str] = []

    monkeypatch.setattr(
        native_disk_ops,
        "_select_macos_candidate",
        lambda device: native_disk_ops.NativeDiskCandidate("/dev/disk4", "disk"),
    )
    monkeypatch.setattr(native_disk_ops, "_macos_wait_for_partition", lambda disk_path: "/dev/disk4s2")
    monkeypatch.setattr(native_disk_ops, "_macos_wait_for_mount", lambda partition_path: "/Volumes/DUT")
    monkeypatch.setattr(
        native_disk_ops, "_run_command", lambda command, **kwargs: type("Result", (), {"returncode": 0})()
    )
    monkeypatch.setattr(
        native_disk_ops,
        "_mark_macos_volume_no_index",
        lambda mount_point: marker_calls.append(mount_point),
    )

    prepared = native_disk_ops._prepare_macos_device(device)

    assert prepared == native_disk_ops.PreparedBenchmarkTarget("/dev/disk4", "/dev/disk4s2", "/Volumes/DUT")
    assert marker_calls == ["/Volumes/DUT"]


def test_mark_macos_volume_no_index_runs_touch_command(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        seen.append((command, kwargs))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    native_disk_ops._mark_macos_volume_no_index("/Volumes/DUT")

    assert seen == [
        (
            ["touch", "/Volumes/DUT/.metadata_never_index"],
            {"check": False, "capture_output": True},
        )
    ]


def test_macos_data_partition_path_prefers_dut_named_volume() -> None:
    entry = {
        "Partitions": [
            {"DeviceIdentifier": "disk4s1", "Content": "EFI"},
            {"DeviceIdentifier": "disk4s2", "Content": "Microsoft Basic Data", "VolumeName": "DUT"},
        ]
    }

    assert native_disk_ops._macos_data_partition_path(entry) == "/dev/disk4s2"


def test_macos_data_partition_path_falls_back_to_first_non_efi() -> None:
    entry = {
        "Partitions": [
            {"DeviceIdentifier": "disk4s1", "Content": "EFI"},
            {"DeviceIdentifier": "disk4s2", "Content": "Microsoft Basic Data"},
        ]
    }

    assert native_disk_ops._macos_data_partition_path(entry) == "/dev/disk4s2"


def test_macos_wait_for_partition_skips_efi_partition(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        native_disk_ops,
        "_macos_disk_entry",
        lambda disk_path: {
            "Partitions": [
                {"DeviceIdentifier": "disk4s1", "Content": "EFI"},
                {"DeviceIdentifier": "disk4s2", "Content": "Microsoft Basic Data", "VolumeName": "DUT"},
            ]
        },
    )
    monkeypatch.setattr("drive_qual.core.native_disk_ops.time.sleep", lambda _: None)

    assert native_disk_ops._macos_wait_for_partition("/dev/disk4") == "/dev/disk4s2"


def test_macos_wait_for_mount_attempts_mount_when_not_mounted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    infos = iter(
        [
            {"MountPoint": None},
            {"MountPoint": "/Volumes/DUT"},
        ]
    )
    commands: list[list[str]] = []

    monkeypatch.setattr(native_disk_ops, "_macos_disk_info", lambda partition_path: next(infos))
    monkeypatch.setattr("drive_qual.core.native_disk_ops.time.sleep", lambda _: None)

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        commands.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    mount_point = native_disk_ops._macos_wait_for_mount("/dev/disk4s2")

    assert mount_point == "/Volumes/DUT"
    assert commands == [["diskutil", "mount", "/dev/disk4s2"]]


def test_safe_remove_macos_device_uses_force_unmount_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123")
    commands: list[list[str]] = []
    kwargs_seen: list[dict[str, Any]] = []

    monkeypatch.setattr(
        native_disk_ops,
        "_select_macos_candidate",
        lambda device: native_disk_ops.NativeDiskCandidate("/dev/disk4", "disk"),
    )

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        commands.append(command)
        kwargs_seen.append(kwargs)
        if command[:2] == ["diskutil", "eject"]:
            returncode = 0 if len([c for c in commands if c[:2] == ["diskutil", "eject"]]) > 1 else 1
            return type("Result", (), {"returncode": returncode, "stdout": "mds_stores", "stderr": "mds_stores"})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    assert native_disk_ops._safe_remove_macos_device(device) is True
    assert commands == [
        ["diskutil", "eject", "/dev/disk4"],
        ["diskutil", "unmountDisk", "force", "/dev/disk4"],
        ["diskutil", "eject", "/dev/disk4"],
    ]
    assert kwargs_seen == [
        {"check": False, "capture_output": True},
        {"check": False, "capture_output": True},
        {"check": False, "capture_output": True},
    ]


def test_safe_remove_macos_device_returns_true_when_disk_already_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    device = ApricornDevice(iProduct="Padlock 3.0", iSerial="ABC123")
    commands: list[list[str]] = []

    monkeypatch.setattr(
        native_disk_ops,
        "_select_macos_candidate",
        lambda device: native_disk_ops.NativeDiskCandidate("/dev/disk4", "disk"),
    )

    def fake_run_command(command: list[str], **kwargs: Any) -> object:
        commands.append(command)
        return type(
            "Result",
            (),
            {"returncode": 1, "stdout": "", "stderr": "Failed to find disk /dev/disk4"},
        )()

    monkeypatch.setattr(native_disk_ops, "_run_command", fake_run_command)

    assert native_disk_ops._safe_remove_macos_device(device) is True
    assert commands == [["diskutil", "eject", "/dev/disk4"]]
