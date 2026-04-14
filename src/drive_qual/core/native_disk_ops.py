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

from drive_qual.integrations.apricorn.usb_cli import (
    ApricornDevice,
    device_identity,
    get_usb_payload,
    is_same_device,
    list_apricorn_devices,
)

LINUX_FILESYSTEM = "ext4"
LINUX_PARTITION_TABLE = "gpt"
LINUX_VOLUME_LABEL = "DUT"
MACOS_FILESYSTEM = "APFS"
MACOS_PARTITION_TABLE = "GPTFormat"
MACOS_VOLUME_LABEL = "DUT"
MACOS_NO_INDEX_MARKER = ".metadata_never_index"
POLL_ATTEMPTS = 20
POLL_DELAY_SECONDS = 0.5
LINUX_MKFS_RETRY_ATTEMPTS = 3
LINUX_MKFS_RETRY_DELAY_SECONDS = 0.5


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
    _linux_prepare_for_repartition(candidate.disk_path)
    _linux_make_filesystem(candidate.disk_path)
    _run_command(_with_linux_privilege(["udevadm", "settle"]), check=False)
    mount_point = _linux_mount_block_device(candidate.disk_path)
    _linux_take_mount_ownership(mount_point)
    return PreparedBenchmarkTarget(candidate.disk_path, candidate.disk_path, mount_point)


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
    _mark_macos_volume_no_index(mount_point)
    return PreparedBenchmarkTarget(candidate.disk_path, partition_path, mount_point)


def _safe_remove_linux_device(device: ApricornDevice) -> bool:
    candidate = _select_linux_candidate(device)
    _linux_unmount_disk(candidate.disk_path)
    result = _run_command(_with_linux_privilege(["udisksctl", "power-off", "-b", candidate.disk_path]), check=False)
    return result.returncode == 0


def _mark_macos_volume_no_index(mount_point: str) -> None:
    marker_path = f"{mount_point.rstrip('/')}/{MACOS_NO_INDEX_MARKER}"
    result = _run_command(["touch", marker_path], check=False, capture_output=True)
    if result.returncode != 0:
        print(f"Warning: could not create {MACOS_NO_INDEX_MARKER} on {mount_point}.")


def _safe_remove_macos_device(device: ApricornDevice) -> bool:
    candidate = _select_macos_candidate(device)
    eject_result = _run_command(
        ["diskutil", "eject", candidate.disk_path],
        check=False,
        capture_output=True,
    )
    if eject_result.returncode == 0 or _macos_disk_missing_from_result(eject_result):
        return True

    # Retry with a forced unmount in case Spotlight/Finder is still holding the volume.
    output = _normalized(f"{eject_result.stdout or ''}\n{eject_result.stderr or ''}")
    if "mds_stores" in output:
        print(f"Spotlight lock detected on {candidate.disk_path}; forcing unmount before removal.")
    _run_command(
        ["diskutil", "unmountDisk", "force", candidate.disk_path],
        check=False,
        capture_output=True,
    )

    retry_eject = _run_command(
        ["diskutil", "eject", candidate.disk_path],
        check=False,
        capture_output=True,
    )
    if retry_eject.returncode == 0 or _macos_disk_missing_from_result(retry_eject):
        return True

    presence_check = _run_command(
        ["diskutil", "info", candidate.disk_path],
        check=False,
        capture_output=True,
    )
    return presence_check.returncode != 0


def _macos_disk_missing_from_result(result: subprocess.CompletedProcess[str]) -> bool:
    output = _normalized(f"{result.stdout or ''}\n{result.stderr or ''}")
    return "failed to find disk" in output or "could not find disk" in output


def _with_linux_privilege(command: list[str]) -> list[str]:
    if _current_uid() == 0:
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


def _linux_make_filesystem(disk_path: str) -> None:
    command = _with_linux_privilege(["mkfs", f"-t{LINUX_FILESYSTEM}", "-F", "-L", LINUX_VOLUME_LABEL, disk_path])
    for attempt in range(1, LINUX_MKFS_RETRY_ATTEMPTS + 1):
        result = _run_command(command, check=False, capture_output=True)
        if result.returncode == 0:
            return

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = f"{stderr}\n{stdout}".strip()
        if attempt < LINUX_MKFS_RETRY_ATTEMPTS and _linux_mkfs_busy(detail):
            _linux_unmount_disk(disk_path)
            _run_command(_with_linux_privilege(["udevadm", "settle"]), check=False)
            time.sleep(LINUX_MKFS_RETRY_DELAY_SECONDS)
            continue

        rendered = " ".join(command)
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Command failed ({rendered}){suffix}")


