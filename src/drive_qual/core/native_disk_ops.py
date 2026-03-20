from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from drive_qual.integrations.apricorn.usb_cli import ApricornDevice, device_identity

LINUX_FILESYSTEM = "ext4"
LINUX_PARTITION_TABLE = "gpt"
LINUX_VOLUME_LABEL = "DUT"
MACOS_FILESYSTEM = "ExFAT"
MACOS_PARTITION_TABLE = "GPTFormat"
MACOS_VOLUME_LABEL = "DUT"
POLL_ATTEMPTS = 20
POLL_DELAY_SECONDS = 0.5


@dataclass(frozen=True)
class NativeDiskCandidate:
    disk_path: str
    description: str
    serial: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class PreparedBenchmarkTarget:
    disk_path: str
    partition_path: str
    mount_point: str


def prepare_device_for_benchmark(device: ApricornDevice) -> PreparedBenchmarkTarget:
    if sys.platform.startswith("linux"):
        return _prepare_linux_device(device)
    if sys.platform == "darwin":
        return _prepare_macos_device(device)
    raise RuntimeError(f"Unsupported platform for native disk operations: {sys.platform}")


def safe_remove_device(device: ApricornDevice) -> bool:
    if sys.platform.startswith("linux"):
        return _safe_remove_linux_device(device)
    if sys.platform == "darwin":
        return _safe_remove_macos_device(device)
    raise RuntimeError(f"Unsupported platform for native disk operations: {sys.platform}")


def _prepare_linux_device(device: ApricornDevice) -> PreparedBenchmarkTarget:
    candidate = _select_linux_candidate(device)
    _linux_unmount_disk(candidate.disk_path)
    _run_command(_with_linux_privilege(["parted", "-s", candidate.disk_path, "mklabel", LINUX_PARTITION_TABLE]))
    _run_command(
        _with_linux_privilege(
            [
                "parted",
                "-s",
                candidate.disk_path,
                "mkpart",
                "primary",
                LINUX_FILESYSTEM,
                "1MiB",
                "100%",
            ]
        )
    )
    _run_command(_with_linux_privilege(["udevadm", "settle"]))
    partition_path = _linux_wait_for_partition(candidate.disk_path)
    _run_command(
        _with_linux_privilege(["mkfs", f"-t{LINUX_FILESYSTEM}", "-F", "-L", LINUX_VOLUME_LABEL, partition_path])
    )
    mount_point = _linux_mount_partition(partition_path)
    return PreparedBenchmarkTarget(candidate.disk_path, partition_path, mount_point)


def _prepare_macos_device(device: ApricornDevice) -> PreparedBenchmarkTarget:
    candidate = _select_macos_candidate(device)
    _run_command(["diskutil", "unmountDisk", "force", candidate.disk_path])
    _run_command(
        [
            "diskutil",
            "eraseDisk",
            MACOS_FILESYSTEM,
            MACOS_VOLUME_LABEL,
            MACOS_PARTITION_TABLE,
            candidate.disk_path,
        ]
    )
    partition_path = _macos_wait_for_partition(candidate.disk_path)
    mount_point = _macos_wait_for_mount(partition_path)
    return PreparedBenchmarkTarget(candidate.disk_path, partition_path, mount_point)


def _safe_remove_linux_device(device: ApricornDevice) -> bool:
    candidate = _select_linux_candidate(device)
    _linux_unmount_disk(candidate.disk_path)
    result = _run_command(["udisksctl", "power-off", "-b", candidate.disk_path], check=False)
    return result.returncode == 0


def _safe_remove_macos_device(device: ApricornDevice) -> bool:
    candidate = _select_macos_candidate(device)
    result = _run_command(["diskutil", "eject", candidate.disk_path], check=False)
    return result.returncode == 0


def _with_linux_privilege(command: list[str]) -> list[str]:
    if os.geteuid() == 0:
        return command
    sudo = shutil.which("sudo")
    if sudo is None:
        raise RuntimeError("Linux disk operations require root privileges or sudo.")
    return [sudo, *command]


