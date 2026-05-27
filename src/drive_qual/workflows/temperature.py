from __future__ import annotations

from pathlib import Path
from typing import Any

from drive_qual.core.dut_selection import select_report_dut_name
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.temperature import (
    copy_temperature_chart,
    load_temperature_performance_csv,
    update_temperature_performance,
)


def _prompt_path(label: str, *, required: bool) -> Path | None:
    response = input(f"{label}: ").strip().strip('"')
    if not response:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    return Path(response)


def _part_number_from_report(data: dict[str, Any], fallback: str) -> str:
    drive_info = data.get("drive_info")
    if isinstance(drive_info, dict):
        value = drive_info.get("apricorn_part_number")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def post_process_temperature_data(
    *,
    part_number: str | None = None,
    dut_name: str | None = None,
    performance_csv: Path | None = None,
    chart: Path | None = None,
) -> Path:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    resolved_dut_name = dut_name or select_report_dut_name(report_path)
    actual_part_number = _part_number_from_report(data, folder_name)

    if performance_csv is not None:
        rows = load_temperature_performance_csv(performance_csv)
        update_temperature_performance(data, resolved_dut_name, rows)

    if chart is not None:
        copied_chart = copy_temperature_chart(chart, part_number=actual_part_number, dut_name=resolved_dut_name)
        print(f"Saved temperature chart to: {copied_chart}")

    save_report(report_path, data)
    print(f"Updated temperature data in {report_path}")
    return report_path


def run_temperature_step(part_number: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    dut_name = select_report_dut_name(report_path)

    print("Temperature post-processing uses a CSV of matched temperature/performance rows.")
    print("Leave paths blank to skip until temperature artifacts are ready.")
    performance_csv = _prompt_path("Temperature performance CSV path", required=False)
    chart = _prompt_path("Temperature chart PNG path", required=False)
    if performance_csv is None and chart is None:
        print("No temperature inputs provided; leaving report unchanged.")
        return

    post_process_temperature_data(
        part_number=folder_name,
        dut_name=dut_name,
        performance_csv=performance_csv,
        chart=chart,
    )
