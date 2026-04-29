from __future__ import annotations

import argparse
import csv
import io
import json
import re
import struct
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from drive_qual.core.report_session import TEMPLATE_NAME, report_path_for, resolve_folder_name
from drive_qual.core.storage_paths import localize_windows_path
from drive_qual.reports.evaluation import EvaluatedReport, Status, evaluate_report

DEFAULT_OUTPUT_NAME = "drive_qualification_report.docx"
OS_COLUMNS = (("linux", "Linux"), ("macos", "MacOS"), ("windows", "Windows"))
MA_PER_A = 1000.0
MAX_IO_RMS_FAIL_MA = 1000.0
MAX_IO_RMS_WARN_MA = 900.0
INRUSH_WARN_MA = 900.0
APPENDIX_IMAGE_WIDTH_INCHES = 5.7
APPENDIX_OS_LABEL_WIDTH_INCHES = 1.18
APPENDIX_OS_ARTIFACT_WIDTH_INCHES = 6.12
APPENDIX_MEASUREMENT_COLUMN_WIDTH_FRACTION = 0.97
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
MEASUREMENT_LABELS = {"Inrush Summary", "Max IO Summary"}
PERFORMANCE_LABEL = "Performance"
EXCLUDED_ACCUM_FIELDS = {"Accum-Pk-Pk", "Accum-Std Dev", "Accum-Population"}
EXCLUDED_MEASUREMENT_ROWS = {"Meas9"}
CSV_ENCODING_CANDIDATES = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
KEY_VALUE_CSV_ROW_WIDTH = 2
LINUX_DISKS_SUMMARY_COLUMN_COUNT = 3
TEMPERATURE_TABLE_POINTS_C = tuple(range(-40, 61, 10))
EMU_PER_TWIP = 635
OBJECT_ICON_WIDTH_INCHES = 0.72
WINDOWS_PERFORMANCE_BLANK_LINES_BEFORE_FIRST_OBJECT = 10
WINDOWS_PERFORMANCE_BLANK_LINES_BETWEEN_OBJECTS = 13
CFB_SECTOR_SIZE = 512
CFB_MINI_SECTOR_SIZE = 64
CFB_MINI_STREAM_CUTOFF = 4096
CFB_END_OF_CHAIN = -2
CFB_FREE_SECTOR = -1
CFB_FAT_SECTOR = -3
CFB_NO_STREAM = -1
OLE_MARKER_BYTES = b"\x01\x00\x00\x02" + (b"\x00" * 16)
PACKAGE_CLSID = bytes.fromhex("0c00030000000000c000000000000046")
STATUS_COLORS = {
    Status.PASS: "C6EFCE",
    Status.WARN: "FFEB9C",
    Status.FAIL: "FFC7CE",
    Status.MISSING: "D9EAF7",
    Status.NOT_APPLICABLE: "E7E6E6",
}
COMPATIBILITY_ROWS = (
    ("recognized_by_os", "Recognized by OS"),
    ("hot_pluggable", "Hot Pluggable"),
    ("safely_remove", "Safely Remove"),
    ("device_manager_disk_mgmt", "Native Disk Utility"),
    ("partition_drive", "Partition Drive"),
    ("format_drive", "Format Drive"),
    ("copy_to_drive", "Copy to Drive"),
    ("copy_from_drive", "Copy from Drive"),
    ("delete_data", "Delete Data"),
)
POWER_ROWS = (
    ("Max in-rush current", ("max_inrush_current", "max_inrush_current_5v", "max_inrush_current_12v")),
    ("Max read/write current", ("max_read_write_current", "max_read_write_current_5v", "max_read_write_current_12v")),
    (
        "RMS during read/write test",
        ("rms_read_write_current", "rms_read_write_current_5v", "rms_read_write_current_12v"),
    ),
)
TEMP_RE = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)\s*c", re.IGNORECASE)


def generate_report_docx(
    *,
    part_number: str | None = None,
    source_root: Path | None = None,
    output: Path | None = None,
) -> Path:
    folder_name = resolve_folder_name(part_number)
    report_path = resolve_report_path(folder_name, source_root)
    data = load_source_report(report_path)
    evaluated = evaluate_report(data)
    output_path = resolve_output_path(folder_name, source_root, output)
    write_docx_report(data, evaluated, report_path, output_path)
    return output_path


def resolve_report_path(folder_name: str, source_root: Path | None) -> Path:
    if source_root is None:
        return localize_windows_path(report_path_for(folder_name))
    return source_root / folder_name / TEMPLATE_NAME


def resolve_output_path(folder_name: str, source_root: Path | None, output: Path | None) -> Path:
    if output is not None:
        return output
    if source_root is not None:
        return source_root / folder_name / DEFAULT_OUTPUT_NAME
    return localize_windows_path(report_path_for(folder_name)).with_name(DEFAULT_OUTPUT_NAME)


def load_source_report(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        raise FileNotFoundError(f"Report JSON not found at {report_path}.")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Report JSON is not an object.")
    return data


def write_docx_report(
    data: dict[str, Any],
    evaluated: EvaluatedReport,
    report_path: Path,
    output_path: Path,
) -> None:
    Document, Inches, shade_cell = _load_docx_tools()
    document = Document()
    _set_margins(document, Inches)

    document.add_heading("Drive Qualification Report", level=1)
    _add_revision_table(document)
    _add_executive_summary(document, evaluated)
    _add_drive_info(document, data.get("drive_info"), report_path)
    _add_qualification_equipment(document, data.get("equipment"))

    document.add_page_break()
    document.add_heading("Test Results", level=1)
    _add_power_data(document, data.get("power"), shade_cell)
    _add_compatibility_data(document, data.get("compatibility"), shade_cell)
    _add_disk_performance(document, data.get("performance"))
    _add_compliance(document, data.get("compliance"), shade_cell)
    document.add_page_break()
    _add_temperature_data(document, data.get("temperature"), report_path.parent, shade_cell, Inches)
    document.add_page_break()
    _add_appendix(document, data, report_path.parent, Inches)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)


