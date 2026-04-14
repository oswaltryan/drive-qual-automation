from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path, PureWindowsPath
from typing import Any, cast

from drive_qual.core.report_session import (
    load_report,
    report_path_for,
    resolve_folder_name,
    sanitize_dir_name,
    save_report,
)
from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, localize_windows_path

PATH_PARTS_MIN = 5
VALUE_AND_UNIT_PARTS = 2
DUT_PATH_PART_NUMBER_INDEX = 1
DUT_PATH_OS_INDEX = 2
UNIT_SCALE_MA = {
    "a": 1000.0,
    "ma": 1.0,
    "ua": 0.001,
}
ARTIFACT_OS_NAME_BY_PLATFORM = {
    "win32": "Windows",
    "darwin": "macOS",
    "linux": "Linux",
}
REPORT_OS_KEY_BY_ARTIFACT = {
    "windows": "windows",
    "macos": "macos",
    "linux": "linux",
}
CSV_ENCODING_CANDIDATES = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
CSV_APPEAR_TIMEOUT_SECONDS = 45.0
CSV_APPEAR_POLL_INTERVAL_SECONDS = 0.25
DUT_ALIASES: dict[str, str] = {
    "secure key 3 0": "Padlock DT FIPS",
    "secure key 3": "Padlock DT FIPS",
    "secure key dt": "Padlock DT FIPS",
    "secure key dt fips": "Padlock DT FIPS",
    "secure key 3 0 fips": "Padlock DT FIPS",
    "secure key fips": "Padlock DT FIPS",
    "aegis fips dt": "Padlock DT FIPS",
    "padlock dt": "Padlock DT FIPS",
}
MAX_IO_RAIL_SUFFIX_PATTERN = re.compile(r"^(?P<dut>.+?)(?:[\s_-]+(?P<rail>5v|12v))?$", re.IGNORECASE)


def _display_path(path: str | Path) -> str:
    return PureWindowsPath(str(path)).as_posix()


def _current_artifact_os_name() -> str:
    if sys.platform.startswith("linux"):
        return "Linux"
    return ARTIFACT_OS_NAME_BY_PLATFORM.get(sys.platform, "Windows")


def _report_os_key_from_artifact_name(name: str) -> str | None:
    return REPORT_OS_KEY_BY_ARTIFACT.get(name.strip().casefold())


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    numeric_value = _parse_numeric_value(text)
    if numeric_value is not None:
        return numeric_value

    return _parse_value_with_unit(text)


