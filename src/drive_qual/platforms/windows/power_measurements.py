from __future__ import annotations

import importlib.util
import subprocess
from logging import Logger, getLogger
from pathlib import Path, PureWindowsPath
from types import ModuleType
from typing import Protocol, cast

from drive_qual.integrations.apricorn.usb_cli import ApricornDevice, device_identity

SAFE_EJECT_SCRIPT = Path("tools") / "safe_eject.ps1"
DISK_OPS_DIR = Path(__file__).resolve().parents[4] / "tools"
DISK_OPS_PATH = DISK_OPS_DIR / "disk_ops.py"
DRIVE_TOKEN_WITH_COLON_LEN = 2


class _FormatDiskFn(Protocol):
    def __call__(
        self,
        adapter: object,
        device: object,
        label: str = "DUT",
        drive_letter: str | None = None,
        filesystem: str | None = None,
        partition_scheme: str | None = None,
    ) -> bool: ...


def _display_path(path: str | Path) -> str:
    return PureWindowsPath(str(path)).as_posix()


def _load_disk_ops_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("drive_qual_disk_ops", DISK_OPS_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load disk ops module from {_display_path(DISK_OPS_PATH)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _format_disk() -> _FormatDiskFn:
    module = _load_disk_ops_module()
    return cast(_FormatDiskFn, module._format_disk)


class _DiskOpsAdapter:
    def __init__(self, dut: ApricornDevice) -> None:
        self.dut = dut
        self.logger: Logger = getLogger("drive_qual.platforms.windows.power_measurements.disk_ops")

    def _normalize_windows_drive_letter(self, drive_letter: str | None) -> str | None:
        if not drive_letter:
            return None
        token = drive_letter.split(",")[0].strip().replace("\\", "").replace("/", "")
        if token.endswith(":"):
            token = token[:-1]
        if len(token) != 1 or not token.isalpha():
            return None
        return f"{token.upper()}:"

    def _resolve_serial_reference(self) -> str | None:
        return self.dut.iSerial

    def _update_dut_from_device_info(
        self,
        _device_info: object,
        *,
        stage: str,
        volume_present: bool,
        refresh_from_tool: bool,
        serial_number: str | None,
    ) -> None:
        del _device_info, stage, volume_present, refresh_from_tool, serial_number


def partition_and_format_drive(dut: ApricornDevice) -> bool:
    if dut.physicalDriveNum is None:
        print(f"Skipping partition/format; disk number unavailable for {device_identity(dut)}")
        return False

    adapter = _DiskOpsAdapter(dut)
    drive_letter = adapter._normalize_windows_drive_letter(dut.driveLetter)
    return bool(
        _format_disk()(
            adapter,
            dut.physicalDriveNum,
            label="DUT",
            drive_letter=drive_letter,
        )
    )


def prompt_disk_management_visible(dut: ApricornDevice) -> bool:
    print(f"\nLaunching Disk Management for {device_identity(dut)}...")
    try:
        subprocess.Popen(["diskmgmt.msc"], shell=True)
    except Exception as exc:
        print(f"Failed to launch Disk Management: {exc}")

    prompt = f"Can the drive be seen in Disk Management for {device_identity(dut)}? [true/false]: "
    while True:
        response = input(prompt).strip().casefold()
        if response == "true":
            return True
        if response == "false":
            return False


def run_safe_eject_script(dut: ApricornDevice) -> bool:
    if dut.physicalDriveNum is None:
        print(f"Skipping safe eject; disk number unavailable for {device_identity(dut)}")
        return False

    script_path = SAFE_EJECT_SCRIPT.resolve()
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-DiskNumber",
        str(dut.physicalDriveNum),
    ]
    print(f"Running safe eject script for {device_identity(dut)}")
    result = subprocess.run(command, check=False)
    if result.returncode == 0:
        return True

    print(f"Safe eject script failed with return code {result.returncode}")
    return False


def normalize_drive_target(raw: str | None) -> str:
    if raw is None or not raw.strip():
        raise RuntimeError("Drive letter not available for device.")
    token = raw.strip()
    if len(token) == 1 and token.isalpha():
        return f"{token}:\\"
    if len(token) == DRIVE_TOKEN_WITH_COLON_LEN and token[1] == ":" and token[0].isalpha():
        return f"{token}\\"
    return token


# Backward-compatible aliases for legacy imports/tests.
def _partition_and_format_drive(dut: ApricornDevice) -> bool:
    return partition_and_format_drive(dut)


def _prompt_disk_management_visible(dut: ApricornDevice) -> bool:
    return prompt_disk_management_visible(dut)


def _run_safe_eject_script(dut: ApricornDevice) -> bool:
    return run_safe_eject_script(dut)


def _normalize_drive_target(raw: str | None) -> str:
    return normalize_drive_target(raw)


# Compatibility shim for callers still importing this module for workflow execution.
def run_power_measurements_step() -> None:
    from drive_qual.platforms.power_measurements_mixed import run_power_measurements_step as run_mixed_platform_step

    run_mixed_platform_step()


__all__ = [
    "normalize_drive_target",
    "partition_and_format_drive",
    "prompt_disk_management_visible",
    "run_power_measurements_step",
    "run_safe_eject_script",
]