def _linux_mkfs_busy(detail: str) -> bool:
    normalized = _normalized(detail)
    return (
        "apparently in use by the system" in normalized
        or "is mounted" in normalized
        or "device or resource busy" in normalized
    )


def _select_linux_candidate(device: ApricornDevice) -> NativeDiskCandidate:
    disk_path = _linux_disk_path_for_device(device)
    return _linux_candidate_for_path(disk_path)


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


def _linux_disk_path_for_device(device: ApricornDevice) -> str:
    if device.blockDevice:
        return device.blockDevice

    payload = get_usb_payload()
    devices = list_apricorn_devices(payload) if payload else []
    for detected in devices:
        if is_same_device(device, detected) and detected.blockDevice:
            return detected.blockDevice

    raise RuntimeError(f"Could not resolve Linux block device from usb --json for {device_identity(device)}.")


def _linux_candidate_for_path(disk_path: str) -> NativeDiskCandidate:
    result = _run_command(
        ["lsblk", "-J", "-o", "PATH,SERIAL,MODEL,TRAN,RM,HOTPLUG,TYPE", disk_path],
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    devices = payload.get("blockdevices", [])
    if not isinstance(devices, list) or not devices:
        raise RuntimeError(f"Could not inspect Linux disk device {disk_path}.")

    entry = devices[0]
    if not isinstance(entry, dict):
        raise RuntimeError(f"Invalid Linux disk entry for {disk_path}.")
    if entry.get("type") != "disk":
        raise RuntimeError(f"Resolved Linux block device is not a disk: {disk_path}.")

    serial = _string_or_none(entry.get("serial"))
    model = _string_or_none(entry.get("model"))
    description = " ".join(part for part in (disk_path, model, serial) if part)
    return NativeDiskCandidate(disk_path=disk_path, description=description, serial=serial, model=model)


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


def _linux_partition_paths(disk_path: str) -> list[str]:
    paths: list[str] = []
    for partition in _linux_partitions(disk_path):
        partition_path = _string_or_none(partition.get("path"))
        if partition_path:
            paths.append(partition_path)
    return paths


def _linux_unmount_block_device(block_path: str) -> None:
    result = _run_command(["udisksctl", "unmount", "-b", block_path], check=False)
    if result.returncode != 0:
        _run_command(_with_linux_privilege(["umount", block_path]), check=False)


def _linux_unmount_disk(disk_path: str) -> None:
    seen: set[str] = set()
    for block_path in [*_linux_partition_paths(disk_path), disk_path]:
        if block_path in seen:
            continue
        seen.add(block_path)
        _linux_unmount_block_device(block_path)


def _linux_deactivate_partition_usage(disk_path: str) -> None:
    for partition_path in _linux_partition_paths(disk_path):
        _run_command(_with_linux_privilege(["swapoff", partition_path]), check=False)
        _run_command(_with_linux_privilege(["wipefs", "--all", "--force", partition_path]), check=False)


def _linux_prepare_for_repartition(disk_path: str) -> None:
    _linux_unmount_disk(disk_path)
    _linux_deactivate_partition_usage(disk_path)
    _run_command(_with_linux_privilege(["wipefs", "--all", "--force", disk_path]), check=False)
    _run_command(_with_linux_privilege(["udevadm", "settle"]), check=False)


def _linux_mount_block_device(block_path: str) -> str:
    _run_command(["udisksctl", "mount", "-b", block_path])
    for _ in range(POLL_ATTEMPTS):
        mount_point = _linux_mount_point(block_path)
        if mount_point:
            return mount_point
        time.sleep(POLL_DELAY_SECONDS)
    raise RuntimeError(f"Timed out waiting for mount point on {block_path}.")


def _linux_mount_point(block_path: str) -> str | None:
    block = _linux_block_device_info(block_path)
    if block is None:
        return None
    mount_points = block.get("mountpoints")
    if isinstance(mount_points, list):
        for value in mount_points:
            if isinstance(value, str) and value:
                return value
        return None
    if isinstance(mount_points, str):
        mount_point = mount_points.strip()
        return mount_point or None
    return None


def _linux_take_mount_ownership(mount_point: str) -> None:
    uid = _current_uid()
    gid = _current_gid()
    _run_command(_with_linux_privilege(["chown", f"{uid}:{gid}", mount_point]))


def _current_uid() -> int:
    getter = getattr(os, "getuid", None)
    if callable(getter):
        return int(getter())
    return 0


def _current_gid() -> int:
    getter = getattr(os, "getgid", None)
    if callable(getter):
        return int(getter())
    return 0


def _linux_block_device_info(block_path: str) -> dict[str, Any] | None:
    result = _run_command(
        ["lsblk", "-J", "-o", "PATH,TYPE,MOUNTPOINTS", block_path],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    devices = payload.get("blockdevices", [])
    if not isinstance(devices, list):
        return None
    for entry in devices:
        if not isinstance(entry, dict):
            continue
        if _string_or_none(entry.get("path")) == block_path:
            return entry
    return None


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
        partition_path = _macos_data_partition_path(entry)
        if partition_path is not None:
            return partition_path
        time.sleep(POLL_DELAY_SECONDS)
    raise RuntimeError(f"Timed out waiting for macOS partition on {disk_path}.")


def _macos_wait_for_mount(partition_path: str) -> str:
    mount_attempted_for: set[str] = set()
    last_target = partition_path
    for _ in range(POLL_ATTEMPTS):
        mount_target = _macos_mountable_device_path(partition_path)
        last_target = mount_target
        try:
            info = _macos_disk_info(mount_target)
        except RuntimeError:
            time.sleep(POLL_DELAY_SECONDS)
            continue
        mount_point = _string_or_none(info.get("MountPoint"))
        if mount_point:
            return mount_point
        if mount_target not in mount_attempted_for:
            _run_command(["diskutil", "mount", mount_target], check=False, capture_output=True)
            mount_attempted_for.add(mount_target)
        time.sleep(POLL_DELAY_SECONDS)
    raise RuntimeError(
        f"Timed out waiting for macOS mount point on {last_target} (source partition {partition_path})."
    )


def _macos_mountable_device_path(partition_path: str) -> str:
    apfs_volume_path = _macos_apfs_volume_path_for_physical_store(partition_path)
    if apfs_volume_path:
        return apfs_volume_path
    return partition_path


def _macos_apfs_volume_path_for_physical_store(partition_path: str) -> str | None:
    result = _run_command(
        ["diskutil", "apfs", "list", "-plist", partition_path],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None

    try:
        payload = plistlib.loads(result.stdout.encode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    partition_identifier = _device_identifier(partition_path)
    if not partition_identifier:
        return None

    containers = payload.get("Containers", [])
    if not isinstance(containers, list):
        return None

    for container in containers:
        if not isinstance(container, dict):
            continue
        if not _macos_container_has_physical_store(container, partition_identifier):
            continue
        volume_path = _macos_preferred_apfs_volume_path(container)
        if volume_path:
            return volume_path

    return None


def _macos_container_has_physical_store(container: dict[str, Any], partition_identifier: str) -> bool:
    stores = container.get("PhysicalStores", [])
    if not isinstance(stores, list):
        return False
    for store in stores:
        if not isinstance(store, dict):
            continue
        identifier = _normalized(_string_or_none(store.get("DeviceIdentifier")))
        if identifier == _normalized(partition_identifier):
            return True
    return False


def _macos_preferred_apfs_volume_path(container: dict[str, Any]) -> str | None:
    volumes = container.get("Volumes", [])
    if not isinstance(volumes, list):
        return None

    preferred: str | None = None
    fallback: str | None = None
    for volume in volumes:
        if not isinstance(volume, dict):
            continue

        identifier = _string_or_none(volume.get("DeviceIdentifier"))
        if not identifier:
            continue
        volume_path = f"/dev/{identifier}"
        if fallback is None:
            fallback = volume_path

        name = _normalized(_string_or_none(volume.get("Name")) or _string_or_none(volume.get("VolumeName")))
        if name == _normalized(MACOS_VOLUME_LABEL):
            return volume_path

        role = _normalized(_string_or_none(volume.get("Role")))
        if not role and preferred is None:
            preferred = volume_path

    return preferred or fallback


def _device_identifier(device_path: str) -> str | None:
    normalized = _string_or_none(device_path)
    if not normalized:
        return None
    if normalized.startswith("/dev/"):
        return normalized[5:]
    return normalized


def _macos_data_partition_path(entry: dict[str, Any]) -> str | None:
    partitions = entry.get("Partitions", [])
    if not isinstance(partitions, list) or not partitions:
        return None

    preferred: str | None = None
    fallback: str | None = None
    for partition in partitions:
        if not isinstance(partition, dict):
            continue
        identifier = _string_or_none(partition.get("DeviceIdentifier"))
        if not identifier:
            continue
        partition_path = f"/dev/{identifier}"
        if fallback is None:
            fallback = partition_path

        volume_name = _normalized(_string_or_none(partition.get("VolumeName")))
        if volume_name == _normalized(MACOS_VOLUME_LABEL):
            return partition_path

        content = _normalized(_string_or_none(partition.get("Content")))
        if content != "efi" and preferred is None:
            preferred = partition_path

    return preferred or fallback


def _string_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
