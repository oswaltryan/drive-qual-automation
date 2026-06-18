from __future__ import annotations

import csv
import re
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from drive_qual.core.dut_selection import select_report_dut_name
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.temperature import (
    copy_temperature_chart,
    load_temperature_performance_csv,
    plot_temperature_chart,
    temperature_artifact_dir,
    temperature_chart_path,
    update_temperature_performance,
)
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice, device_identity
from drive_qual.integrations.instruments.watlow import DEFAULT_F4T_IP, F4TController
from drive_qual.platforms.performance_common import (
    refresh_dut_device,
    resolve_or_bind_dut_device,
    resolve_report_dut_name,
)

LOW_TEMPERATURE_C = 20.000
HIGH_TEMPERATURE_C = 30.000
AMBIENT_TEMPERATURE_C = 25.000
TEMPERATURE_SETPOINTS_C: tuple[float, ...] = (LOW_TEMPERATURE_C, HIGH_TEMPERATURE_C)
SETPOINT_TOLERANCE_C = 0.1
SNAPSHOT_INTERVAL_SECONDS = 5.0
DISK_TESTER_INTERVAL_SECONDS = 60
DISK_TESTER_STOP_TIMEOUT_SECONDS = 15.0
DISK_TESTER_SPEED_RE = re.compile(
    r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+"
    r"(?P<category>SEQUENTIAL|RANDOM)\s+(?P<operation>read|write):\s+"
    r"(?P<speed>\d+(?:\.\d+)?)\s+MiB/s",
    re.IGNORECASE,
)

SNAPSHOT_CSV_FIELDS: tuple[str, ...] = (
    "timestamp",
    "temperature_c",
    "temperature_f",
)
TEMPERATURE_PERFORMANCE_CSV_FIELDS: tuple[str, ...] = ("TemperatureC", "Operation", "SpeedMiB")


@dataclass(frozen=True)
class TemperatureRunArtifacts:
    snapshot_csv: Path
    performance_csv: Path
    disk_tester_log: Path
    disk_tester_stdout: Path
    disk_tester_stderr: Path


@dataclass(frozen=True)
class TemperatureTarget:
    drive_target: str
    dut_name: str


@dataclass(frozen=True)
class TemperatureSnapshot:
    timestamp: datetime
    temperature_c: float


@dataclass(frozen=True)
class DiskTesterSpeed:
    timestamp: datetime
    operation: str
    speed_mib: float


def _part_number_from_report(data: dict[str, Any], fallback: str) -> str:
    drive_info = data.get("drive_info")
    if isinstance(drive_info, dict):
        value = drive_info.get("apricorn_part_number")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _timestamp_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _phase_name(setpoint_c: float) -> str:
    return f"{setpoint_c:g}c"


def _temperature_artifacts(part_number: str) -> TemperatureRunArtifacts:
    artifact_dir = temperature_artifact_dir(part_number)
    timestamp = _timestamp_for_filename()
    return TemperatureRunArtifacts(
        snapshot_csv=artifact_dir / f"temperature_snapshots_{timestamp}.csv",
        performance_csv=artifact_dir / f"temperature_performance_{timestamp}.csv",
        disk_tester_log=artifact_dir / f"disk_tester_temperature_{timestamp}.log",
        disk_tester_stdout=artifact_dir / f"disk_tester_temperature_{timestamp}.stdout.log",
        disk_tester_stderr=artifact_dir / f"disk_tester_temperature_{timestamp}.stderr.log",
    )


def _disk_tester_command(target_path: str, log_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "drive_qual.benchmarks.disk_tester",
        "temp",
        "--path",
        target_path,
        "--interval",
        str(DISK_TESTER_INTERVAL_SECONDS),
        "--log",
        str(log_path),
    ]


def _normalize_drive_letter(raw: str) -> str:
    token = raw.strip().replace("\\", "").replace("/", "")
    if token.endswith(":"):
        token = token[:-1]
    if len(token) != 1 or not token.isalpha():
        raise RuntimeError(f"Invalid drive letter for temperature testing: {raw!r}")
    return f"{token.upper()}:"


def _drive_letter_or_none(dut: ApricornDevice) -> str | None:
    if dut.driveLetter is None:
        return None
    try:
        return _normalize_drive_letter(dut.driveLetter)
    except RuntimeError:
        return None


def _format_temperature_target(dut: ApricornDevice) -> None:
    if sys.platform != "win32":
        raise RuntimeError(f"usb --json did not include a usable driveLetter for {device_identity(dut)}.")

    from drive_qual.platforms.windows.power_measurements import partition_and_format_drive

    print(f"No usable drive letter found for {device_identity(dut)}; partitioning and formatting DUT.")
    if not partition_and_format_drive(dut):
        raise RuntimeError(f"Partition/format failed for {device_identity(dut)}.")


