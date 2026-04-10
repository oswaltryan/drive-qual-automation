"""Disk formatting helpers loaded dynamically by Windows power measurements."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from contextlib import suppress
from logging import Logger
from typing import Protocol

WINDOWS_FILESYSTEMS = ("NTFS", "FAT32", "EXFAT")
WINDOWS_PARTITION_SCHEMES = ("GPT", "MBR")
MACOS_FILESYSTEMS = ("APFS", "HFS+", "FAT32", "EXFAT")
MACOS_PARTITION_SCHEMES = ("GUID", "MBR", "APFS_CONTAINER")
LINUX_FILESYSTEMS = ("EXT4", "NTFS", "VFAT", "EXFAT")
LINUX_PARTITION_SCHEMES = ("GPT", "MBR")

FORMAT_DEFAULTS: dict[str, dict[str, str]] = {
    "windows": {"filesystem": "EXFAT", "partition_scheme": "GPT"},
    "macos": {"filesystem": "EXFAT", "partition_scheme": "GUID"},
    "linux": {"filesystem": "EXT4", "partition_scheme": "GPT"},
}

FILESYSTEM_CHOICES: dict[str, tuple[str, ...]] = {
    "windows": WINDOWS_FILESYSTEMS,
    "macos": MACOS_FILESYSTEMS,
    "linux": LINUX_FILESYSTEMS,
}

PARTITION_SCHEME_CHOICES: dict[str, tuple[str, ...]] = {
    "windows": WINDOWS_PARTITION_SCHEMES,
    "macos": MACOS_PARTITION_SCHEMES,
    "linux": LINUX_PARTITION_SCHEMES,
}


class _DutLike(Protocol):
    read_only_enabled: bool


class _DiskOpsAdapterLike(Protocol):
    dut: _DutLike
    logger: Logger

    def _normalize_windows_drive_letter(self, drive_letter: str | None) -> str | None: ...


def _detect_os_key() -> str:
    if sys.platform.startswith("win32"):
        return "windows"
    if sys.platform.startswith("darwin"):
        return "macos"
    return "linux"


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_choice(
    logger: Logger,
    *,
    os_key: str,
    requested: str | None,
    env_value: str | None,
    allowed: tuple[str, ...],
    default_value: str,
) -> str:
    candidate = requested or env_value
    if not candidate:
        return default_value
    normalized = candidate.upper()
    allowed_map = {option.upper(): option for option in allowed}
    resolved = allowed_map.get(normalized)
    if resolved is None:
        logger.warning(
            "Unsupported value '%s' for %s hosts; using %s.",
            candidate,
            os_key,
            default_value,
        )
        return default_value
    return resolved


def _run(command: list[str], *, stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=stdin_text,
        text=True,
        check=False,
        capture_output=True,
    )


def _linux_partition_path(device_path: str) -> str:
    if device_path.startswith("/dev/nvme") or device_path.startswith("/dev/mmcblk"):
        return f"{device_path}p1"
    return f"{device_path}1"


def _normalize_windows_disk_number(device: object) -> int:
    raw = str(device).strip()
    if not raw:
        raise ValueError("On Windows you must supply a disk number.")

    lowered = raw.casefold()
    if lowered.startswith(r"\\.\physicaldrive"):
        raw = raw[len(r"\\.\PhysicalDrive") :]
    elif lowered.startswith("physicaldrive"):
        raw = raw[len("PhysicalDrive") :]

    if not raw.isdigit():
        raise ValueError(f"Unable to extract disk number from '{device}'.")
    return int(raw)


def _windows_filesystem_token(filesystem: str) -> str:
    mapping = {"EXFAT": "exFAT", "FAT32": "FAT32", "NTFS": "NTFS"}
    return mapping.get(filesystem.upper(), filesystem)


def _windows_script(
    *,
    disk_number: int,
    partition_style: str,
    preferred_letter: str | None,
    volume_label: str,
    filesystem: str,
) -> str:
    preferred_letter_token = f"'{preferred_letter.rstrip(':')}'" if preferred_letter else "$null"
    ps_label = volume_label.replace("'", "''")
    return textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $diskNumber = {disk_number}
        $partitionStyle = "{partition_style}"
        $preferredLetter = {preferred_letter_token}
        $volumeLabel = '{ps_label}'
        $fsType = "{filesystem}"
        $size32GB = 32GB

        $disk = Get-Disk -Number $diskNumber -ErrorAction Stop
        if ($disk.IsOffline) {{
            Set-Disk -Number $diskNumber -IsOffline:$false -PassThru | Out-Null
        }}
        if ($disk.IsReadOnly) {{
            Set-Disk -Number $diskNumber -IsReadOnly:$false -PassThru | Out-Null
        }}

        if ($disk.PartitionStyle -eq 'RAW') {{
            Initialize-Disk -Number $diskNumber -PartitionStyle $partitionStyle -Confirm:$false | Out-Null
        }} else {{
            Clear-Disk -Number $diskNumber -RemoveData -Confirm:$false | Out-Null
            Initialize-Disk -Number $diskNumber -PartitionStyle $partitionStyle -Confirm:$false | Out-Null
        }}

        if ($fsType -eq "FAT32" -and (Get-Disk -Number $diskNumber).Size -gt $size32GB) {{
            if ($preferredLetter) {{
                $partition = New-Partition -DiskNumber $diskNumber -Size $size32GB `
                    -DriveLetter $preferredLetter -ErrorAction Stop
            }} else {{
                $partition = New-Partition -DiskNumber $diskNumber -Size $size32GB `
                    -AssignDriveLetter -ErrorAction Stop
            }}
        }} else {{
            if ($preferredLetter) {{
                $partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize `
                    -DriveLetter $preferredLetter -ErrorAction Stop
            }} else {{
                $partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize `
                    -AssignDriveLetter -ErrorAction Stop
            }}
        }}

        $partition | Format-Volume -FileSystem $fsType -NewFileSystemLabel $volumeLabel `
            -Confirm:$false -Force | Out-Null
        """
    ).strip()


