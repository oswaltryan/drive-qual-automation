from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from types import ModuleType
from typing import Any, Protocol, TextIO

from drive_qual.core.dut_selection import select_report_dut_name
from drive_qual.core.io_utils import mk_dir
from drive_qual.core.product_profiles import normalize_product_name, report_dut_name_candidates
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, localize_windows_path
from drive_qual.core.temperature_contract import (
    HIGH_TEMPERATURE_C,
    LOW_TEMPERATURE_C,
)
from drive_qual.integrations.apricorn.usb_cli import (
    ApricornDevice,
    device_identity,
    get_usb_payload,
    is_usb_3x,
    list_apricorn_devices,
    missing_required_fields,
    select_apricorn_device,
    usb_generation_label,
)
from drive_qual.integrations.instruments.watlow import DEFAULT_F4T_IP, F4TController
from drive_qual.platforms.performance_common import resolve_report_dut_name

AMBIENT_TEMPERATURE_C = 25.000
TEMPERATURE_SETPOINTS_C: tuple[float, ...] = (float(LOW_TEMPERATURE_C), float(HIGH_TEMPERATURE_C))
SETPOINT_TOLERANCE_C = 0.4
SETPOINT_SOAK_SECONDS = 300.0
SNAPSHOT_INTERVAL_SECONDS = 2.0
DISK_TESTER_STOP_TIMEOUT_SECONDS = 15.0
DISK_TESTER_IO_RETRIES = 3
DISK_TESTER_RETRY_DELAY_SECONDS = 5.0
ARTIFACT_PUBLISH_INTERVAL_SECONDS = 60.0
ARTIFACT_PUBLISH_RETRIES = 3
ARTIFACT_PUBLISH_RETRY_DELAY_SECONDS = 2.0
TEMPERATURE_ARTIFACT_CATEGORY = "Temperature"
TEMPERATURE_CHART_SUFFIX = "Temperature Data.png"
TEMPERATURE_PROFILE_CSV_FIELDS: tuple[str, ...] = ("TempRounded", "Operation", "SpeedMiB", "Mode")
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_. -]+")
__all__ = [
    "SNAPSHOT_CSV_FIELDS",
    "SETPOINT_SOAK_SECONDS",
    "SNAPSHOT_INTERVAL_SECONDS",
    "TemperatureRunArtifacts",
    "post_process_temperature_data",
    "run_temperature_step",
    "sys",
    "temperature_plotter",
    "time",
]

SNAPSHOT_CSV_FIELDS: tuple[str, ...] = (
    "timestamp",
    "temperature_c",
    "temperature_f",
)


@dataclass(frozen=True)
class TemperatureRunArtifacts:
    snapshot_csv: Path
    performance_csv: Path
    disk_tester_log: Path
    disk_tester_stdout: Path
    disk_tester_stderr: Path
    progress_log: Path | None = None


@dataclass(frozen=True)
class TemperatureTarget:
    drive_target: str
    dut_name: str


@dataclass(frozen=True)
class TemperatureResumeState:
    timestamp: str
    source_artifacts: TemperatureRunArtifacts | None
    completed_setpoints: frozenset[float]


@dataclass(frozen=True)
class TemperatureRunContext:
    resume_state: TemperatureResumeState
    local_artifacts: TemperatureRunArtifacts
    published_artifacts: TemperatureRunArtifacts
    local_chart: Path
    published_chart: Path
    publish_artifacts: Callable[[bool], None]


class _TemperaturePlotterProxy:
    def _module(self) -> ModuleType:
        from drive_qual.core import temperature

        return temperature

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module(), name)


class TemperatureController(Protocol):
    def write_setpoint_c(self, setpoint_c: float) -> None: ...

    def read_snapshot(self) -> Any: ...


class DiskTesterProcess(Protocol):
    returncode: Any

    def poll(self) -> int | None: ...


temperature_plotter = _TemperaturePlotterProxy()


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


def _safe_filename_component(value: str) -> str:
    return SAFE_FILENAME_RE.sub("_", value).strip(" ._")