def _load_docx_tools() -> tuple[Any, Any, Callable[[Any, Status], None]]:
    try:
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches
    except ImportError as exc:
        raise RuntimeError(
            "Word report generation requires python-docx. Install project dependencies with `uv sync`."
        ) from exc

    def shade_cell(cell: Any, status: Status) -> None:
        tc_pr = cell._tc.get_or_add_tcPr()
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), STATUS_COLORS[status])
        tc_pr.append(shading)

    return Document, Inches, shade_cell


def _set_margins(document: Any, inches: Any) -> None:
    for section in document.sections:
        section.left_margin = inches(0.6)
        section.right_margin = inches(0.6)
        section.top_margin = inches(0.5)
        section.bottom_margin = inches(0.5)


def _add_revision_table(document: Any) -> None:
    table = _table(document, ["Revision", "Name", "Date", "Description"])
    row = table.add_row().cells
    row[3].text = "Initial Draft"
    table.add_row()


def _add_drive_info(document: Any, drive_info: object, report_path: Path) -> None:
    document.add_heading("Drive Info", level=2)
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
    document.add_heading("Qualification Equipment", level=2)
    if not isinstance(equipment, dict):
        _list_line(document, "No equipment data recorded.")
        return
    _host_lines(document, equipment)
    _scope_lines(document, equipment)
    _dut_lines(document, equipment.get("dut"))


def _host_lines(document: Any, equipment: dict[str, Any]) -> None:
    for key, label in (
        ("windows_host", "Windows Host"),
        ("usb_if_host", "Windows Host"),
        ("linux_host", "Linux Host"),
        ("macos_host", "MacOS Host"),
    ):
        host = equipment.get(key)
        if not isinstance(host, dict):
            continue
        _list_line(document, f"{label}: {_join_present(host.get('hardware'), host.get('os_version'))}")
        if _software_entries is not None:
            _list_line(document, "Software:", level=1)
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


def _dut_lines(document: Any, dut_data: object) -> None:
    _list_line(document, "Device Under Test (DUT):")
    if not isinstance(dut_data, dict) or not dut_data:
        _list_line(document, "No DUT data recorded.")
        return
    for dut_name, binding in dut_data.items():
        _list_line(document, str(dut_name), level=1)
        serial = _field(binding, "serial_number") if isinstance(binding, dict) else ""
        if serial:
            _list_line(document, f"Serial Number: {serial}", level=2)


def _add_power_data(document: Any, power: object, shade_cell: Callable[[Any, Status], None]) -> None:
    document.add_heading("Power Data", level=2)
    table = _table(document, ["Test", "Linux", "MacOS", "Windows"])
    for label, fields in POWER_ROWS:
        row = table.add_row().cells
        row[0].text = label
        for index, (os_key, _display) in enumerate(OS_COLUMNS, start=1):
            value, dut_name = _max_power_value(power, fields, os_key)
            row[index].text = _format_power_value(value, dut_name)
            shade_cell(row[index], _power_status(label, value))
    _center_table_columns(table, range(1, 4))


def _add_compatibility_data(document: Any, compatibility: object, shade_cell: Callable[[Any, Status], None]) -> None:
    document.add_heading("Compatibility Data", level=2)
    table = _table(document, ["Test", "Linux", "MacOS", "Windows"])
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
    document.add_heading("Temperature Data", level=2)
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
        _add_picture_to_paragraph(merged_cell.paragraphs[0], temperature_artifact, width=inches(1.7))
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
    document.add_heading("Disk Performance", level=2)
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
    document.add_heading("Compliance/Reliability Test", level=2)
    table = _table(document, ["Program", "Iterations/Loops", "Result"])
    _compliance_row(
        table,
        shade_cell,
        "USB-IF Mass Storage Compliance",
        _field(compliance, "usb_if_msc_iterations"),
        _field(compliance, "usb_if_msc_result"),
    )
    _compliance_row(
        table,
        shade_cell,
        "Reliability Test",
        _field(compliance, "disk_tester_reliability_iterations"),
        _field(compliance, "disk_tester_reliability_result"),
    )
    _center_table_columns(table, range(1, 3))


def _add_executive_summary(document: Any, evaluated: EvaluatedReport) -> None:
    document.add_heading("Executive Summary", level=2)
    document.add_paragraph(_result_sentence(evaluated))


def _add_appendix(document: Any, data: dict[str, Any], part_root: Path, inches: Any) -> None:
    duts = _report_duts(data)
    for dut_name in duts:
        document.add_heading(f"Disk Performance Raw Data & Measurements ({dut_name})", level=2)
        for os_name in ("Windows", "Linux", "MAC"):
            _add_platform_artifact_table(document, part_root, dut_name, os_name, inches)
            document.add_paragraph("")


def _add_platform_artifact_table(document: Any, part_root: Path, dut_name: str, os_name: str, inches: Any) -> None:
    table = _table(document, [os_name, ""])
    for label in ("Inrush Summary", "Max IO Summary", "Performance"):
        row = table.add_row().cells
        row[0].text = _appendix_row_label(label)
        if label in MEASUREMENT_LABELS:
            _add_measurement_artifacts_to_row(row, part_root, dut_name, os_name, label, inches)
        elif label == PERFORMANCE_LABEL:
            _add_performance_artifacts_to_row(row, part_root, dut_name, os_name, label, inches)
        else:
            _add_matching_artifacts_to_cell(row[1], part_root, dut_name, os_name, label, inches)
    if os_name == "Windows":
        row = table.add_row().cells
        row[0].text = "Drive Information"
        _add_drive_information_artifacts_to_row(row, part_root, dut_name, os_name, "Drive Information", inches)
    _center_table_column(table, 0)
    _set_table_column_widths(table, [inches(APPENDIX_OS_LABEL_WIDTH_INCHES), inches(APPENDIX_OS_ARTIFACT_WIDTH_INCHES)])


def _appendix_row_label(label: str) -> str:
    if label in MEASUREMENT_LABELS:
        return label.removesuffix(" Summary")
    return label


