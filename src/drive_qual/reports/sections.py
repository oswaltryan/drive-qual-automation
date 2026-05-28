from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from drive_qual.reports.constants import (
    COMPATIBILITY_ROWS,
    INRUSH_WARN_MA,
    MA_PER_A,
    MAX_IO_RMS_FAIL_MA,
    MAX_IO_RMS_WARN_MA,
    OS_COLUMNS,
    POWER_ROWS,
    TEMP_RE,
    TEMPERATURE_TABLE_POINTS_C,
    TWO_SECTION_COUNT,
)
from drive_qual.reports.docx_shared import (
    _add_heading,
    _center_cell_paragraphs,
    _center_table_columns,
    _field,
    _format_value,
    _join_present,
    _list_line,
    _table,
    _to_float,
)
from drive_qual.reports.embedded import _add_embedded_package_to_paragraph
from drive_qual.reports.evaluation import EvaluatedReport, Status


def _add_revision_table(document: Any) -> None:
    table = _table(document, ["Revision", "Name", "Date", "Description"])
    row_0 = table.add_row().cells
    row_0[0].text = "1"
    row_0[1].text = "Alex Klein"
    row_0[2].text = "3/20/2025"
    row_0[3].text = "Initial Draft"
    row_1 = table.add_row().cells
    row_1[0].text = "2"
    row_1[1].text = "Ryan Oswalt"
    row_1[2].text = "4/29/2026"
    row_1[3].text = "Automation"


def _add_drive_info(document: Any, drive_info: object, report_path: Path) -> None:
    _add_heading(document, "Drive Info", level=2)
    fields = (
        ("apricorn_part_number", "Apricorn Part Number", report_path.parent.name),
        ("manufacturer", "Manufacturer", ""),
        ("manufacturer_part_number", "Manufacturer Part Number", ""),
        ("serial_number", "Serial Number", ""),
        ("capacity", "Capacity", ""),
        ("firmware", "Firmware", ""),
        ("form_factor", "Form Factor", ""),
        ("interface", "Interface", ""),
        ("technology", "Technology", ""),
    )
    for key, label, fallback in fields:
        _list_line(document, f"{label}: {_field(drive_info, key) or fallback}")


def _add_qualification_equipment(document: Any, equipment: object) -> None:
    _add_heading(document, "Qualification Equipment", level=2)
    if not isinstance(equipment, dict):
        _list_line(document, "No equipment data recorded.")
        return
    _host_lines(document, equipment)
    _scope_lines(document, equipment)


def _host_lines(document: Any, equipment: dict[str, Any]) -> None:
    for key, label in (
        ("windows_host", "Windows Host"),
        ("usb_if_host", "Windows Host"),
        ("linux_host", "Linux Host"),
        ("macos_host", "macOS Host"),
    ):
        host = equipment.get(key)
        if not isinstance(host, dict):
            continue
        _list_line(document, f"{label}: {_join_present(host.get('hardware'), host.get('os_version'))}")
        for software in _software_entries(host.get("software")):
            _list_line(document, f"{software}", level=2)


def _scope_lines(document: Any, equipment: dict[str, Any]) -> None:
    scope = equipment.get("scope")
    if isinstance(scope, dict):
        _list_line(document, f"Measuring Device: {_field(scope, 'model')}")
        _list_line(document, f"Serial Number: {_field(scope, 'serial_number')}", level=1)
        _list_line(document, f"Version: {_field(scope, 'version')}", level=1)
    _probe_line(document, equipment.get("probe_current"), "Current")
    _probe_line(document, equipment.get("probe_voltage"), "Voltage")


def _probe_line(document: Any, probe: object, role: str) -> None:
    if not isinstance(probe, dict):
        return
    channel = _field(probe, "channel")
    channel_text = f" - Channel {channel}" if channel else ""
    _list_line(document, f"Probe Type: {_field(probe, 'model')}{channel_text} ({role})", level=1)
    _list_line(document, f"Serial Number: {_field(probe, 'serial_number')}", level=2)


