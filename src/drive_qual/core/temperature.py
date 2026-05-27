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
CHART_WIDTH_PX = 1200
CHART_HEIGHT_PX = 720
CHART_MARGIN_LEFT = 120
CHART_MARGIN_RIGHT = 70
CHART_MARGIN_TOP = 85
CHART_MARGIN_BOTTOM = 105
SPEED_TICK_SMALL_MAX = 100
SPEED_TICK_MEDIUM_MAX = 500
SPEED_TICK_SMALL_STEP = 20
SPEED_TICK_MEDIUM_STEP = 100
SPEED_TICK_LARGE_STEP = 250
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


@dataclass(frozen=True)
class ChartArea:
    left: int
    top: int
    right: int
    bottom: int
    temp_min: int
    temp_max: int
    speed_min: int
    speed_max: int


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


def plot_temperature_chart(
    rows: Iterable[TemperaturePerformanceRow],
    out_path: Path,
    *,
    title: str = "Temperature vs Speed",
) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    series = _chart_series(rows)
    if not any(series.values()):
        raise ValueError("No plottable temperature rows found.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (CHART_WIDTH_PX, CHART_HEIGHT_PX), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    area = _chart_area(series)

    _draw_axes(draw, font=font, area=area)
    _draw_chart_labels(draw, font=font, area=area, title=title)

    colors = {"read": "#1f77b4", "write": "#d62728"}
    labels = {"read": "Read", "write": "Write"}
    for operation in ("read", "write"):
        _draw_series(draw, area=area, points=series[operation], color=colors[operation])

    _draw_legend(draw, font, colors=colors, labels=labels, area=area)
    image.save(out_path)
    return out_path


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
        records = list(csv.DictReader(handle))
    rows = [_row_from_csv(record) for record in records]
    parsed_rows = [row for row in rows if row is not None]
    if parsed_rows:
        return parsed_rows
    return _load_sectioned_temperature_csv(path)


def _row_from_csv(record: dict[str | None, Any]) -> TemperaturePerformanceRow | None:
    normalized = {_normalize_header(key): value for key, value in record.items() if key is not None}
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


def _load_sectioned_temperature_csv(path: Path) -> list[TemperaturePerformanceRow]:
    rows: list[TemperaturePerformanceRow] = []
    operation: str | None = None
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for fields in csv.reader(handle):
            if not fields:
                continue
            first = fields[0].strip()
            first_normalized = first.casefold()
            if first_normalized.startswith("read"):
                operation = "read"
                continue
            if first_normalized.startswith("write"):
                operation = "write"
                continue
            if operation is None or first_normalized in {"temp c", "tempc", "temperaturec"}:
                continue
            temperature_c = _parse_temperature_c(first)
            if temperature_c is None:
                continue
            speed = fields[1] if len(fields) > 1 else None
            rows.append(
                TemperaturePerformanceRow(
                    temperature_c=temperature_c,
                    operation=operation,
                    speed_mb_s=_parse_float(speed),
                )
            )
    return rows


def _safe_filename_component(value: str) -> str:
    return _SAFE_FILENAME_RE.sub("_", value).strip(" ._")


def _chart_series(rows: Iterable[TemperaturePerformanceRow]) -> dict[str, list[tuple[int, float]]]:
    best_by_operation_temp: dict[tuple[str, int], float] = {}
    for row in rows:
        operation = row.operation.casefold()
        if operation not in TEMPERATURE_OPERATION_FIELDS or row.speed_mb_s is None or row.error:
            continue
        best_by_operation_temp[(operation, row.temperature_c)] = row.speed_mb_s

    return {
        operation: sorted(
            [(temp, speed) for (op, temp), speed in best_by_operation_temp.items() if op == operation],
            key=lambda item: item[0],
        )
        for operation in ("read", "write")
    }


def _chart_area(series: dict[str, list[tuple[int, float]]]) -> ChartArea:
    all_points = [point for points in series.values() for point in points]
    temp_min, temp_max = _axis_bounds([temp for temp, _speed in all_points], default=(-40, 80), step=10)
    _speed_min, speed_max = _axis_bounds([speed for _temp, speed in all_points], default=(0, 100), step=100)
    return ChartArea(
        left=CHART_MARGIN_LEFT,
        top=CHART_MARGIN_TOP,
        right=CHART_WIDTH_PX - CHART_MARGIN_RIGHT,
        bottom=CHART_HEIGHT_PX - CHART_MARGIN_BOTTOM,
        temp_min=temp_min,
        temp_max=temp_max,
        speed_min=0,
        speed_max=speed_max,
    )


def _axis_bounds(values: list[float | int], *, default: tuple[int, int], step: int) -> tuple[int, int]:
    if not values:
        return default
    low = int(min(values) // step * step)
    high = int((max(values) + step - 1) // step * step)
    if low == high:
        high = low + step
    return low, high


def _point_to_pixel(
    temp: float,
    speed: float,
    *,
    area: ChartArea,
) -> tuple[int, int]:
    x_ratio = (temp - area.temp_min) / (area.temp_max - area.temp_min)
    y_ratio = (speed - area.speed_min) / (area.speed_max - area.speed_min)
    x = area.left + round(x_ratio * (area.right - area.left))
    y = area.bottom - round(y_ratio * (area.bottom - area.top))
    return x, y


def _draw_axes(
    draw: Any,
    *,
    font: Any,
    area: ChartArea,
) -> None:
    draw.rectangle((area.left, area.top, area.right, area.bottom), outline="#333333", width=2)
    _draw_temperature_ticks(draw, font=font, area=area)
    _draw_speed_ticks(draw, font=font, area=area)


def _draw_temperature_ticks(draw: Any, *, font: Any, area: ChartArea) -> None:
    for temp in range(area.temp_min, area.temp_max + 1, 10):
        x, _ = _point_to_pixel(temp, area.speed_min, area=area)
        draw.line((x, area.top, x, area.bottom), fill="#e5e5e5")
        draw.text((x - 12, area.bottom + 12), str(temp), fill="#333333", font=font)


def _draw_speed_ticks(draw: Any, *, font: Any, area: ChartArea) -> None:
    speed_step = _speed_tick_step(area.speed_max)
    for speed in range(area.speed_min, area.speed_max + 1, speed_step):
        _, y = _point_to_pixel(area.temp_min, speed, area=area)
        draw.line((area.left, y, area.right, y), fill="#e5e5e5")
        draw.text((area.left - 65, y - 6), str(speed), fill="#333333", font=font)


def _draw_chart_labels(draw: Any, *, font: Any, area: ChartArea, title: str) -> None:
    draw.text((area.left, 25), title, fill="#111111", font=font)
    draw.text((area.left, CHART_HEIGHT_PX - 45), "Temperature (C)", fill="#111111", font=font)
    draw.text((20, area.top - 45), "Speed (MB/s)", fill="#111111", font=font)


def _draw_series(draw: Any, *, area: ChartArea, points: list[tuple[int, float]], color: str) -> None:
    if not points:
        return
    pixel_points = [_point_to_pixel(temp, speed, area=area) for temp, speed in points]
    if len(pixel_points) > 1:
        draw.line(pixel_points, fill=color, width=4)
    for x, y in pixel_points:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color, outline=color)


def _speed_tick_step(speed_max: int) -> int:
    if speed_max <= SPEED_TICK_SMALL_MAX:
        return SPEED_TICK_SMALL_STEP
    if speed_max <= SPEED_TICK_MEDIUM_MAX:
        return SPEED_TICK_MEDIUM_STEP
    return SPEED_TICK_LARGE_STEP


def _draw_legend(
    draw: Any,
    font: Any,
    *,
    colors: dict[str, str],
    labels: dict[str, str],
    area: ChartArea,
) -> None:
    x = area.right - 180
    y = area.top + 20
    for operation in ("read", "write"):
        draw.line((x, y + 7, x + 38, y + 7), fill=colors[operation], width=4)
        draw.ellipse((x + 14, y + 2, x + 24, y + 12), fill=colors[operation], outline=colors[operation])
        draw.text((x + 50, y), labels[operation], fill="#111111", font=font)
        y += 28