def _temperature_artifact_dir(part_number: str, *, create: bool = True) -> Path:
    path = PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, TEMPERATURE_ARTIFACT_CATEGORY)
    local_path = localize_windows_path(Path(str(path)))
    if create:
        mk_dir(local_path)
    return local_path


def _temperature_chart_path(part_number: str, dut_name: str) -> Path:
    safe_dut = _safe_filename_component(dut_name) or "DUT"
    return _temperature_artifact_dir(part_number) / f"{safe_dut} {TEMPERATURE_CHART_SUFFIX}"


def _artifacts_in(artifact_dir: Path, timestamp: str) -> TemperatureRunArtifacts:
    return TemperatureRunArtifacts(
        snapshot_csv=artifact_dir / f"temperature_snapshots_{timestamp}.csv",
        performance_csv=artifact_dir / f"temperature_performance_{timestamp}.csv",
        disk_tester_log=artifact_dir / f"disk_tester_temperature_{timestamp}.log",
        disk_tester_stdout=artifact_dir / f"disk_tester_temperature_{timestamp}.stdout.log",
        disk_tester_stderr=artifact_dir / f"disk_tester_temperature_{timestamp}.stderr.log",
        progress_log=artifact_dir / f"temperature_progress_{timestamp}.jsonl",
    )


def _temperature_artifacts(part_number: str, timestamp: str | None = None) -> TemperatureRunArtifacts:
    return _artifacts_in(_temperature_artifact_dir(part_number), timestamp or _timestamp_for_filename())


def _local_temperature_artifacts(part_number: str, timestamp: str) -> TemperatureRunArtifacts:
    artifact_dir = _local_temperature_root(part_number) / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return _artifacts_in(artifact_dir, timestamp)


def _local_temperature_root(part_number: str) -> Path:
    safe_part_number = _safe_filename_component(part_number) or "unknown-part"
    return Path(tempfile.gettempdir(), "drive-qual", "temperature", safe_part_number)


def _timestamp_from_snapshot_path(path: Path) -> str | None:
    match = re.search(r"(\d{8}_\d{6})", path.name)
    return match.group(1) if match else None


def _completed_setpoints_from_progress(path: Path, dut_name: str) -> tuple[frozenset[float], bool]:
    completed: set[float] = set()
    run_completed = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset(), False
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        event_dut = event.get("dut_name")
        if isinstance(event_dut, str) and event_dut.casefold() != dut_name.casefold():
            continue
        if event.get("event") == "run_completed":
            run_completed = True
        if event.get("event") != "phase_completed":
            continue
        try:
            setpoint = float(event["setpoint_c"])
        except (KeyError, TypeError, ValueError):
            continue
        if setpoint in TEMPERATURE_SETPOINTS_C:
            completed.add(setpoint)
    return frozenset(completed), run_completed


def _completed_setpoints_from_snapshots(path: Path) -> frozenset[float]:
    completed: set[float] = set()
    soak_started: dict[float, datetime | None] = {setpoint: None for setpoint in TEMPERATURE_SETPOINTS_C}
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return frozenset()

    for row in rows:
        try:
            timestamp = datetime.fromisoformat(row["timestamp"])
            measured_c = float(row["temperature_c"])
        except (KeyError, TypeError, ValueError):
            soak_started = {setpoint: None for setpoint in TEMPERATURE_SETPOINTS_C}
            continue
        for setpoint in TEMPERATURE_SETPOINTS_C:
            if not _setpoint_reached(measured_c=measured_c, setpoint_c=setpoint):
                soak_started[setpoint] = None
                continue
            started = soak_started[setpoint]
            if started is None:
                soak_started[setpoint] = timestamp
            elif (timestamp - started).total_seconds() >= SETPOINT_SOAK_SECONDS:
                completed.add(setpoint)
    return frozenset(completed)