def _add_power_data(document: Any, power: object, shade_cell: Callable[[Any, Status], None]) -> None:
    _add_heading(document, "Power Data", level=2)
    table = _table(document, ["Test", "Linux", "macOS", "Windows"])
    for label, fields in POWER_ROWS:
        row = table.add_row().cells
        row[0].text = label
        for index, (os_key, _display) in enumerate(OS_COLUMNS, start=1):
            value, dut_name = _max_power_value(power, fields, os_key)
            row[index].text = _format_power_value(value, dut_name)
            shade_cell(row[index], _power_status(label, value))
    _center_table_columns(table, range(1, 4))


def _add_compatibility_data(document: Any, compatibility: object, shade_cell: Callable[[Any, Status], None]) -> None:
    _add_heading(document, "Compatibility Data", level=2)
    table = _table(document, ["Test", "Linux", "macOS", "Windows"])
    for key, label in COMPATIBILITY_ROWS:
        row = table.add_row().cells
        row[0].text = label
        for index, (os_key, _display) in enumerate(OS_COLUMNS, start=1):
            status = _compatibility_status(compatibility, key, os_key)
            row[index].text = _status_text(status)
            shade_cell(row[index], status)
    _center_table_columns(table, range(1, 4))


def _add_temperature_data(
    document: Any,
    temperature: object,
    part_root: Path,
    shade_cell: Callable[[Any, Status], None],
    inches: Any,
) -> None:
    _add_heading(document, "Temperature Data", level=2)
    if not isinstance(temperature, dict) or not temperature:
        _add_temperature_table(document, part_root, "", {}, shade_cell, inches)
        return
    sections = _temperature_sections(temperature)
    if not sections:
        _add_temperature_table(document, part_root, "", {}, shade_cell, inches)
        return
    for dut_name, dut_data in sections:
        if len(sections) > 1:
            document.add_paragraph(str(dut_name))
        _add_temperature_table(
            document, part_root, str(dut_name), _temperature_row_lookup(dut_data), shade_cell, inches
        )


def _add_temperature_table(
    document: Any,
    part_root: Path,
    dut_name: str,
    values_by_temp: dict[int, dict[str, Any]],
    shade_cell: Callable[[Any, Status], None],
    inches: Any,
) -> None:
    table = _table(document, ["Chart", "Temperature", "Read MB/s", "Write MB/s"])
    temperature_artifact = _matching_temperature_artifact(part_root, dut_name)
    for temp_c in TEMPERATURE_TABLE_POINTS_C:
        values = values_by_temp.get(temp_c, {})
        row = table.add_row().cells
        row[1].text = f"{temp_c}\u00b0C"
        _set_temperature_cell(row[2], values.get("read_mb_s"), values.get("error"), shade_cell)
        _set_temperature_cell(row[3], values.get("write_mb_s"), values.get("error"), shade_cell)
    merged_cell = table.rows[1].cells[0].merge(table.rows[-1].cells[0])
    merged_cell.text = ""
    if temperature_artifact is not None:
        chart_paragraph = merged_cell.paragraphs[0]
        for _ in range(3):
            chart_paragraph.add_run().add_break()
        _add_embedded_package_to_paragraph(chart_paragraph, temperature_artifact, width=inches(1.7))
    _center_cell_paragraphs(merged_cell)
    _center_table_columns(table, range(0, 4))