def _parse_numeric_value(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _parse_value_with_unit(text: str) -> float | None:
    parts = text.split()
    if len(parts) != VALUE_AND_UNIT_PARTS:
        return None

    raw_value, unit = parts
    try:
        magnitude = float(raw_value)
    except ValueError:
        return None
    unit_scale = UNIT_SCALE_MA.get(unit.casefold())
    if unit_scale is None:
        return None
    return magnitude * unit_scale


def _measurement_rows(csv_path: Path) -> list[dict[str, str]]:
    try:
        raw = csv_path.read_bytes()
    except OSError as exc:
        print(f"Failed to read measurements CSV {_display_path(csv_path)}: {exc}")
        return []

    lines: list[str] | None = None
    for encoding in CSV_ENCODING_CANDIDATES:
        try:
            lines = raw.decode(encoding).splitlines()
            break
        except UnicodeDecodeError:
            continue
    if lines is None:
        print(f"Failed to decode measurements CSV {_display_path(csv_path)} with supported encodings.")
        return []

    header_index = next((i for i, line in enumerate(lines) if line.startswith("Name,")), None)
    if header_index is None:
        return []

    table = "\n".join(lines[header_index:])
    reader = csv.DictReader(table.splitlines())
    rows: list[dict[str, str]] = []
    for row in reader:
        name = row.get("Name", "").strip()
        if not name:
            continue
        rows.append(
            {str(key): str(value).strip() for key, value in row.items() if key is not None and value is not None}
        )
    return rows


def _extract_measurement(csv_path: Path, measurement: str, field_name: str) -> float | None:
    for row in _measurement_rows(csv_path):
        if row.get("Name", "") != measurement:
            continue
        return _to_float(row.get(field_name))
    return None


def _wait_for_csv(
    csv_path: Path,
    *,
    timeout_seconds: float = CSV_APPEAR_TIMEOUT_SECONDS,
    interval_seconds: float = CSV_APPEAR_POLL_INTERVAL_SECONDS,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if csv_path.exists():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_seconds)


def _normalize_dut_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return re.sub(r"\s+", " ", normalized)


def _find_matching_power_key(power: dict[str, Any], candidate: str) -> str | None:
    if candidate in power:
        return candidate
    normalized_candidate = _normalize_dut_name(candidate)
    for key in power:
        if _normalize_dut_name(key) == normalized_candidate:
            return key
    return None


def _resolve_dut_key(power: dict[str, Any], dut_name: str) -> str | None:
    direct_match = _find_matching_power_key(power, dut_name)
    if direct_match is not None:
        return direct_match

    alias_target = DUT_ALIASES.get(_normalize_dut_name(dut_name))
    if alias_target is not None:
        alias_match = _find_matching_power_key(power, alias_target)
        if alias_match is not None:
            return alias_match

    if len(power) == 1:
        return next(iter(power))
    return None


def _split_dut_name_and_max_io_rail(dut_name: str) -> tuple[str, str | None]:
    match = MAX_IO_RAIL_SUFFIX_PATTERN.fullmatch(dut_name.strip())
    if match is None:
        return dut_name, None
    base_name = (match.group("dut") or "").strip() or dut_name
    rail = (match.group("rail") or "").strip().casefold() or None
    return base_name, rail


def _ensure_os_slot(fields: dict[str, Any], key: str) -> dict[str, Any]:
    default_slot = {"linux": None, "macos": None, "windows": None}
    slot = fields.setdefault(key, default_slot)
    if not isinstance(slot, dict):
        slot = default_slot.copy()
        fields[key] = slot
    return cast(dict[str, Any], slot)


def _apply_csv_to_power(power: dict[str, Any], csv_path: Path) -> bool:  # noqa: PLR0912, PLR0915
    measurement_group = csv_path.parent.name.casefold()
    dut_name = csv_path.stem
    rail = None
    if measurement_group in {"max io", "in rush current"}:
        dut_name, rail = _split_dut_name_and_max_io_rail(dut_name)
    dut_key = _resolve_dut_key(power, dut_name)
    if dut_key is None:
        print(f"Skipping CSV {_display_path(csv_path)}; could not map DUT '{dut_name}' in report power section.")
        return False

    report_os_key = _report_os_key_from_artifact_name(csv_path.parent.parent.name)
    if report_os_key is None:
        print(f"Skipping CSV {_display_path(csv_path)}; could not determine OS bucket from artifact path.")
        return False

    fields = power.get(dut_key)
    if not isinstance(fields, dict):
        fields = {}
        power[dut_key] = fields

    changed = False
    if measurement_group == "in rush current":
        max_inrush = _extract_measurement(csv_path, "Meas1", "Accum-Max")
        inrush_field = "max_inrush_current"
        if rail == "5v":
            inrush_field = "max_inrush_current_5v"
        elif rail == "12v":
            inrush_field = "max_inrush_current_12v"
        if max_inrush is not None:
            slot = _ensure_os_slot(fields, inrush_field)
            if slot.get(report_os_key) != max_inrush:
                slot[report_os_key] = max_inrush
                changed = True
    elif measurement_group == "max io":
        max_rw = _extract_measurement(csv_path, "Meas1", "Accum-Max")
        rms_rw = _extract_measurement(csv_path, "Meas3", "Accum-Mean")
        max_rw_field = "max_read_write_current"
        rms_rw_field = "rms_read_write_current"
        if rail == "5v":
            max_rw_field = "max_read_write_current_5v"
            rms_rw_field = "rms_read_write_current_5v"
        elif rail == "12v":
            max_rw_field = "max_read_write_current_12v"
            rms_rw_field = "rms_read_write_current_12v"

        if max_rw is not None:
            slot = _ensure_os_slot(fields, max_rw_field)
            if slot.get(report_os_key) != max_rw:
                slot[report_os_key] = max_rw
                changed = True
        if rms_rw is not None:
            slot = _ensure_os_slot(fields, rms_rw_field)
            if slot.get(report_os_key) != rms_rw:
                slot[report_os_key] = rms_rw
                changed = True
    return changed


def extract_power_values_from_csv(csv_path: str) -> dict[str, float | None]:
    path = localize_windows_path(Path(csv_path))
    measurement_group = path.parent.name.casefold()
    _dut_name, rail = _split_dut_name_and_max_io_rail(path.stem)
    values: dict[str, float | None] = {
        "max_inrush_current": None,
        "max_inrush_current_5v": None,
        "max_inrush_current_12v": None,
        "max_read_write_current": None,
        "rms_read_write_current": None,
        "max_read_write_current_5v": None,
        "rms_read_write_current_5v": None,
        "max_read_write_current_12v": None,
        "rms_read_write_current_12v": None,
    }
    if measurement_group == "in rush current":
        max_inrush = _extract_measurement(path, "Meas1", "Accum-Max")
        values["max_inrush_current"] = max_inrush
        if rail == "5v":
            values["max_inrush_current_5v"] = max_inrush
        elif rail == "12v":
            values["max_inrush_current_12v"] = max_inrush
    elif measurement_group == "max io":
        max_rw = _extract_measurement(path, "Meas1", "Accum-Max")
        rms_rw = _extract_measurement(path, "Meas3", "Accum-Mean")
        values["max_read_write_current"] = max_rw
        values["rms_read_write_current"] = rms_rw
        if rail == "5v":
            values["max_read_write_current_5v"] = max_rw
            values["rms_read_write_current_5v"] = rms_rw
        elif rail == "12v":
            values["max_read_write_current_12v"] = max_rw
            values["rms_read_write_current_12v"] = rms_rw
    return values


def _resolve_csv_root(data: dict[str, Any], folder_name: str, requested_part_number: str | None) -> Path:
    part_number = requested_part_number
    drive_info = data.get("drive_info")
    if isinstance(drive_info, dict):
        raw_part_number = drive_info.get("apricorn_part_number")
        if isinstance(raw_part_number, str) and raw_part_number.strip():
            part_number = raw_part_number.strip()
    if not part_number:
        part_number = folder_name
    windows_root = PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, _current_artifact_os_name())
    return localize_windows_path(Path(str(windows_root)))