def _table(document: Any, headers: Iterable[str]) -> Any:
    header_list = list(headers)
    table = document.add_table(rows=1, cols=len(header_list))
    table.style = "Table Grid"
    for cell, header in zip(table.rows[0].cells, header_list, strict=True):
        cell.text = header
    return table


def _set_table_column_widths(table: Any, widths: list[Any]) -> None:
    OxmlElement, qn = _load_docx_xml_tools()
    table.autofit = False
    _set_table_preferred_width(table, sum(widths), OxmlElement, qn)
    _set_table_grid(table, widths, OxmlElement, qn)
    for row in table.rows:
        for index, width in enumerate(widths):
            row.cells[index].width = width
            _set_cell_preferred_width(row.cells[index], width, OxmlElement, qn)


def _load_docx_xml_tools() -> tuple[Any, Any]:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    return OxmlElement, qn


def _set_table_preferred_width(table: Any, width: Any, oxml_element: Any, qn: Any) -> None:
    tbl_pr = table._tbl.tblPr
    tbl_width = tbl_pr.find(qn("w:tblW"))
    if tbl_width is None:
        tbl_width = oxml_element("w:tblW")
        tbl_pr.append(tbl_width)
    tbl_width.set(qn("w:type"), "dxa")
    tbl_width.set(qn("w:w"), str(_twips(width)))


def _set_table_grid(table: Any, widths: list[Any], oxml_element: Any, qn: Any) -> None:
    tbl = table._tbl
    existing_grid = tbl.find(qn("w:tblGrid"))
    if existing_grid is not None:
        tbl.remove(existing_grid)
    tbl_grid = oxml_element("w:tblGrid")
    for width in widths:
        grid_col = oxml_element("w:gridCol")
        grid_col.set(qn("w:w"), str(_twips(width)))
        tbl_grid.append(grid_col)
    tbl.insert(1, tbl_grid)


def _set_cell_preferred_width(cell: Any, width: Any, oxml_element: Any, qn: Any) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_width = tc_pr.find(qn("w:tcW"))
    if tc_width is None:
        tc_width = oxml_element("w:tcW")
        tc_pr.append(tc_width)
    tc_width.set(qn("w:type"), "dxa")
    tc_width.set(qn("w:w"), str(_twips(width)))


def _twips(width: Any) -> int:
    return max(int(int(width) / EMU_PER_TWIP), 1)


def _add_matching_artifacts_to_cell(
    cell: Any, part_root: Path, dut_name: str, os_name: str, label: str, inches: Any
) -> None:
    artifacts = _matching_artifacts(part_root, dut_name, os_name, label)
    image_artifacts = _image_artifacts(artifacts)
    if image_artifacts:
        measurement_csvs = _measurement_csvs(artifacts) if label in MEASUREMENT_LABELS else []
        if label in MEASUREMENT_LABELS:
            _add_artifact_objects_to_cell(cell, image_artifacts, inches)
        else:
            _add_artifact_images_to_cell(
                cell,
                image_artifacts,
                measurement_csvs,
                width=inches(APPENDIX_IMAGE_WIDTH_INCHES),
                measurement_table_width=inches(APPENDIX_OS_ARTIFACT_WIDTH_INCHES),
            )
        return
    cell.text = _artifact_names(part_root, artifacts)


def _add_measurement_artifacts_to_row(
    row_cells: Any,
    part_root: Path,
    dut_name: str,
    os_name: str,
    label: str,
    inches: Any,
) -> None:
    label_cell = row_cells[0]
    artifact_cell = row_cells[1]
    artifacts = _matching_artifacts(part_root, dut_name, os_name, label)
    image_artifacts = _image_artifacts(artifacts)
    measurement_csvs = _measurement_csvs(artifacts)
    if not image_artifacts:
        artifact_cell.text = _artifact_names(part_root, artifacts)
        return
    _add_artifact_objects_to_cell(label_cell, image_artifacts, inches)
    _center_cell_paragraphs(label_cell)
    _add_measurement_summaries_to_cell(
        artifact_cell,
        image_artifacts,
        measurement_csvs,
        measurement_table_width=inches(APPENDIX_OS_ARTIFACT_WIDTH_INCHES),
    )


def _add_performance_artifacts_to_row(
    row_cells: Any,
    part_root: Path,
    dut_name: str,
    os_name: str,
    label: str,
    inches: Any,
) -> None:
    label_cell = row_cells[0]
    artifact_cell = row_cells[1]
    artifacts = _matching_artifacts(part_root, dut_name, os_name, label)
    image_artifacts = _image_artifacts(artifacts)
    performance_csvs = _measurement_csvs(artifacts)
    if not image_artifacts:
        artifact_cell.text = _artifact_names(part_root, artifacts)
        return
    sorted_images = _sorted_performance_images(image_artifacts) if os_name == "Windows" else image_artifacts
    if os_name == "Windows":
        _add_windows_performance_objects_to_cell(label_cell, sorted_images, inches)
    else:
        _add_artifact_objects_to_cell(label_cell, sorted_images, inches)
    _add_csv_tables_to_cell(
        artifact_cell,
        sorted_images,
        performance_csvs,
        table_width=inches(APPENDIX_OS_ARTIFACT_WIDTH_INCHES),
    )


def _add_drive_information_artifacts_to_row(
    row_cells: Any,
    part_root: Path,
    dut_name: str,
    os_name: str,
    label: str,
    inches: Any,
) -> None:
    label_cell = row_cells[0]
    artifact_cell = row_cells[1]
    artifacts = _matching_artifacts(part_root, dut_name, os_name, label)
    image_artifacts = _image_artifacts(artifacts)
    if not image_artifacts:
        artifact_cell.text = _artifact_names(part_root, artifacts)
        return
    _add_artifact_objects_to_cell(label_cell, image_artifacts, inches)
    artifact_cell.text = _artifact_names(part_root, _non_image_artifacts(artifacts))