def _format_windows(
    adapter: _DiskOpsAdapterLike,
    *,
    device: object,
    label: str,
    drive_letter: str | None,
    filesystem: str,
    partition_scheme: str,
) -> bool:
    disk_number = _normalize_windows_disk_number(device)
    normalized_letter: str | None = None
    if drive_letter:
        normalized_letter = adapter._normalize_windows_drive_letter(drive_letter)
        if normalized_letter is None and not bool(getattr(adapter.dut, "read_only_enabled", False)):
            adapter.logger.warning("Ignoring invalid drive letter '%s' during format.", drive_letter)

    filesystem_token = _windows_filesystem_token(filesystem)
    adapter.logger.info(
        "Formatting disk %s as %s (%s)...",
        disk_number,
        filesystem_token,
        partition_scheme,
    )
    ps = _windows_script(
        disk_number=disk_number,
        partition_style=partition_scheme,
        preferred_letter=normalized_letter,
        volume_label=label or "DUT",
        filesystem=filesystem_token,
    )
    result = _run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps,
        ]
    )
    if result.returncode != 0:
        adapter.logger.error("Windows format failed: %s", (result.stderr or result.stdout).strip())
        return False
    return True


def _format_macos(
    adapter: _DiskOpsAdapterLike,
    *,
    device: object,
    label: str,
    filesystem: str,
    partition_scheme: str,
) -> bool:
    fs_map = {"EXFAT": "ExFAT", "FAT32": "MS-DOS FAT32", "HFS+": "JHFS+", "APFS": "APFS"}
    scheme_map = {"GUID": "GPT", "MBR": "MBRFormat", "APFS_CONTAINER": "GPT"}
    fs_token = fs_map.get(filesystem.upper(), "ExFAT")
    scheme_token = scheme_map.get(partition_scheme.upper(), "GPT")
    cmd = [
        "diskutil",
        "eraseDisk",
        fs_token,
        label or "DUT",
        scheme_token,
        str(device),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        adapter.logger.error("macOS format failed: %s", (result.stderr or result.stdout).strip())
        return False
    return True


def _format_linux(
    adapter: _DiskOpsAdapterLike,
    *,
    device: object,
    label: str,
    filesystem: str,
    partition_scheme: str,
) -> bool:
    device_path = str(device).strip()
    if not device_path:
        raise ValueError("On Linux you must supply a device path (for example /dev/sdb).")

    with suppress(Exception):
        subprocess.run(["umount", _linux_partition_path(device_path)], stderr=subprocess.DEVNULL, check=False)

    label_type = "gpt" if partition_scheme.upper() == "GPT" else "msdos"
    mkfs_map = {
        "EXT4": ["mkfs.ext4", "-F", "-L", label or "DUT"],
        "NTFS": ["mkfs.ntfs", "-F", "-L", label or "DUT"],
        "VFAT": ["mkfs.vfat", "-F", "32", "-n", label or "DUT"],
        "EXFAT": ["mkfs.exfat", "-n", label or "DUT"],
    }
    mkfs_cmd = mkfs_map.get(filesystem.upper())
    if mkfs_cmd is None:
        adapter.logger.error("Unsupported Linux filesystem '%s'.", filesystem)
        return False

    parted = _run(["parted", "-s", device_path, "mklabel", label_type, "mkpart", "primary", "0%", "100%"])
    if parted.returncode != 0:
        adapter.logger.error("Linux partitioning failed: %s", (parted.stderr or parted.stdout).strip())
        return False

    partition = _linux_partition_path(device_path)
    mkfs = _run([*mkfs_cmd, partition])
    if mkfs.returncode != 0:
        adapter.logger.error("Linux format failed: %s", (mkfs.stderr or mkfs.stdout).strip())
        return False
    return True


def _format_disk(
    self: _DiskOpsAdapterLike,
    device: object,
    label: str = "DUT",
    drive_letter: str | None = None,
    filesystem: str | None = None,
    partition_scheme: str | None = None,
) -> bool:
    """Format a disk using platform tooling and adapter callbacks."""
    os_key = _detect_os_key()
    filesystem_choice = _resolve_choice(
        self.logger,
        os_key=os_key,
        requested=filesystem,
        env_value=_clean_env(os.environ.get("DUT_FORMAT_FILESYSTEM")),
        allowed=FILESYSTEM_CHOICES[os_key],
        default_value=FORMAT_DEFAULTS[os_key]["filesystem"],
    )
    partition_choice = _resolve_choice(
        self.logger,
        os_key=os_key,
        requested=partition_scheme,
        env_value=_clean_env(os.environ.get("DUT_PARTITION_SCHEME")),
        allowed=PARTITION_SCHEME_CHOICES[os_key],
        default_value=FORMAT_DEFAULTS[os_key]["partition_scheme"],
    )

    if os_key == "windows":
        return _format_windows(
            self,
            device=device,
            label=label,
            drive_letter=drive_letter,
            filesystem=filesystem_choice,
            partition_scheme=partition_choice,
        )
    if os_key == "macos":
        return _format_macos(
            self,
            device=device,
            label=label,
            filesystem=filesystem_choice,
            partition_scheme=partition_choice,
        )
    return _format_linux(
        self,
        device=device,
        label=label,
        filesystem=filesystem_choice,
        partition_scheme=partition_choice,
    )