def _run_command(
    command: list[str], *, check: bool = True, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, check=False, capture_output=capture_output, text=True)
    if check and result.returncode != 0:
        rendered = " ".join(command)
        stderr = (result.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(f"Command failed ({rendered}){detail}")
    return result


def _select_linux_candidate(device: ApricornDevice) -> NativeDiskCandidate:
    candidates = _linux_candidates()
    return _select_candidate(candidates, device)


def _select_macos_candidate(device: ApricornDevice) -> NativeDiskCandidate:
    candidates = _macos_candidates()
    return _select_candidate(candidates, device)


def _select_candidate(candidates: list[NativeDiskCandidate], device: ApricornDevice) -> NativeDiskCandidate:
    if not candidates:
        raise RuntimeError(f"No native storage devices found for {device_identity(device)}.")

    serial_match = _find_candidate_by_serial(candidates, device.iSerial)
    if serial_match is not None:
        return serial_match

    product_match = _find_candidate_by_product(candidates, device.iProduct)
    if product_match is not None:
        return product_match

    if len(candidates) == 1:
        return candidates[0]

    return _prompt_candidate_selection(candidates, device)


def _find_candidate_by_serial(candidates: list[NativeDiskCandidate], serial: str | None) -> NativeDiskCandidate | None:
    normalized_serial = _normalized(serial)
    if not normalized_serial:
        return None
    for candidate in candidates:
        if _normalized(candidate.serial) == normalized_serial:
            return candidate
    return None


def _find_candidate_by_product(
    candidates: list[NativeDiskCandidate], product: str | None
) -> NativeDiskCandidate | None:
    normalized_product = _normalized(product)
    if not normalized_product:
        return None
    for candidate in candidates:
        haystack = " ".join(part for part in (candidate.model, candidate.description) if part)
        if normalized_product in _normalized(haystack):
            return candidate
    return None


def _prompt_candidate_selection(candidates: list[NativeDiskCandidate], device: ApricornDevice) -> NativeDiskCandidate:
    print(f"Multiple native disk candidates detected for {device_identity(device)}:")
    for index, candidate in enumerate(candidates, start=1):
        print(f"{index}. {candidate.description}")
    while True:
        response = input("Select native disk number: ").strip()
        try:
            selection = int(response)
        except ValueError:
            continue
        if 1 <= selection <= len(candidates):
            return candidates[selection - 1]


def _normalized(value: str | None) -> str:
    return (value or "").strip().casefold()


def _linux_candidates() -> list[NativeDiskCandidate]:
    result = _run_command(
        ["lsblk", "-J", "-o", "PATH,SERIAL,MODEL,TRAN,RM,HOTPLUG,TYPE"],
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    candidates: list[NativeDiskCandidate] = []
    for entry in payload.get("blockdevices", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "disk":
            continue
        if not _linux_is_external_disk(entry):
            continue
        disk_path = entry.get("path")
        if not isinstance(disk_path, str) or not disk_path:
            continue
        serial = _string_or_none(entry.get("serial"))
        model = _string_or_none(entry.get("model"))
        description = " ".join(part for part in (disk_path, model, serial) if part)
        candidates.append(NativeDiskCandidate(disk_path=disk_path, description=description, serial=serial, model=model))
    return candidates


def _linux_is_external_disk(entry: dict[str, Any]) -> bool:
    transport = _normalized(_string_or_none(entry.get("tran")))
    if transport == "usb":
        return True
    return bool(entry.get("rm")) or bool(entry.get("hotplug"))


def _linux_device_tree(disk_path: str) -> dict[str, Any]:
    result = _run_command(["lsblk", "-J", "-o", "PATH,TYPE,MOUNTPOINTS", disk_path], capture_output=True)
    payload = json.loads(result.stdout)
    devices = payload.get("blockdevices", [])
    if not isinstance(devices, list) or not devices:
        raise RuntimeError(f"Could not inspect Linux disk device {disk_path}.")
    tree = devices[0]
    if not isinstance(tree, dict):
        raise RuntimeError(f"Invalid Linux device tree for {disk_path}.")
    return tree


def _linux_partitions(disk_path: str) -> list[dict[str, Any]]:
    tree = _linux_device_tree(disk_path)
    children = tree.get("children", [])
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict) and child.get("type") == "part"]


def _linux_unmount_disk(disk_path: str) -> None:
    for partition in _linux_partitions(disk_path):
        partition_path = _string_or_none(partition.get("path"))
        if not partition_path:
            continue
        mount_points = partition.get("mountpoints") or []
        if not isinstance(mount_points, list) or not any(isinstance(value, str) and value for value in mount_points):
            continue
        _run_command(["udisksctl", "unmount", "-b", partition_path], check=False)


def _linux_wait_for_partition(disk_path: str) -> str:
    for _ in range(POLL_ATTEMPTS):
        partitions = _linux_partitions(disk_path)
        if partitions:
            partition_path = _string_or_none(partitions[0].get("path"))
            if partition_path:
                return partition_path
        time.sleep(POLL_DELAY_SECONDS)
    raise RuntimeError(f"Timed out waiting for Linux partition on {disk_path}.")


def _linux_mount_partition(partition_path: str) -> str:
    _run_command(["udisksctl", "mount", "-b", partition_path])
    for _ in range(POLL_ATTEMPTS):
        for partition in _linux_partitions(_linux_parent_disk(partition_path)):
            if _string_or_none(partition.get("path")) != partition_path:
                continue
            mount_points = partition.get("mountpoints") or []
            if isinstance(mount_points, list):
                for value in mount_points:
                    if isinstance(value, str) and value:
                        return value
        time.sleep(POLL_DELAY_SECONDS)
    raise RuntimeError(f"Timed out waiting for mount point on {partition_path}.")


def _linux_parent_disk(partition_path: str) -> str:
    if partition_path.startswith("/dev/nvme") or partition_path.startswith("/dev/mmcblk"):
        return partition_path.rsplit("p", 1)[0]
    return partition_path[:-1]


def _macos_candidates() -> list[NativeDiskCandidate]:
    result = _run_command(["diskutil", "list", "-plist", "external", "physical"], capture_output=True)
    payload = plistlib.loads(result.stdout.encode("utf-8"))
    entries = payload.get("AllDisksAndPartitions", [])
    candidates: list[NativeDiskCandidate] = []
    if not isinstance(entries, list):
        return candidates
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        device_identifier = _string_or_none(entry.get("DeviceIdentifier"))
        if not device_identifier:
            continue
        disk_path = f"/dev/{device_identifier}"
        info = _macos_disk_info(disk_path)
        model = _string_or_none(info.get("MediaName")) or _string_or_none(info.get("IORegistryEntryName"))
        serial = _string_or_none(info.get("DeviceIdentifier"))
        description = " ".join(part for part in (disk_path, model) if part)
        candidates.append(NativeDiskCandidate(disk_path=disk_path, description=description, serial=serial, model=model))
    return candidates


def _macos_disk_info(device_path: str) -> dict[str, Any]:
    result = _run_command(["diskutil", "info", "-plist", device_path], capture_output=True)
    payload = plistlib.loads(result.stdout.encode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid diskutil info payload for {device_path}.")
    return payload


def _macos_disk_entry(device_path: str) -> dict[str, Any]:
    result = _run_command(["diskutil", "list", "-plist", device_path], capture_output=True)
    payload = plistlib.loads(result.stdout.encode("utf-8"))
    entries = payload.get("AllDisksAndPartitions", [])
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"Could not inspect macOS disk {device_path}.")
    entry = entries[0]
    if not isinstance(entry, dict):
        raise RuntimeError(f"Invalid macOS disk entry for {device_path}.")
    return entry


def _macos_wait_for_partition(disk_path: str) -> str:
    for _ in range(POLL_ATTEMPTS):
        entry = _macos_disk_entry(disk_path)
        partitions = entry.get("Partitions", [])
        if isinstance(partitions, list) and partitions:
            first_partition = partitions[0]
            if isinstance(first_partition, dict):
                identifier = _string_or_none(first_partition.get("DeviceIdentifier"))
                if identifier:
                    return f"/dev/{identifier}"
        time.sleep(POLL_DELAY_SECONDS)
    raise RuntimeError(f"Timed out waiting for macOS partition on {disk_path}.")


def _macos_wait_for_mount(partition_path: str) -> str:
    for _ in range(POLL_ATTEMPTS):
        info = _macos_disk_info(partition_path)
        mount_point = _string_or_none(info.get("MountPoint"))
        if mount_point:
            return mount_point
        time.sleep(POLL_DELAY_SECONDS)
    raise RuntimeError(f"Timed out waiting for macOS mount point on {partition_path}.")


def _string_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