def _add_artifact_images_to_cell(
    cell: Any,
    image_artifacts: Iterable[Path],
    measurement_csvs: list[Path],
    *,
    width: Any,
    measurement_table_width: Any,
) -> None:
    cell.text = ""
    first = True
    for artifact in image_artifacts:
        added_summary = _add_measurement_summary_for_image(cell, artifact, measurement_csvs, measurement_table_width)
        paragraph = cell.paragraphs[0] if first and not added_summary else cell.add_paragraph()
        _add_picture_to_paragraph(paragraph, artifact, width=width)
        first = False


def _add_measurement_summary_for_image(
    cell: Any,
    image_artifact: Path,
    measurement_csvs: list[Path],
    measurement_table_width: Any,
    *,
    add_trailing_paragraph: bool = True,
) -> bool:
    csv_path = _matching_measurement_csv(image_artifact, measurement_csvs)
    if csv_path is None:
        return False
    rows = _accum_measurement_rows(csv_path)
    if not rows:
        return False
    table = cell.add_table(rows=1, cols=len(rows[0]))
    table.style = "Table Grid"
    for index, header in enumerate(rows[0]):
        table.rows[0].cells[index].text = header
    for values in rows[1:]:
        row = table.add_row().cells
        for index, value in enumerate(values):
            row[index].text = value
    column_width = int((measurement_table_width // len(rows[0])) * APPENDIX_MEASUREMENT_COLUMN_WIDTH_FRACTION)
    _set_table_column_widths(table, [column_width] * len(rows[0]))
    _center_table_columns(table, range(2, len(rows[0])))
    if add_trailing_paragraph:
        cell.add_paragraph("")
    return True


def _add_artifact_objects_to_cell(cell: Any, image_artifacts: Iterable[Path], inches: Any) -> None:
    first = not any(paragraph.text for paragraph in cell.paragraphs)
    for artifact in image_artifacts:
        if not first:
            cell.add_paragraph()
        object_paragraph = cell.add_paragraph()
        _add_embedded_package_to_paragraph(object_paragraph, artifact, width=inches(OBJECT_ICON_WIDTH_INCHES))
        first = False


def _center_cell_paragraphs(cell: Any) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _center_table_column(table: Any, column_index: int) -> None:
    for row in table.rows:
        _center_cell_paragraphs(row.cells[column_index])


def _center_table_columns(table: Any, column_indexes: Iterable[int]) -> None:
    for column_index in column_indexes:
        _center_table_column(table, column_index)


def _center_performance_summary_columns(table: Any, utility_label: str) -> None:
    if utility_label in {"ATTO", "Crystal Disk Mark", "Disks", "Blackmagic"}:
        _center_table_columns(table, range(1, min(3, len(table.columns))))


def _add_windows_performance_objects_to_cell(cell: Any, image_artifacts: Iterable[Path], inches: Any) -> None:
    first = True
    for artifact in image_artifacts:
        blank_count = (
            WINDOWS_PERFORMANCE_BLANK_LINES_BEFORE_FIRST_OBJECT
            if first
            else WINDOWS_PERFORMANCE_BLANK_LINES_BETWEEN_OBJECTS
        )
        for _ in range(blank_count):
            cell.add_paragraph()
        object_paragraph = cell.add_paragraph()
        _add_embedded_package_to_paragraph(object_paragraph, artifact, width=inches(OBJECT_ICON_WIDTH_INCHES))
        first = False


def _add_measurement_summaries_to_cell(
    cell: Any,
    image_artifacts: Iterable[Path],
    measurement_csvs: list[Path],
    *,
    measurement_table_width: Any,
) -> None:
    cell.text = ""
    for artifact in image_artifacts:
        _add_measurement_summary_for_image(
            cell,
            artifact,
            measurement_csvs,
            measurement_table_width,
            add_trailing_paragraph=False,
        )
    _minimize_empty_cell_paragraphs(cell)


def _add_csv_tables_to_cell(
    cell: Any,
    image_artifacts: Iterable[Path],
    csv_paths: list[Path],
    *,
    table_width: Any,
) -> None:
    cell.text = ""
    matching_tables: list[tuple[Path, list[list[str]]]] = []
    for artifact in image_artifacts:
        csv_path = _matching_measurement_csv(artifact, csv_paths)
        if csv_path is None:
            continue
        rows = _performance_csv_rows(artifact, csv_path)
        if rows:
            matching_tables.append((artifact, rows))
    for index, (artifact, rows) in enumerate(matching_tables):
        if index:
            _add_minimized_empty_paragraph(cell)
        utility_label = _performance_utility_label(artifact)
        nested_table = _add_nested_table(cell, [[utility_label], *rows], table_width)
        _center_performance_summary_columns(nested_table, utility_label)
        if utility_label == "Disks":
            _merge_linux_disks_access_time_row(nested_table)
    _minimize_trailing_empty_cell_paragraph(cell)


def _minimize_empty_cell_paragraphs(cell: Any) -> None:
    for paragraph in cell.paragraphs:
        if paragraph.text or paragraph._p.xpath(".//w:drawing | .//w:object"):
            continue
        _minimize_empty_paragraph(paragraph)


def _minimize_trailing_empty_cell_paragraph(cell: Any) -> None:
    if not cell.paragraphs:
        return
    paragraph = cell.paragraphs[-1]
    if paragraph.text or paragraph._p.xpath(".//w:drawing | .//w:object"):
        return
    _minimize_empty_paragraph(paragraph)


def _minimize_empty_paragraph(paragraph: Any) -> None:
    from docx.shared import Pt

    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = Pt(1)
    if not paragraph.runs:
        paragraph.add_run()
    for run in paragraph.runs:
        run.font.size = Pt(1)


def _add_minimized_empty_paragraph(cell: Any) -> None:
    paragraph = cell.add_paragraph("")
    _minimize_empty_paragraph(paragraph)


def _add_nested_table(cell: Any, rows: list[list[str]], table_width: Any) -> Any:
    normalized_rows = _normalize_table_rows(rows)
    table = cell.add_table(rows=1, cols=len(normalized_rows[0]))
    table.style = "Table Grid"
    for index, header in enumerate(normalized_rows[0]):
        table.rows[0].cells[index].text = header
    for values in normalized_rows[1:]:
        row = table.add_row().cells
        for index, value in enumerate(values):
            row[index].text = value
    column_width = int((table_width // len(normalized_rows[0])) * APPENDIX_MEASUREMENT_COLUMN_WIDTH_FRACTION)
    _set_table_column_widths(table, [column_width] * len(normalized_rows[0]))
    return table


def _merge_linux_disks_access_time_row(table: Any) -> None:
    for row in table.rows:
        if row.cells[0].text == "Average Access Time" and len(row.cells) >= LINUX_DISKS_SUMMARY_COLUMN_COUNT:
            merged_cell = row.cells[1].merge(row.cells[2])
            _remove_extra_empty_paragraphs(merged_cell)
            return


def _remove_extra_empty_paragraphs(cell: Any) -> None:
    non_empty_paragraphs = [paragraph for paragraph in cell.paragraphs if paragraph.text]
    if not non_empty_paragraphs:
        return
    for paragraph in list(cell.paragraphs):
        if paragraph.text:
            continue
        paragraph._element.getparent().remove(paragraph._element)


def _normalize_table_rows(rows: list[list[str]]) -> list[list[str]]:
    width = max(len(row) for row in rows)
    return [row + ([""] * (width - len(row))) for row in rows]


def _add_embedded_package_to_paragraph(paragraph: Any, artifact: Path, *, width: Any) -> None:
    object_r_id = _relate_to_embedded_package(paragraph.part, artifact)
    icon_r_id = _relate_to_object_icon(paragraph.part, artifact)
    shape_id = f"_x0000_i{1000 + _relationship_number(object_r_id)}"
    object_id = f"_{zlib.crc32(f'{artifact.name}:{object_r_id}'.encode()) % 2_000_000_000}"
    run = paragraph.add_run()
    run_element = run._r
    run_element.append(
        _embedded_package_xml(
            object_r_id=object_r_id,
            icon_r_id=icon_r_id,
            shape_id=shape_id,
            object_id=object_id,
            width_pt=_points(width),
        )
    )


def _relationship_number(r_id: str) -> int:
    suffix = r_id.removeprefix("rId")
    return int(suffix) if suffix.isdecimal() else 0


def _relate_to_embedded_package(part: Any, artifact: Path) -> str:
    from docx.opc.constants import CONTENT_TYPE as CT
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    package = part.package
    partname = package.next_partname("/word/embeddings/oleObject%d.bin")
    ole_part = Part(
        PackURI(str(partname)),
        CT.OFC_OLE_OBJECT,
        _ole_package_blob(label=artifact.name, filename=artifact.name, payload=artifact.read_bytes()),
        package,
    )
    return cast(str, part.relate_to(ole_part, RT.OLE_OBJECT))


def _relate_to_object_icon(part: Any, artifact: Path) -> str:
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    package = part.package
    icon_part = package.get_or_add_image_part(_object_preview_stream(artifact))
    return cast(str, part.relate_to(icon_part, RT.IMAGE))


def _object_preview_stream(artifact: Path) -> io.BytesIO:
    from PIL import Image

    stream = io.BytesIO()
    image = Image.open(artifact)
    image.thumbnail((96, 96))
    image.save(stream, format="PNG")
    stream.seek(0)
    cast(Any, stream).name = f"{artifact.stem}-preview.png"
    return stream


def _embedded_package_xml(*, object_r_id: str, icon_r_id: str, shape_id: str, object_id: str, width_pt: float) -> Any:
    from docx.oxml import parse_xml

    height_pt = width_pt
    return parse_xml(
        f"""
        <w:object
            xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:v="urn:schemas-microsoft-com:vml"
            xmlns:o="urn:schemas-microsoft-com:office:office"
            w:dxaOrig="{int(width_pt * 20)}"
            w:dyaOrig="{int(height_pt * 20)}">
            <v:shapetype id="_x0000_t75" coordsize="21600,21600" o:spt="75"
                o:preferrelative="t" path="m@4@5l@4@11@9@11@9@5xe" filled="f" stroked="f">
                <v:stroke joinstyle="miter"/>
                <v:formulas>
                    <v:f eqn="if lineDrawn pixelLineWidth 0"/>
                    <v:f eqn="sum @0 1 0"/>
                    <v:f eqn="sum 0 0 @1"/>
                    <v:f eqn="prod @2 1 2"/>
                    <v:f eqn="prod @3 21600 pixelWidth"/>
                    <v:f eqn="prod @3 21600 pixelHeight"/>
                    <v:f eqn="sum @0 0 1"/>
                    <v:f eqn="prod @6 1 2"/>
                    <v:f eqn="prod @7 21600 pixelWidth"/>
                    <v:f eqn="sum @8 21600 0"/>
                    <v:f eqn="prod @7 21600 pixelHeight"/>
                    <v:f eqn="sum @10 21600 0"/>
                </v:formulas>
                <v:path o:extrusionok="f" gradientshapeok="t" o:connecttype="rect"/>
                <o:lock v:ext="edit" aspectratio="t"/>
            </v:shapetype>
            <v:shape id="{shape_id}" type="#_x0000_t75"
                style="width:{width_pt:.2f}pt;height:{height_pt:.2f}pt" o:ole="">
                <v:imagedata r:id="{icon_r_id}" o:title=""/>
            </v:shape>
            <o:OLEObject Type="Embed" ProgID="Package" ShapeID="{shape_id}"
                DrawAspect="Icon" ObjectID="{object_id}" r:id="{object_r_id}"/>
        </w:object>
        """
    )


def _points(width: Any) -> float:
    return int(width) / 12700.0


def _ole_package_blob(*, label: str, filename: str, payload: bytes) -> bytes:
    streams = [
        _CfbStream("\x01Ole", OLE_MARKER_BYTES),
        _CfbStream("\x01Ole10Native", _ole10_native_stream(label=label, filename=filename, payload=payload)),
    ]
    return _write_cfb(streams)


def _ole10_native_stream(*, label: str, filename: str, payload: bytes) -> bytes:
    label_bytes = _asciiz(label)
    filename_bytes = _asciiz(filename)
    command_bytes = filename.encode("utf-8")
    body = b"".join(
        [
            struct.pack("<H", 2),
            label_bytes,
            filename_bytes,
            struct.pack("<H", 0),
            struct.pack("<H", 3),
            struct.pack("<I", len(command_bytes)),
            command_bytes,
            struct.pack("<I", len(payload)),
            payload,
        ]
    )
    return struct.pack("<I", len(body)) + body


def _asciiz(value: str) -> bytes:
    return value.encode("utf-8", errors="replace") + b"\x00"


@dataclass
class _CfbStream:
    name: str
    data: bytes
    start: int = CFB_END_OF_CHAIN

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def mini(self) -> bool:
        return len(self.data) < CFB_MINI_STREAM_CUTOFF


@dataclass(frozen=True)
class _DirectoryEntry:
    name: str
    entry_type: int
    right: int = CFB_NO_STREAM
    child: int = CFB_NO_STREAM
    start: int = CFB_END_OF_CHAIN
    size: int = 0
    clsid: bytes = b"\x00" * 16


@dataclass(frozen=True)
class _FatLayout:
    sector_count: int
    fat_sector_count: int
    minifat_start: int
    minifat_sector_count: int
    directory_start: int
    root_start: int
    root_sector_count: int
    regular_streams: list[_CfbStream]


def _write_cfb(streams: list[_CfbStream]) -> bytes:
    mini_stream, mini_fat = _build_mini_stream(streams)
    regular_streams = [stream for stream in streams if not stream.mini]
    minifat_stream = _pack_fat(mini_fat)
    minifat_sector_count = _sector_count(minifat_stream)
    root_sector_count = _sector_count(mini_stream)
    regular_sector_count = sum(_sector_count(stream.data) for stream in regular_streams)
    nonfat_sector_count = minifat_sector_count + 1 + root_sector_count + regular_sector_count
    fat_sector_count = _fat_sector_count(nonfat_sector_count)
    first_minifat_sector = fat_sector_count if mini_fat else CFB_END_OF_CHAIN
    first_directory_sector = fat_sector_count + minifat_sector_count
    current_sector = first_directory_sector + 1
    root_start = current_sector if mini_stream else CFB_END_OF_CHAIN
    current_sector += root_sector_count
    for stream in regular_streams:
        stream.start = current_sector
        current_sector += _sector_count(stream.data)
    directory_stream = _build_directory_stream(streams, root_start=root_start, root_size=len(mini_stream))
    sector_payloads = [b""] * fat_sector_count
    sector_payloads.extend(_chunk_sectors(minifat_stream))
    sector_payloads.extend(_chunk_sectors(directory_stream))
    sector_payloads.extend(_chunk_sectors(mini_stream))
    for stream in regular_streams:
        sector_payloads.extend(_chunk_sectors(stream.data))
    fat = _build_fat(
        _FatLayout(
            sector_count=len(sector_payloads),
            fat_sector_count=fat_sector_count,
            minifat_start=first_minifat_sector,
            minifat_sector_count=minifat_sector_count,
            directory_start=first_directory_sector,
            root_start=root_start,
            root_sector_count=root_sector_count,
            regular_streams=regular_streams,
        )
    )
    fat_sectors = _chunk_sectors(_pack_fat(fat))
    sector_payloads[:fat_sector_count] = fat_sectors
    header = _cfb_header(fat_sector_count, first_directory_sector, first_minifat_sector, minifat_sector_count)
    return header + b"".join(_pad(payload, CFB_SECTOR_SIZE) for payload in sector_payloads)


def _build_mini_stream(streams: list[_CfbStream]) -> tuple[bytes, list[int]]:
    mini_sectors: list[bytes] = []
    mini_fat: list[int] = []
    for stream in streams:
        if not stream.mini:
            continue
        stream.start = len(mini_sectors)
        chunks = _chunk_units(stream.data, CFB_MINI_SECTOR_SIZE)
        mini_sectors.extend(chunks)
        for offset in range(len(chunks)):
            mini_fat.append(stream.start + offset + 1 if offset < len(chunks) - 1 else CFB_END_OF_CHAIN)
    return b"".join(mini_sectors), mini_fat


def _build_directory_stream(streams: list[_CfbStream], *, root_start: int, root_size: int) -> bytes:
    entries = [
        _directory_entry(
            _DirectoryEntry(
                "Root Entry",
                5,
                child=1 if streams else CFB_NO_STREAM,
                start=root_start,
                size=root_size,
                clsid=PACKAGE_CLSID,
            )
        )
    ]
    for index, stream in enumerate(streams, start=1):
        right = index + 1 if index < len(streams) else CFB_NO_STREAM
        entries.append(
            _directory_entry(_DirectoryEntry(stream.name, 2, right=right, start=stream.start, size=stream.size))
        )
    return _pad(b"".join(entries), CFB_SECTOR_SIZE)


def _directory_entry(spec: _DirectoryEntry) -> bytes:
    name_bytes = spec.name.encode("utf-16le") + b"\x00\x00"
    entry = bytearray(128)
    entry[: len(name_bytes)] = name_bytes
    struct.pack_into("<H", entry, 64, len(name_bytes))
    entry[66] = spec.entry_type
    entry[67] = 1
    struct.pack_into("<iii", entry, 68, CFB_NO_STREAM, spec.right, spec.child)
    entry[80:96] = spec.clsid
    struct.pack_into("<i", entry, 116, spec.start)
    struct.pack_into("<Q", entry, 120, spec.size)
    return bytes(entry)


def _build_fat(layout: _FatLayout) -> list[int]:
    fat: list[int] = [CFB_FREE_SECTOR] * layout.sector_count
    for index in range(layout.fat_sector_count):
        fat[index] = CFB_FAT_SECTOR
    _mark_fat_chain(fat, layout.minifat_start, layout.minifat_sector_count)
    _mark_fat_chain(fat, layout.directory_start, 1)
    _mark_fat_chain(fat, layout.root_start, layout.root_sector_count)
    for stream in layout.regular_streams:
        _mark_fat_chain(fat, stream.start, _sector_count(stream.data))
    return fat


def _mark_fat_chain(fat: list[int], start: int, count: int) -> None:
    if start < 0 or count == 0:
        return
    for offset in range(count):
        fat[start + offset] = start + offset + 1 if offset < count - 1 else CFB_END_OF_CHAIN


def _cfb_header(
    fat_sector_count: int,
    first_directory_sector: int,
    first_minifat_sector: int,
    minifat_sector_count: int,
) -> bytes:
    header = bytearray(CFB_SECTOR_SIZE)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x003E, 0x0003, 0xFFFE, 9, 6)
    struct.pack_into(
        "<IIiIIi",
        header,
        40,
        0,
        fat_sector_count,
        first_directory_sector,
        0,
        CFB_MINI_STREAM_CUTOFF,
        first_minifat_sector,
    )
    struct.pack_into("<Ii", header, 64, minifat_sector_count, CFB_END_OF_CHAIN)
    struct.pack_into("<I", header, 72, 0)
    for index in range(109):
        value = index if index < fat_sector_count else CFB_FREE_SECTOR
        struct.pack_into("<i", header, 76 + index * 4, value)
    return bytes(header)


def _pack_fat(fat: list[int]) -> bytes:
    if not fat:
        return b""
    padding = (_sector_count(struct.pack(f"<{len(fat)}i", *fat)) * 128) - len(fat)
    padded = fat + ([CFB_FREE_SECTOR] * padding)
    return struct.pack(f"<{len(padded)}i", *padded)


def _fat_sector_count(payload_sector_count: int) -> int:
    fat_sector_count = 1
    while fat_sector_count * 128 < payload_sector_count + fat_sector_count:
        fat_sector_count += 1
    return fat_sector_count


def _chunk_sectors(data: bytes) -> list[bytes]:
    return _chunk_units(data, CFB_SECTOR_SIZE)


def _chunk_units(data: bytes, unit_size: int) -> list[bytes]:
    if not data:
        return []
    return [data[index : index + unit_size] for index in range(0, len(data), unit_size)]


def _sector_count(data: bytes) -> int:
    return (len(data) + CFB_SECTOR_SIZE - 1) // CFB_SECTOR_SIZE


def _pad(data: bytes, size: int) -> bytes:
    remainder = len(data) % size
    return data if remainder == 0 else data + (b"\x00" * (size - remainder))


def _matching_measurement_csv(image_artifact: Path, measurement_csvs: list[Path]) -> Path | None:
    same_stem = [csv_path for csv_path in measurement_csvs if csv_path.stem == image_artifact.stem]
    if same_stem:
        return same_stem[0]
    return measurement_csvs[0] if len(measurement_csvs) == 1 else None


def _add_picture_to_paragraph(paragraph: Any, artifact: Path, *, width: Any) -> None:
    try:
        paragraph.add_run().add_picture(str(artifact), width=width)
    except Exception:
        paragraph.add_run(str(artifact.name))


def _list_line(document: Any, text: str, level: int = 0) -> None:
    from docx.shared import Inches

    p = document.add_paragraph(text, style="List Bullet")
    if level > 0:
        p.paragraph_format.left_indent = Inches(0.25 * (level + 1))


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


def _compliance_row(
    table: Any, shade_cell: Callable[[Any, Status], None], program: str, iterations: str, result: str
) -> None:
    row = table.add_row().cells
    row[0].text = program
    row[1].text = iterations
    row[2].text = result
    shade_cell(row[2], _result_status(result))


def _result_status(result: str) -> Status:
    lowered = result.casefold()
    if lowered == "pass":
        return Status.PASS
    if lowered == "fail":
        return Status.FAIL
    return Status.MISSING


def _result_sentence(evaluated: EvaluatedReport) -> str:
    failures = next((int(row.value) for row in evaluated.summary if row.label == "Failures"), 0)
    warnings = next((int(row.value) for row in evaluated.summary if row.label == "Warnings"), 0)
    if failures:
        return f"Review required: {failures} failing result(s) and {warnings} warning(s) were detected."
    if warnings:
        return f"Drive performed with {warnings} warning result(s) requiring review."
    return "Drive performed nominally across recorded qualification data."


def _artifact_files(part_root: Path) -> list[Path]:
    if not part_root.exists():
        return []
    excluded_names = {TEMPLATE_NAME, DEFAULT_OUTPUT_NAME}
    return sorted(
        path
        for path in part_root.rglob("*")
        if path.is_file() and path.name not in excluded_names and not path.name.startswith("._")
    )


def _matching_artifact_text(part_root: Path, dut_name: str, os_name: str, label: str) -> str:
    return _artifact_names(part_root, _matching_artifacts(part_root, dut_name, os_name, label))


def _matching_artifacts(part_root: Path, dut_name: str, os_name: str, label: str) -> list[Path]:
    os_token = "macOS" if os_name == "MAC" else os_name
    category_tokens = {
        "Inrush Summary": ("in rush", "inrush"),
        "Max IO Summary": ("max io", "max i/o"),
        "Performance": ("performance", "crystaldiskmark", "atto", "blackmagic", "disks"),
        "Drive Information": ("crystaldiskinfo", "drive information", "drive info"),
    }[label]
    dut_norm = _normalize_text(dut_name)
    matches: list[Path] = []
    for artifact in _artifact_files(part_root):
        text = _normalize_text(str(artifact.relative_to(part_root)))
        if _normalize_text(os_token) not in text:
            continue
        if dut_norm not in text and not any(part in text for part in dut_norm.split()):
            continue
        if any(_normalize_text(token) in text for token in category_tokens):
            matches.append(artifact)
    return matches if label in MEASUREMENT_LABELS else matches[:4]


def _image_artifacts(artifacts: Iterable[Path]) -> list[Path]:
    return [artifact for artifact in artifacts if artifact.suffix.casefold() in IMAGE_EXTENSIONS]


def _non_image_artifacts(artifacts: Iterable[Path]) -> list[Path]:
    return [artifact for artifact in artifacts if artifact.suffix.casefold() not in IMAGE_EXTENSIONS]


def _measurement_csvs(artifacts: Iterable[Path]) -> list[Path]:
    return [artifact for artifact in artifacts if artifact.suffix.casefold() == ".csv"]


def _accum_measurement_rows(csv_path: Path) -> list[list[str]]:
    rows = _measurement_rows(csv_path)
    accum_fields = _accum_fields(rows)
    if not accum_fields:
        return []
    table_rows = [["Name", "Measurement", *accum_fields]]
    for row in rows:
        if row.get("Name") in EXCLUDED_MEASUREMENT_ROWS:
            continue
        values = [row.get("Name", ""), row.get("Measurement", "")]
        values.extend(row.get(field, "") for field in accum_fields)
        table_rows.append(values)
    return table_rows


def _measurement_rows(csv_path: Path) -> list[dict[str, str]]:
    lines = _decoded_csv_lines(csv_path)
    if not lines:
        return []
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Name,")), None)
    if header_index is None:
        return []
    reader = csv.DictReader(lines[header_index:])
    return [
        {str(key): str(value).strip() for key, value in row.items() if key is not None and value is not None}
        for row in reader
        if row.get("Name", "").strip()
    ]


def _generic_csv_rows(csv_path: Path) -> list[list[str]]:
    lines = _decoded_csv_lines(csv_path)
    if not lines:
        return []
    rows = [row for row in csv.reader(lines) if any(cell.strip() for cell in row)]
    if not rows:
        return []
    return _normalize_table_rows(rows)


def _performance_csv_rows(artifact: Path, csv_path: Path) -> list[list[str]]:
    rows = _generic_csv_rows(csv_path)
    utility_label = _performance_utility_label(artifact)
    if utility_label == "Disks":
        return _linux_disks_summary_rows(rows)
    if utility_label == "Blackmagic":
        return _read_write_summary_rows(rows)
    return rows


def _read_write_summary_rows(rows: list[list[str]]) -> list[list[str]]:
    values = {row[0].strip().casefold(): row[1].strip() for row in rows[1:] if len(row) >= KEY_VALUE_CSV_ROW_WIDTH}
    return [["Metric", "Read", "Write"], ["Speed", values.get("read mb/s", ""), values.get("write mb/s", "")]]


def _linux_disks_summary_rows(rows: list[list[str]]) -> list[list[str]]:
    values = {row[0].strip().casefold(): row[1].strip() for row in rows[1:] if len(row) >= KEY_VALUE_CSV_ROW_WIDTH}
    summary_rows = [
        ("Minimum Rate", values.get("minimum read rate", ""), values.get("minimum write rate", "")),
        ("Average Rate", values.get("average read rate", ""), values.get("average write rate", "")),
        ("Maximum Rate", values.get("maximum read rate", ""), values.get("maximum write rate", "")),
    ]
    extra_rows = [
        ("Average Access Time", values.get("average access time", ""), ""),
    ]
    return [["Metric", "Read", "Write"], *[list(row) for row in summary_rows + extra_rows if any(row[1:])]]


def _performance_utility_label(artifact: Path) -> str:
    text = _normalize_text(str(artifact))
    if "atto" in text:
        return "ATTO"
    if "blackmagic" in text:
        return "Blackmagic"
    if "crystaldiskmark" in text or "crystal disk mark" in text:
        return "Crystal Disk Mark"
    if "disks" in text:
        return "Disks"
    return artifact.stem


def _sorted_performance_images(image_artifacts: Iterable[Path]) -> list[Path]:
    return sorted(image_artifacts, key=lambda artifact: (_performance_utility_sort_key(artifact), str(artifact)))


def _performance_utility_sort_key(artifact: Path) -> int:
    label = _performance_utility_label(artifact)
    order = {
        "ATTO": 0,
        "Crystal Disk Mark": 1,
        "Blackmagic": 2,
        "Disks": 3,
    }
    return order.get(label, len(order))


def _decoded_csv_lines(csv_path: Path) -> list[str]:
    try:
        raw = csv_path.read_bytes()
    except OSError:
        return []
    for encoding in CSV_ENCODING_CANDIDATES:
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return []


def _accum_fields(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key.startswith("Accum-") and key not in EXCLUDED_ACCUM_FIELDS and key not in fields:
                fields.append(key)
    return fields


def _artifact_names(part_root: Path, artifacts: Iterable[Path]) -> str:
    return "\n".join(str(artifact.relative_to(part_root)) for artifact in artifacts)


def _report_duts(data: dict[str, Any]) -> list[str]:
    equipment = data.get("equipment")
    if isinstance(equipment, dict) and isinstance(equipment.get("dut"), dict):
        return [str(key) for key in equipment["dut"]]
    performance = data.get("performance")
    if isinstance(performance, dict):
        return [str(key) for key in performance]
    power = data.get("power")
    if isinstance(power, dict):
        return [str(key) for key in power]
    return []


def _field(data: object, key: str) -> str:
    if not isinstance(data, dict):
        return ""
    return _format_value(data.get(key))


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return ", ".join(_format_value(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{_label(str(key))}: {_format_value(val)}" for key, val in value.items())
    return str(value)


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _join_present(*values: object) -> str:
    return ", ".join(str(value) for value in values if value)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def run_report_generate_cli() -> None:
    parser = argparse.ArgumentParser(description="Generate a Word drive qualification report.")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument(
        "--source-root",
        type=Path,
        help="Local or fileshare root containing <part-number>/drive_qualification_report_atomic_tests.json.",
    )
    parser.add_argument("--output", type=Path, help="Output .docx path.")
    args = parser.parse_args()

    output_path = generate_report_docx(
        part_number=args.part_number,
        source_root=args.source_root,
        output=args.output,
    )
    print(f"Generated Word report at {output_path}")


if __name__ == "__main__":
    run_report_generate_cli()