def _temperature_run_candidates(part_number: str) -> list[tuple[str, TemperatureRunArtifacts]]:
    candidates: dict[str, TemperatureRunArtifacts] = {}
    roots = (_temperature_artifact_dir(part_number, create=False), _local_temperature_root(part_number))
    for root in roots:
        try:
            snapshot_paths = list(root.glob("temperature_snapshots_*.csv"))
            snapshot_paths.extend(root.glob("*/temperature_snapshots_*.csv"))
            snapshot_paths.extend(root.glob("temperature_progress_*.jsonl"))
            snapshot_paths.extend(root.glob("*/temperature_progress_*.jsonl"))
        except OSError:
            continue
        for artifact_path in snapshot_paths:
            timestamp = _timestamp_from_snapshot_path(artifact_path)
            if timestamp is not None:
                candidates[timestamp] = _artifacts_in(artifact_path.parent, timestamp)
    return sorted(candidates.items(), reverse=True)


def _resolve_temperature_resume_state(
    part_number: str,
    dut_name: str,
    *,
    restart: bool,
) -> TemperatureResumeState:
    if not restart:
        eligible: list[TemperatureResumeState] = []
        for timestamp, artifacts in _temperature_run_candidates(part_number):
            progress_path = artifacts.progress_log
            completed, run_completed = (
                _completed_setpoints_from_progress(progress_path, dut_name)
                if progress_path is not None and progress_path.exists()
                else (_completed_setpoints_from_snapshots(artifacts.snapshot_csv), False)
            )
            if run_completed:
                break
            eligible.append(TemperatureResumeState(timestamp, artifacts, completed))
        if eligible:
            return max(eligible, key=lambda state: (len(state.completed_setpoints), state.timestamp))
    return TemperatureResumeState(_timestamp_for_filename(), None, frozenset())


def _prepare_local_resume_artifacts(
    part_number: str,
    state: TemperatureResumeState,
) -> TemperatureRunArtifacts:
    local_artifacts = _local_temperature_artifacts(part_number, state.timestamp)
    source = state.source_artifacts
    if source is None or source.snapshot_csv.parent == local_artifacts.snapshot_csv.parent:
        return local_artifacts
    for field_name in TemperatureRunArtifacts.__dataclass_fields__:
        source_path = getattr(source, field_name)
        destination_path = getattr(local_artifacts, field_name)
        if isinstance(source_path, Path) and isinstance(destination_path, Path) and source_path.exists():
            _atomic_copy(source_path, destination_path)
    return local_artifacts


def _write_progress_event(
    artifacts: TemperatureRunArtifacts,
    *,
    event: str,
    part_number: str,
    dut_name: str,
    setpoint_c: float | None = None,
) -> None:
    if artifacts.progress_log is None:
        return
    payload: dict[str, Any] = {
        "timestamp": _timestamp(),
        "event": event,
        "part_number": part_number,
        "dut_name": dut_name,
    }
    if setpoint_c is not None:
        payload["setpoint_c"] = setpoint_c
    with artifacts.progress_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()


def _record_recovered_setpoints(
    artifacts: TemperatureRunArtifacts,
    state: TemperatureResumeState,
    *,
    part_number: str,
    dut_name: str,
) -> None:
    source_progress = state.source_artifacts.progress_log if state.source_artifacts is not None else None
    if source_progress is not None and source_progress.exists():
        return
    for setpoint_c in sorted(state.completed_setpoints):
        _write_progress_event(
            artifacts,
            event="phase_completed",
            part_number=part_number,
            dut_name=dut_name,
            setpoint_c=setpoint_c,
        )