def _resolve_temperature_target(report_path: Path) -> TemperatureTarget:
    dut_name = resolve_report_dut_name(report_path)
    dut_info = resolve_or_bind_dut_device(
        report_path,
        dut_name,
        prompt="Connect the Apricorn device to continue temperature testing...",
        required_fields=("physicalDriveNum",) if sys.platform == "win32" else (),
    )

    drive_letter = _drive_letter_or_none(dut_info)
    if drive_letter is None:
        _format_temperature_target(dut_info)
        dut_info = refresh_dut_device(
            report_path,
            dut_name,
            prompt="Waiting for DUT to re-enumerate after format...",
            required_fields=("physicalDriveNum", "driveLetter") if sys.platform == "win32" else ("driveLetter",),
        )
        drive_letter = _drive_letter_or_none(dut_info)

    if drive_letter is None:
        raise RuntimeError(f"usb --json did not include a usable driveLetter for {device_identity(dut_info)}.")
    return TemperatureTarget(drive_target=drive_letter, dut_name=dut_name)


def _resolve_drive_target(report_path: Path) -> str:
    return _resolve_temperature_target(report_path).drive_target


def _start_disk_tester(
    *,
    target_path: str,
    artifacts: TemperatureRunArtifacts,
    stdout: TextIO,
    stderr: TextIO,
) -> subprocess.Popen[str]:
    command = _disk_tester_command(target_path, artifacts.disk_tester_log)
    print(f"Starting disk tester: {' '.join(command)}")
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)


def _setpoint_reached(*, measured_c: float, setpoint_c: float) -> bool:
    return abs(measured_c - setpoint_c) <= SETPOINT_TOLERANCE_C


def _write_snapshot_and_check_setpoint(
    writer: csv.DictWriter[str],
    *,
    controller: F4TController,
    setpoint_target_c: float,
) -> bool:
    try:
        snapshot = controller.read_snapshot()
    except Exception as exc:
        print(f"Warning: could not read Watlow temperature snapshot: {exc}")
        writer.writerow(
            {
                "timestamp": _timestamp(),
                "temperature_c": "",
                "temperature_f": "",
            }
        )
        return False

    writer.writerow(
        {
            "timestamp": snapshot.timestamp,
            "temperature_c": f"{snapshot.temperature_c:.3f}",
            "temperature_f": f"{snapshot.temperature_f:.3f}",
        }
    )
    print(
        "Temperature snapshot: "
        f"{snapshot.timestamp}, {snapshot.temperature_c:.3f} C, {snapshot.temperature_f:.3f} F"
    )
    return _setpoint_reached(measured_c=snapshot.temperature_c, setpoint_c=setpoint_target_c)


def _parse_snapshot_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_temperature_snapshots(path: Path) -> list[TemperatureSnapshot]:
    snapshots: list[TemperatureSnapshot] = []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            timestamp = _parse_snapshot_timestamp(row.get("timestamp", ""))
            if timestamp is None:
                continue
            try:
                temperature_c = float(row.get("temperature_c", ""))
            except ValueError:
                continue
            snapshots.append(TemperatureSnapshot(timestamp=timestamp.replace(tzinfo=None), temperature_c=temperature_c))
    return snapshots


def _load_disk_tester_speeds(path: Path) -> list[DiskTesterSpeed]:
    speeds: list[DiskTesterSpeed] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = DISK_TESTER_SPEED_RE.match(line.strip())
        if match is None:
            continue
        speeds.append(
            DiskTesterSpeed(
                timestamp=datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S"),
                operation=match.group("operation").casefold(),
                speed_mib=float(match.group("speed")),
            )
        )
    return speeds


def _nearest_snapshot_temperature(snapshots: list[TemperatureSnapshot], timestamp: datetime) -> float | None:
    if not snapshots:
        return None
    return min(snapshots, key=lambda snapshot: abs((snapshot.timestamp - timestamp).total_seconds())).temperature_c


def _write_temperature_performance_csv(
    *,
    snapshots_csv: Path,
    disk_tester_log: Path,
    output_csv: Path,
) -> Path:
    snapshots = _load_temperature_snapshots(snapshots_csv)
    speeds = _load_disk_tester_speeds(disk_tester_log)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TEMPERATURE_PERFORMANCE_CSV_FIELDS)
        writer.writeheader()
        for speed in speeds:
            temperature_c = _nearest_snapshot_temperature(snapshots, speed.timestamp)
            if temperature_c is None:
                continue
            writer.writerow(
                {
                    "TemperatureC": f"{temperature_c:.3f}",
                    "Operation": speed.operation,
                    "SpeedMiB": f"{speed.speed_mib:.2f}",
                }
            )
    return output_csv


def _finalize_temperature_results(
    *,
    folder_name: str,
    dut_name: str,
    artifacts: TemperatureRunArtifacts,
) -> None:
    performance_csv = _write_temperature_performance_csv(
        snapshots_csv=artifacts.snapshot_csv,
        disk_tester_log=artifacts.disk_tester_log,
        output_csv=artifacts.performance_csv,
    )
    rows = load_temperature_performance_csv(performance_csv)
    if not rows:
        raise RuntimeError(f"No temperature/performance rows could be derived from {artifacts.disk_tester_log}.")
    post_process_temperature_data(
        part_number=folder_name,
        dut_name=dut_name,
        performance_csv=performance_csv,
    )