def _report_power_data(csv_path: str) -> tuple[Path, Path, dict[str, Any], dict[str, Any]] | None:
    win_path = PureWindowsPath(csv_path)
    if len(win_path.parts) < PATH_PARTS_MIN:
        return None
    part_number = win_path.parts[DUT_PATH_PART_NUMBER_INDEX]
    folder_name = sanitize_dir_name(part_number)
    if not folder_name:
        return None

    report_path = report_path_for(folder_name)
    try:
        data = load_report(report_path)
    except FileNotFoundError:
        return None

    power = data.get("power")
    if not isinstance(power, dict) or not power:
        return None
    return localize_windows_path(Path(str(win_path))), report_path, data, power


def update_report_power_from_csv_path(csv_path: str) -> bool:
    resolved = _report_power_data(csv_path)
    if resolved is None:
        return False
    path, report_path, data, power = resolved
    if not _wait_for_csv(path):
        print(f"Failed to read measurements CSV {_display_path(path)}: file did not appear on host.")
        return False

    changed = _apply_csv_to_power(power, path)
    if not changed:
        return False

    save_report(report_path, data)
    print(f"Updated power measurements in {_display_path(report_path)}")
    return True


def update_power_measurements_from_saved_csvs(part_number: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    power = data.get("power")
    if not isinstance(power, dict):
        raise ValueError("Missing or invalid 'power' section in report.")
    if not power:
        raise ValueError("No DUT entries found in 'power'. Run the equipment step first.")

    csv_root = _resolve_csv_root(data, folder_name, part_number)
    inrush_dir = csv_root / "In Rush Current"
    max_io_dir = csv_root / "Max IO"
    csv_files = sorted(inrush_dir.glob("*.csv")) + sorted(max_io_dir.glob("*.csv"))
    if not csv_files:
        print(f"No measurement CSV files found under {csv_root}")
        return

    changed = False
    for csv_file in csv_files:
        changed = _apply_csv_to_power(power, csv_file) or changed

    if not changed:
        print("No power measurements were updated from the discovered CSV files.")
        return

    save_report(report_path, data)
    print(f"Updated power measurements in {_display_path(report_path)}")