def _disk_tester_command(target_path: str, log_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "drive_qual.benchmarks.disk_tester",
        "temp",
        "--path",
        target_path,
        "--log",
        str(log_path),
        "--failure-action",
        "retry",
        "--max-retries",
        str(DISK_TESTER_IO_RETRIES),
        "--retry-delay",
        str(DISK_TESTER_RETRY_DELAY_SECONDS),
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

    from drive_qual.platforms.windows import power_measurements

    print(f"No usable drive letter found for {device_identity(dut)}; partitioning and formatting DUT.")
    if not power_measurements.partition_and_format_drive(dut):
        raise RuntimeError(f"Partition/format failed for {device_identity(dut)}.")


def _current_apricorn_devices_for_temperature() -> list[ApricornDevice]:
    payload = get_usb_payload()
    if not isinstance(payload, dict):
        raise RuntimeError(
            "Unable to read Apricorn USB inventory from `usb --json`. "
            "Confirm the Apricorn USB CLI is installed and on PATH, then verify `usb --json` works."
        )
    return list_apricorn_devices(payload)


def _matches_temperature_product(device: ApricornDevice, dut_name: str) -> bool:
    product = device.iProduct
    if not isinstance(product, str) or not product.strip():
        return False
    normalized_product = normalize_product_name(product)
    return any(
        normalize_product_name(candidate) == normalized_product for candidate in report_dut_name_candidates(dut_name)
    )


def _resolve_temperature_device_by_product(
    dut_name: str,
    *,
    prompt: str,
    required_fields: tuple[str, ...],
) -> ApricornDevice:
    devices = _current_apricorn_devices_for_temperature()
    product_matches = [device for device in devices if _matches_temperature_product(device, dut_name)]
    usb_3x_matches = [device for device in product_matches if is_usb_3x(device)]

    if not product_matches:
        print(prompt)
        available = ", ".join(device_identity(device) for device in devices) if devices else "<none>"
        raise RuntimeError(
            f"No Apricorn device with iProduct matching DUT '{dut_name}' was detected. "
            f"Detected Apricorn devices: {available}."
        )
    if not usb_3x_matches:
        detected = ", ".join(
            f"{device_identity(device)} ({usb_generation_label(device)})" for device in product_matches
        )
        raise RuntimeError(
            f"DUT '{dut_name}' was detected by iProduct but is not enumerated as USB 3.x: {detected}. "
            "Terminate and reconnect as USB 3.x."
        )

    selected = select_apricorn_device(usb_3x_matches)
    if selected is None:
        raise RuntimeError(f"No Apricorn device selected for DUT '{dut_name}'.")

    missing = missing_required_fields(selected, required_fields)
    if missing:
        fields = ", ".join(missing)
        raise RuntimeError(f"DUT '{dut_name}' is missing required usb --json fields for this step: {fields}.")
    return selected


def _resolve_temperature_target(report_path: Path) -> TemperatureTarget:
    dut_name = resolve_report_dut_name(report_path)
    dut_info = _resolve_temperature_device_by_product(
        dut_name,
        prompt="Connect the Apricorn device to continue temperature testing...",
        required_fields=("physicalDriveNum",) if sys.platform == "win32" else (),
    )

    drive_letter = _drive_letter_or_none(dut_info)
    if drive_letter is None:
        _format_temperature_target(dut_info)
        dut_info = _resolve_temperature_device_by_product(
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
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        text=True,
        creationflags=creationflags,
        start_new_session=sys.platform != "win32",
    )


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)
        if result.returncode != 0:
            print(f"Warning: taskkill could not stop the disk tester process tree: {result.stderr.strip()}")
        return
    process.terminate()
    try:
        process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=DISK_TESTER_STOP_TIMEOUT_SECONDS)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
    try:
        shutil.copy2(source, partial)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _publish_temperature_artifacts(
    source: TemperatureRunArtifacts,
    destination: TemperatureRunArtifacts,
) -> None:
    for field_name in TemperatureRunArtifacts.__dataclass_fields__:
        source_path = getattr(source, field_name)
        destination_path = getattr(destination, field_name)
        if isinstance(source_path, Path) and isinstance(destination_path, Path) and source_path.exists():
            _atomic_copy(source_path, destination_path)


def _publish_temperature_artifacts_with_retry(
    source: TemperatureRunArtifacts,
    destination: TemperatureRunArtifacts,
) -> None:
    for attempt in range(1, ARTIFACT_PUBLISH_RETRIES + 1):
        try:
            _publish_temperature_artifacts(source, destination)
            return
        except OSError:
            if attempt == ARTIFACT_PUBLISH_RETRIES:
                raise
            time.sleep(ARTIFACT_PUBLISH_RETRY_DELAY_SECONDS)