def _run_snapshot_phase(
    *,
    controller: F4TController,
    writer: csv.DictWriter[str],
    csv_handle: TextIO,
    disk_tester: subprocess.Popen[str],
    setpoint_c: float,
) -> None:
    phase = _phase_name(setpoint_c)
    print(f"Setting chamber setpoint to {setpoint_c:g} C.")
    controller.write_setpoint_c(setpoint_c)

    while True:
        if disk_tester.poll() is not None:
            raise RuntimeError(f"disk_tester.py exited early with code {disk_tester.returncode}.")
        reached = _write_snapshot_and_check_setpoint(
            writer,
            controller=controller,
            setpoint_target_c=setpoint_c,
        )
        csv_handle.flush()
        if reached:
            print(f"Chamber reached {phase} setpoint within {SETPOINT_TOLERANCE_C:g} C.")
            return
        time.sleep(SNAPSHOT_INTERVAL_SECONDS)


def _return_chamber_to_ambient(controller: F4TController) -> None:
    print(f"Returning chamber setpoint to ambient ({AMBIENT_TEMPERATURE_C:g} C).")
    controller.write_setpoint_c(AMBIENT_TEMPERATURE_C)

    while True:
        try:
            snapshot = controller.read_snapshot()
        except Exception as exc:
            print(f"Warning: could not read Watlow ambient snapshot: {exc}")
            time.sleep(SNAPSHOT_INTERVAL_SECONDS)
            continue

        print(
            "Ambient normalization snapshot: "
            f"{snapshot.timestamp}, {snapshot.temperature_c:.3f} C, {snapshot.temperature_f:.3f} F"
        )
        if _setpoint_reached(measured_c=snapshot.temperature_c, setpoint_c=AMBIENT_TEMPERATURE_C):
            print(f"Chamber reached ambient within {SETPOINT_TOLERANCE_C:g} C.")
            return
        time.sleep(SNAPSHOT_INTERVAL_SECONDS)


def run_temperature_step(part_number: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    artifacts = _temperature_artifacts(folder_name)
    target = _resolve_temperature_target(report_path)
    controller = F4TController(ip=DEFAULT_F4T_IP)

    print(f"Writing temperature snapshots to: {artifacts.snapshot_csv}")
    print(f"Writing temperature performance rows to: {artifacts.performance_csv}")
    print(f"Writing disk tester log to: {artifacts.disk_tester_log}")
    print(f"Using Watlow F4T IP: {DEFAULT_F4T_IP}")

    with ExitStack() as stack:
        csv_handle = stack.enter_context(artifacts.snapshot_csv.open("w", newline="", encoding="utf-8"))
        stdout = stack.enter_context(artifacts.disk_tester_stdout.open("a", encoding="utf-8"))
        stderr = stack.enter_context(artifacts.disk_tester_stderr.open("a", encoding="utf-8"))
        writer = csv.DictWriter(csv_handle, fieldnames=SNAPSHOT_CSV_FIELDS)
        writer.writeheader()
        csv_handle.flush()

        disk_tester = _start_disk_tester(
            target_path=target.drive_target,
            artifacts=artifacts,
            stdout=stdout,
            stderr=stderr,
        )
        try:
            for setpoint_c in TEMPERATURE_SETPOINTS_C:
                _run_snapshot_phase(
                    controller=controller,
                    writer=writer,
                    csv_handle=csv_handle,
                    disk_tester=disk_tester,
                    setpoint_c=setpoint_c,
                )
        except KeyboardInterrupt:
            print("Temperature workflow interrupted; stopping disk tester.")
            raise
        finally:
            _stop_process(disk_tester)

    _return_chamber_to_ambient(controller)
    _finalize_temperature_results(folder_name=folder_name, dut_name=target.dut_name, artifacts=artifacts)
    print(f"Temperature workflow complete. Snapshot CSV: {artifacts.snapshot_csv}")


def post_process_temperature_data(
    *,
    part_number: str | None = None,
    dut_name: str | None = None,
    performance_csv: Path | None = None,
    chart: Path | None = None,
    chart_title: str = "Temperature vs Speed",
) -> Path:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    resolved_dut_name = dut_name or select_report_dut_name(report_path)
    actual_part_number = _part_number_from_report(data, folder_name)

    if performance_csv is not None:
        rows = load_temperature_performance_csv(performance_csv)
        update_temperature_performance(data, resolved_dut_name, rows)
        if chart is None:
            generated_chart = temperature_chart_path(actual_part_number, resolved_dut_name)
            plot_temperature_chart(rows, generated_chart, title=chart_title)
            print(f"Saved temperature chart to: {generated_chart}")

    if chart is not None:
        copied_chart = copy_temperature_chart(chart, part_number=actual_part_number, dut_name=resolved_dut_name)
        print(f"Saved temperature chart to: {copied_chart}")

    save_report(report_path, data)
    print(f"Updated temperature data in {report_path}")
    return report_path
