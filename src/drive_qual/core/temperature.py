from __future__ import annotations

import csv
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from drive_qual.core.io_utils import mk_dir
from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, localize_windows_path

TEMPERATURE_ARTIFACT_CATEGORY = "Temperature"
TEMPERATURE_CHART_SUFFIX = "Temperature Data.png"
TEMPERATURE_OPERATION_FIELDS = {
    "read": "read_mb_s",
    "write": "write_mb_s",
}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_. -]+")


@dataclass(frozen=True)
class TemperaturePerformanceRow:
    temperature_c: int
    operation: str
    speed_mb_s: float | None
    error: str | None = None


def temperature_artifact_dir(part_number: str) -> Path:
    path = PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, TEMPERATURE_ARTIFACT_CATEGORY)
    local_path = localize_windows_path(Path(str(path)))
    mk_dir(local_path)
    return local_path


def temperature_chart_path(part_number: str, dut_name: str) -> Path:
    safe_dut = _safe_filename_component(dut_name) or "DUT"
    return temperature_artifact_dir(part_number) / f"{safe_dut} {TEMPERATURE_CHART_SUFFIX}"


def copy_temperature_chart(source: Path, *, part_number: str, dut_name: str) -> Path:
    destination = temperature_chart_path(part_number, dut_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def update_temperature_performance(
    data: dict[str, Any],
    dut_name: str,
    rows: Iterable[TemperaturePerformanceRow],
) -> None:
    temperature = data.setdefault("temperature", {})
    if not isinstance(temperature, dict):
        raise ValueError("Invalid 'temperature' section; expected object.")

    dut_temperature = temperature.setdefault(dut_name, {})
    if not isinstance(dut_temperature, dict):
        dut_temperature = {}
        temperature[dut_name] = dut_temperature

    performance = dut_temperature.setdefault("performance", {})
    if not isinstance(performance, dict):
        performance = {}
        dut_temperature["performance"] = performance

    for row in rows:
        operation_key = TEMPERATURE_OPERATION_FIELDS.get(row.operation.casefold())
        if operation_key is None:
            continue
        temp_key = f"{row.temperature_c}c"
        entry = performance.setdefault(temp_key, {"read_mb_s": None, "write_mb_s": None})
        if not isinstance(entry, dict):
            entry = {"read_mb_s": None, "write_mb_s": None}
            performance[temp_key] = entry
        entry[operation_key] = row.speed_mb_s
        if row.error:
            entry["error"] = row.error


def load_temperature_performance_csv(path: Path) -> list[TemperaturePerformanceRow]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = [_row_from_csv(record) for record in reader]
    return [row for row in rows if row is not None]


def _row_from_csv(record: dict[str, str]) -> TemperaturePerformanceRow | None:
    normalized = {_normalize_header(key): value for key, value in record.items()}
    operation = _first_value(normalized, ("operation", "op"))
    if operation is None:
        return None

    temperature = _first_value(
        normalized,
        ("temproundedc", "temprounded", "temperaturec", "tempc", "tempactual", "temp1"),
    )
    speed = _first_value(normalized, ("speedmib", "speedmeanmib", "speedmedianmib", "speedmbs", "mbs"))
    error = _first_value(normalized, ("error", "failure", "error_excerpt"))

    temperature_c = _parse_temperature_c(temperature)
    if temperature_c is None:
        return None

    return TemperaturePerformanceRow(
        temperature_c=temperature_c,
        operation=operation.strip().casefold(),
        speed_mb_s=_parse_float(speed),
        error=error.strip() if isinstance(error, str) and error.strip() else None,
    )


def _parse_temperature_c(value: str | None) -> int | None:
    numeric = _parse_float(value)
    if numeric is None:
        return None
    return int(round(numeric))


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if match is None:
        return None
    return float(match.group(0))


def _first_value(record: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = record.get(name)
        if value is not None:
            return value
    return None


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _safe_filename_component(value: str) -> str:
    return _SAFE_FILENAME_RE.sub("_", value).strip(" ._")