def _periodic_artifact_publisher(
    source: TemperatureRunArtifacts,
    destination: TemperatureRunArtifacts,
) -> Callable[[bool], None]:
    next_publish_at = 0.0
    last_error: str | None = None

    def publish(force: bool = False) -> None:
        nonlocal last_error, next_publish_at
        now = time.monotonic()
        if not force and now < next_publish_at:
            return
        next_publish_at = now + ARTIFACT_PUBLISH_INTERVAL_SECONDS
        try:
            _publish_temperature_artifacts(source, destination)
            if last_error is not None:
                print("Temperature artifact share is available again; publication resumed.")
            last_error = None
        except OSError as exc:
            message = str(exc)
            if message != last_error:
                print(f"Warning: could not publish temperature artifacts to {destination.snapshot_csv.parent}: {exc}")
                print(f"Local recovery files remain at: {source.snapshot_csv.parent}")
            last_error = message

    return publish


def _setpoint_reached(*, measured_c: float, setpoint_c: float) -> bool:
    return abs(measured_c - setpoint_c) <= SETPOINT_TOLERANCE_C


def _write_snapshot_and_check_setpoint(
    writer: csv.DictWriter[str],
    *,
    controller: TemperatureController,
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
    print(f"Temperature snapshot: {snapshot.timestamp}, {snapshot.temperature_c:.3f} C, {snapshot.temperature_f:.3f} F")
    return _setpoint_reached(measured_c=snapshot.temperature_c, setpoint_c=setpoint_target_c)


def _update_temperature_report_from_profile(data: dict[str, Any], dut_name: str, profile_csv: Path) -> None:
    temperature = data.get("temperature")
    if not isinstance(temperature, dict):
        raise ValueError("Invalid 'temperature' section; expected object.")

    dut_temperature = temperature.get(dut_name)
    if not isinstance(dut_temperature, dict):
        raise ValueError(f"Invalid temperature contract for DUT {dut_name!r}; expected object.")

    performance = dut_temperature.get("performance")
    if not isinstance(performance, dict):
        raise ValueError(f"Invalid temperature performance contract for DUT {dut_name!r}; expected object.")
    performance.pop("80c", None)

    with profile_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            mode = (row.get("Mode") or "").strip().casefold()
            if mode and mode != "sequential":
                continue
            operation = (row.get("Operation") or "").strip().casefold()
            if operation not in {"read", "write"}:
                continue
            try:
                requested_temp = row.get("RequestedTemp")
                temp_c = int(round(float(requested_temp or row.get("TempRounded") or "")))
                speed_mib = float(row.get("SpeedMiB") or "")
            except ValueError:
                continue

            entry = performance.get(f"{temp_c}c")
            if not isinstance(entry, dict):
                continue
            entry[f"{operation}_mb_s"] = speed_mib


def _finalize_temperature_results(
    *,
    folder_name: str,
    dut_name: str,
    artifacts: TemperatureRunArtifacts,
    chart_path: Path | None = None,
) -> None:
    data = load_report(report_path_for(folder_name))
    actual_part_number = _part_number_from_report(data, folder_name)
    output_chart = chart_path or _temperature_chart_path(actual_part_number, dut_name)
    profile_df = temperature_plotter.write_snapshot_log_chart_outputs(
        snapshot_csv=artifacts.snapshot_csv,
        log_path=artifacts.disk_tester_log,
        profile_csv=artifacts.performance_csv,
        chart_png=output_chart,
    )
    if profile_df.empty:
        raise RuntimeError(f"No temperature/performance rows could be derived from {artifacts.disk_tester_log}.")
    _update_temperature_report_from_profile(data, dut_name, artifacts.performance_csv)
    save_report(report_path_for(folder_name), data)
    print(f"Saved temperature chart to: {output_chart}")


def _run_snapshot_phase(
    *,
    controller: TemperatureController,
    writer: csv.DictWriter[str],
    csv_handle: TextIO,
    disk_tester: DiskTesterProcess,
    setpoint_c: float,
    publish_artifacts: Callable[[bool], None] | None = None,
) -> None:
    phase = _phase_name(setpoint_c)
    soak_started_at: float | None = None
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
        if publish_artifacts is not None:
            publish_artifacts(False)
        now = time.monotonic()
        if reached:
            if soak_started_at is None:
                soak_started_at = now
                if SETPOINT_SOAK_SECONDS > 0:
                    print(f"Chamber reached {phase}; soaking for {SETPOINT_SOAK_SECONDS:g} seconds.")
            if now - soak_started_at >= SETPOINT_SOAK_SECONDS:
                print(f"Chamber completed {phase} soak within {SETPOINT_TOLERANCE_C:g} C.")
                return
        elif soak_started_at is not None:
            print(f"Chamber drifted outside {phase} tolerance; restarting soak timer.")
            soak_started_at = None
        time.sleep(SNAPSHOT_INTERVAL_SECONDS)


def _return_chamber_to_ambient(controller: TemperatureController) -> None:
    print(f"Returning chamber setpoint to ambient ({AMBIENT_TEMPERATURE_C:g} C).")
    controller.write_setpoint_c(AMBIENT_TEMPERATURE_C)


def _collect_temperature_data(
    *,
    part_number: str,
    controller: TemperatureController,
    target: TemperatureTarget,
    artifacts: TemperatureRunArtifacts,
    publish_artifacts: Callable[[bool], None],
    completed_setpoints: frozenset[float],
) -> None:
    remaining_setpoints = tuple(setpoint for setpoint in TEMPERATURE_SETPOINTS_C if setpoint not in completed_setpoints)
    if not remaining_setpoints:
        print("All temperature soak phases are already complete; proceeding to finalization.")
        return

    with ExitStack() as stack:
        csv_exists = artifacts.snapshot_csv.exists() and artifacts.snapshot_csv.stat().st_size > 0
        csv_handle = stack.enter_context(artifacts.snapshot_csv.open("a", newline="", encoding="utf-8"))
        stdout = stack.enter_context(artifacts.disk_tester_stdout.open("a", encoding="utf-8"))
        stderr = stack.enter_context(artifacts.disk_tester_stderr.open("a", encoding="utf-8"))
        writer = csv.DictWriter(csv_handle, fieldnames=SNAPSHOT_CSV_FIELDS)
        if not csv_exists:
            writer.writeheader()
        csv_handle.flush()

        disk_tester = _start_disk_tester(
            target_path=target.drive_target,
            artifacts=artifacts,
            stdout=stdout,
            stderr=stderr,
        )
        try:
            for setpoint_c in remaining_setpoints:
                _write_progress_event(
                    artifacts,
                    event="phase_started",
                    part_number=part_number,
                    dut_name=target.dut_name,
                    setpoint_c=setpoint_c,
                )
                _run_snapshot_phase(
                    controller=controller,
                    writer=writer,
                    csv_handle=csv_handle,
                    disk_tester=disk_tester,
                    setpoint_c=setpoint_c,
                    publish_artifacts=publish_artifacts,
                )
                _write_progress_event(
                    artifacts,
                    event="phase_completed",
                    part_number=part_number,
                    dut_name=target.dut_name,
                    setpoint_c=setpoint_c,
                )
                publish_artifacts(True)
        finally:
            _stop_process(disk_tester)


def _finalize_and_publish_temperature_data(
    *,
    folder_name: str,
    dut_name: str,
    local_artifacts: TemperatureRunArtifacts,
    published_artifacts: TemperatureRunArtifacts,
    local_chart: Path,
    published_chart: Path,
) -> None:
    _finalize_temperature_results(
        folder_name=folder_name,
        dut_name=dut_name,
        artifacts=local_artifacts,
        chart_path=local_chart,
    )
    try:
        _publish_temperature_artifacts_with_retry(local_artifacts, published_artifacts)
        _atomic_copy(local_chart, published_chart)
    except OSError as exc:
        raise RuntimeError(
            f"Temperature testing completed, but artifacts could not be published to "
            f"{published_artifacts.snapshot_csv.parent}. Recovery files remain at "
            f"{local_artifacts.snapshot_csv.parent}."
        ) from exc


def _temperature_run_chart_paths(
    dut_name: str,
    local_artifacts: TemperatureRunArtifacts,
    published_artifacts: TemperatureRunArtifacts,
) -> tuple[Path, Path]:
    safe_dut = _safe_filename_component(dut_name) or "DUT"
    chart_filename = f"{safe_dut} {TEMPERATURE_CHART_SUFFIX}"
    return (
        local_artifacts.snapshot_csv.parent / chart_filename,
        published_artifacts.snapshot_csv.parent / chart_filename,
    )


def _print_temperature_resume_state(state: TemperatureResumeState) -> None:
    if state.source_artifacts is None:
        return
    completed = ", ".join(f"{value:g} C" for value in sorted(state.completed_setpoints)) or "none"
    remaining = (
        ", ".join(f"{value:g} C" for value in TEMPERATURE_SETPOINTS_C if value not in state.completed_setpoints)
        or "none"
    )
    print(f"Resuming temperature run {state.timestamp}.")
    print(f"Completed phases: {completed}.")
    print(f"Remaining phases: {remaining}.")


def _prepare_temperature_run(
    folder_name: str,
    target: TemperatureTarget,
    *,
    restart: bool,
) -> TemperatureRunContext:
    state = _resolve_temperature_resume_state(folder_name, target.dut_name, restart=restart)
    local_artifacts = _prepare_local_resume_artifacts(folder_name, state)
    _record_recovered_setpoints(
        local_artifacts,
        state,
        part_number=folder_name,
        dut_name=target.dut_name,
    )
    published_artifacts = _artifacts_in(_temperature_artifact_dir(folder_name, create=False), state.timestamp)
    local_chart, published_chart = _temperature_run_chart_paths(target.dut_name, local_artifacts, published_artifacts)
    return TemperatureRunContext(
        resume_state=state,
        local_artifacts=local_artifacts,
        published_artifacts=published_artifacts,
        local_chart=local_chart,
        published_chart=published_chart,
        publish_artifacts=_periodic_artifact_publisher(local_artifacts, published_artifacts),
    )


def run_temperature_step(part_number: str | None = None, *, restart: bool = False) -> None:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    target = _resolve_temperature_target(report_path)
    run = _prepare_temperature_run(folder_name, target, restart=restart)
    controller = F4TController(ip=DEFAULT_F4T_IP)

    print(f"Writing live temperature data locally to: {run.local_artifacts.snapshot_csv.parent}")
    print(f"Publishing temperature artifacts to: {run.published_artifacts.snapshot_csv.parent}")
    print(f"Using Watlow F4T IP: {DEFAULT_F4T_IP}")
    _print_temperature_resume_state(run.resume_state)

    active_error: BaseException | None = None
    try:
        _collect_temperature_data(
            part_number=folder_name,
            controller=controller,
            target=target,
            artifacts=run.local_artifacts,
            publish_artifacts=run.publish_artifacts,
            completed_setpoints=run.resume_state.completed_setpoints,
        )
        _finalize_and_publish_temperature_data(
            folder_name=folder_name,
            dut_name=target.dut_name,
            local_artifacts=run.local_artifacts,
            published_artifacts=run.published_artifacts,
            local_chart=run.local_chart,
            published_chart=run.published_chart,
        )
        _write_progress_event(
            run.local_artifacts,
            event="run_completed",
            part_number=folder_name,
            dut_name=target.dut_name,
        )
        _publish_temperature_artifacts_with_retry(run.local_artifacts, run.published_artifacts)
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            _return_chamber_to_ambient(controller)
        except Exception as reset_exc:
            if active_error is None:
                raise
            print(f"Warning: failed to return chamber to ambient: {reset_exc}")

    print(f"Temperature workflow complete. Snapshot CSV: {run.published_artifacts.snapshot_csv}")


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
        _update_temperature_report_from_profile(data, resolved_dut_name, performance_csv)
        if chart is None:
            generated_chart = _temperature_chart_path(actual_part_number, resolved_dut_name)
            temperature_plotter.plot_profile_csv(performance_csv, generated_chart, title=chart_title)
            print(f"Saved temperature chart to: {generated_chart}")

    if chart is not None:
        copied_chart = _temperature_chart_path(actual_part_number, resolved_dut_name)
        copied_chart.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chart, copied_chart)
        print(f"Saved temperature chart to: {copied_chart}")

    save_report(report_path, data)
    print(f"Updated temperature data in {report_path}")
    return report_path