def _matching_temperature_artifact(part_root: Path, dut_name: str) -> Path | None:
    if not part_root.exists():
        return None
    normalized_dut = _normalized_match_text(dut_name)
    candidates = [
        artifact
        for artifact in part_root.rglob("*.png")
        if not artifact.name.startswith("._") and "temperature" in _normalized_match_text(artifact.stem)
    ]
    if normalized_dut:
        matching = [artifact for artifact in candidates if normalized_dut in _normalized_match_text(artifact.stem)]
        if matching:
            return sorted(matching)[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _normalized_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _add_disk_performance(document: Any, performance: object) -> None:
    _add_heading(document, "Disk Performance", level=2)
    table = _table(document, ["DUT", "CDM-R", "CDM-W", "BM(R)", "BM(W)", "ATTO-R", "ATTO-W"])
    if not isinstance(performance, dict):
        return
    for dut_name, platforms in performance.items():
        row = table.add_row().cells
        row[0].text = str(dut_name)
        row[1].text = _performance_field(platforms, "Windows", "CrystalDiskMark", "read")
        row[2].text = _performance_field(platforms, "Windows", "CrystalDiskMark", "write")
        row[3].text = _performance_field(platforms, "macOS", "Blackmagic Disk Speed Test", "read")
        row[4].text = _performance_field(platforms, "macOS", "Blackmagic Disk Speed Test", "write")
        row[5].text = _performance_field(platforms, "Windows", "ATTO", "read")
        row[6].text = _performance_field(platforms, "Windows", "ATTO", "write")
    _center_table_columns(table, range(1, 7))


def _add_compliance(document: Any, compliance: object, shade_cell: Callable[[Any, Status], None]) -> None:
    _add_heading(document, "Compliance/Reliability Test", level=2)
    table = _table(document, ["Program", "Iterations/Loops", "Result"])
    _compliance_row(
        table,
        shade_cell,
        "USB-IF Mass Storage Compliance",
        _field(compliance, "usb_if_msc_iterations"),
        _raw_field(compliance, "usb_if_msc_result"),
    )
    _compliance_row(
        table,
        shade_cell,
        "Reliability Test",
        _field(compliance, "disk_tester_reliability_iterations"),
        _raw_field(compliance, "disk_tester_reliability_result"),
    )
    _center_table_columns(table, range(1, 3))


def _add_executive_summary(document: Any, evaluated: EvaluatedReport) -> None:
    _add_heading(document, "Executive Summary", level=2)
    _add_review_sections_summary(document, evaluated.review_sections)


def _software_entries(software: object) -> list[str]:
    if not isinstance(software, list):
        return []
    entries: list[str] = []
    for item in software:
        if not isinstance(item, dict):
            continue
        name = _field(item, "name")
        version = _field(item, "version")
        entries.append(f"{name}, v{version}" if version else name)
    return entries


def _max_power_value(power: object, fields: tuple[str, ...], os_key: str) -> tuple[float | None, str | None]:
    if not isinstance(power, dict):
        return None, None
    best_value: float | None = None
    best_dut: str | None = None
    for dut_name, dut_fields in power.items():
        if not isinstance(dut_fields, dict):
            continue
        for field in fields:
            slot = dut_fields.get(field)
            if not isinstance(slot, dict):
                continue
            value = _to_float(slot.get(os_key))
            if value is not None and (best_value is None or value > best_value):
                best_value = value
                best_dut = str(dut_name)
    return best_value, best_dut


def _power_status(label: str, value: float | None) -> Status:
    if value is None:
        return Status.MISSING
    if label.startswith("RMS"):
        if value >= MAX_IO_RMS_FAIL_MA:
            return Status.FAIL
        if value >= MAX_IO_RMS_WARN_MA:
            return Status.WARN
    if label.startswith("Max in-rush") and value > INRUSH_WARN_MA:
        return Status.WARN
    return Status.PASS


def _format_power_value(value: float | None, dut_name: str | None) -> str:
    if value is None:
        return ""
    text = f"{value / MA_PER_A:.2f} A" if value >= MA_PER_A else f"{value:.2f} mA"
    if dut_name:
        return f"{text} ({dut_name})"
    return text


def _compatibility_status(compatibility: object, key: str, os_key: str) -> Status:
    if not isinstance(compatibility, dict):
        return Status.MISSING
    slot = compatibility.get(key)
    if not isinstance(slot, dict):
        return Status.MISSING
    value = slot.get(os_key)
    if value is True:
        return Status.PASS
    if value is False:
        return Status.FAIL
    return Status.MISSING


def _status_text(status: Status) -> str:
    if status == Status.PASS:
        return "Pass"
    if status == Status.FAIL:
        return "Fail"
    return ""


def _temperature_sections(temperature: dict[Any, Any]) -> list[tuple[str, dict[str, Any]]]:
    sections: list[tuple[str, dict[str, Any]]] = []
    for dut_name, dut_data in temperature.items():
        if not isinstance(dut_data, dict):
            continue
        rows = _temperature_rows(dut_data)
        if any(_has_temperature_value(row_values) for _temp, row_values in rows):
            sections.append((str(dut_name), dut_data))
    return sections


def _temperature_rows(dut_data: object) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(dut_data, dict):
        return []
    performance = dut_data.get("performance")
    if not isinstance(performance, dict):
        return []
    rows: list[tuple[str, dict[str, Any]]] = []
    for temp_label, values in performance.items():
        if isinstance(values, dict):
            rows.append((str(temp_label), values))
    return sorted(rows, key=lambda item: _temperature_sort_key(item[0]))


def _temperature_row_lookup(dut_data: object) -> dict[int, dict[str, Any]]:
    lookup: dict[int, dict[str, Any]] = {}
    for temp_label, values in _temperature_rows(dut_data):
        temp_c = _temperature_int(temp_label)
        if temp_c is not None:
            lookup[temp_c] = values
    return lookup


def _has_temperature_value(values: dict[str, Any]) -> bool:
    return any(values.get(key) is not None for key in ("read_mb_s", "write_mb_s")) or bool(values.get("error"))


def _set_temperature_cell(cell: Any, value: object, error: object, shade_cell: Callable[[Any, Status], None]) -> None:
    if error:
        cell.text = str(error)
        shade_cell(cell, Status.FAIL)
        return
    cell.text = _format_value(value)
    numeric = _to_float(value)
    if numeric == 0:
        shade_cell(cell, Status.FAIL)
    elif numeric is None:
        shade_cell(cell, Status.MISSING)


def _temperature_sort_key(value: str) -> float:
    match = TEMP_RE.search(value)
    if match is None:
        return float("inf")
    return float(match.group("value"))


def _temperature_int(value: str) -> int | None:
    numeric = _temperature_sort_key(value)
    if numeric == float("inf") or not numeric.is_integer():
        return None
    return int(numeric)


def _format_temperature_label(value: str) -> str:
    match = TEMP_RE.search(value)
    if match is None:
        return value
    numeric = float(match.group("value"))
    label = str(int(numeric)) if numeric.is_integer() else str(numeric)
    return f"{label}Ãƒâ€šÃ‚Â°C"


def _performance_field(platforms: object, os_name: str, tool_name: str, field: str) -> str:
    if not isinstance(platforms, dict):
        return ""
    os_data = platforms.get(os_name)
    if not isinstance(os_data, dict):
        return ""
    tool_data = os_data.get(tool_name)
    if not isinstance(tool_data, dict):
        return ""
    return _format_value(tool_data.get(field))


def _raw_field(data: object, key: str) -> object:
    if not isinstance(data, dict):
        return None
    return data.get(key)


def _compliance_row(
    table: Any, shade_cell: Callable[[Any, Status], None], program: str, iterations: str, result: object
) -> None:
    row = table.add_row().cells
    row[0].text = program
    row[1].text = iterations
    row[2].text = _format_result(result)
    shade_cell(row[2], _result_status(result))


def _format_result(result: object) -> str:
    if result is True:
        return "Pass"
    if result is False:
        return "Fail"
    return str(result or "")


def _result_status(result: object) -> Status:
    lowered = _format_result(result).casefold()
    if lowered == "pass":
        return Status.PASS
    if lowered == "fail":
        return Status.FAIL
    return Status.MISSING


def _add_review_sections_summary(document: Any, review_sections: list[str]) -> None:
    paragraph = document.add_paragraph()
    if not review_sections:
        paragraph.add_run("No sections require review.")
        return
    paragraph.add_run("Results require review in sections: ")
    for index, section in enumerate(review_sections):
        if index > 0:
            paragraph.add_run(_section_list_separator(index, len(review_sections)))
        run = paragraph.add_run(section)
        run.bold = True
    paragraph.add_run(".")


def _section_list_separator(index: int, count: int) -> str:
    if count == TWO_SECTION_COUNT:
        return " and "
    if index == count - 1:
        return ", and "
    return ", "
