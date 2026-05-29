from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from drive_qual.core.reliability import (
    PASSES_REQUIRED,
    ReliabilityResult,
    ensure_reliability_section,
    parse_reliability_log,
    reliability_artifact_log_path,
    update_reliability_report,
)
from drive_qual.core.report_session import load_report, resolve_folder_name, save_report
from drive_qual.core.storage_paths import localize_windows_path
from drive_qual.platforms.performance_common import (
    load_part_number_and_report,
    resolve_or_bind_dut_device,
    resolve_report_dut_name,
)

DISK_TESTER_EXE = Path("C:/Users/itadmin/Desktop/disk_tester.exe")
DESKTOP_LOG = Path("C:/Users/itadmin/Desktop/disk_test.log")
DESKTOP_DIR = Path("C:/Users/itadmin/Desktop")


class _ReliabilityPaths:
    def __init__(self, *, report_path: Path, artifact_log: Path, desktop_reliability_log: Path) -> None:
        self.report_path = report_path
        self.artifact_log = artifact_log
        self.desktop_reliability_log = desktop_reliability_log


def run_reliability_step(part_number: str | None = None) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows reliability step can only run on Windows.")

    paths = _resolve_reliability_paths(part_number)
    data = load_report(paths.report_path)
    ensure_reliability_section(data)
    save_report(paths.report_path, data)

    _use_desktop_log_if_no_artifact_log(
        paths.artifact_log,
        desktop_logs=(paths.desktop_reliability_log, DESKTOP_LOG),
    )
    existing_result = parse_reliability_log(paths.artifact_log)
    passes_remaining = max(PASSES_REQUIRED - existing_result.passes_completed, 0)
    print(f"Reliability summaries found: {existing_result.passes_completed}/{PASSES_REQUIRED}")

    return_code: int | None = None
    if passes_remaining == 0:
        print("Reliability minimum already met; skipping disk_tester.exe and parsing existing artifact log.")
        result = existing_result
    else:
        return_code, result = _run_missing_reliability_passes(paths, passes_remaining)

    data = load_report(paths.report_path)
    update_reliability_report(data, result)
    save_report(paths.report_path, data)
    print(f"Updated reliability results in {paths.report_path}: {result.status}")

    if result.status != "pass":
        raise RuntimeError(
            "Reliability test did not pass "
            f"({result.passes_completed}/{result.passes_required} passes, return_code={return_code})."
        )


def _resolve_reliability_paths(part_number: str | None) -> _ReliabilityPaths:
    folder_name = resolve_folder_name(part_number)
    actual_pn, report_path = load_part_number_and_report(folder_name)
    return _ReliabilityPaths(
        report_path=report_path,
        artifact_log=localize_windows_path(reliability_artifact_log_path(actual_pn)),
        desktop_reliability_log=DESKTOP_DIR / f"{actual_pn}_reliability.log",
    )


def _run_missing_reliability_passes(paths: _ReliabilityPaths, passes_remaining: int) -> tuple[int, ReliabilityResult]:
    drive_target = _resolve_drive_target(paths.report_path)
    print(f"Running reliability test for {passes_remaining} pass(es) on {drive_target}.")
    return_code = _run_disk_tester(drive_target, passes_remaining)
    paths.artifact_log.parent.mkdir(parents=True, exist_ok=True)
    if DESKTOP_LOG.exists():
        _copy_desktop_log_to_artifact(DESKTOP_LOG, paths.artifact_log)
    else:
        print(f"Warning: disk_tester log not found at {DESKTOP_LOG}; parsing existing artifact log only.")
    result = parse_reliability_log(
        paths.artifact_log,
        passes_requested_this_run=passes_remaining,
        return_code=return_code,
    )
    return return_code, result


def _resolve_drive_target(report_path: Path) -> str:
    dut_name = resolve_report_dut_name(report_path)
    dut_info = resolve_or_bind_dut_device(
        report_path,
        dut_name,
        prompt="Connect the Apricorn device to continue reliability testing...",
        required_fields=("driveLetter",),
    )
    if dut_info.driveLetter is None:
        raise RuntimeError("Could not determine drive letter for the connected device.")
    return _normalize_drive_target(dut_info.driveLetter)


def _normalize_drive_target(raw: str) -> str:
    token = raw.strip().replace("\\", "").replace("/", "")
    if token.endswith(":"):
        token = token[:-1]
    if len(token) != 1 or not token.isalpha():
        raise RuntimeError(f"Invalid drive letter for reliability testing: {raw!r}")
    return f"{token.upper()}:"


def _run_disk_tester(drive_target: str, passes: int) -> int:
    if not DISK_TESTER_EXE.exists():
        raise FileNotFoundError(f"disk_tester.exe not found at {DISK_TESTER_EXE}")
    command = [
        str(DISK_TESTER_EXE),
        "full-test",
        "--path",
        drive_target,
        "--direct-io",
        "--preallocate",
        "--passes",
        str(passes),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    if process.stdout is not None:
        for line in process.stdout:
            print(line, end="", flush=True)
    return process.wait()


def _use_desktop_log_if_no_artifact_log(artifact_log: Path, *, desktop_logs: tuple[Path, ...]) -> None:
    if artifact_log.exists():
        return
    for desktop_log in desktop_logs:
        if not desktop_log.exists():
            continue
        if _confirm_use_desktop_log(desktop_log):
            _copy_desktop_log_to_artifact(desktop_log, artifact_log)
        return


def _confirm_use_desktop_log(desktop_log: Path) -> bool:
    response = input(f"Found reliability log at {desktop_log}. Use it for this report? [y/N]: ").strip().casefold()
    return response in {"y", "yes"}


def _copy_desktop_log_to_artifact(desktop_log: Path, artifact_log: Path) -> None:
    if not desktop_log.exists():
        raise FileNotFoundError(f"disk_tester log not found at {desktop_log}")
    artifact_log.parent.mkdir(parents=True, exist_ok=True)
    source_text = desktop_log.read_text(encoding="utf-8", errors="replace")
    if artifact_log.exists():
        existing_text = artifact_log.read_text(encoding="utf-8", errors="replace")
        if source_text not in existing_text:
            with artifact_log.open("a", encoding="utf-8") as destination:
                destination.write("\n")
                destination.write(source_text)
    else:
        shutil.copy2(desktop_log, artifact_log)
    desktop_log.unlink()
    print(f"Copied reliability log to {artifact_log} and removed {desktop_log}.")
