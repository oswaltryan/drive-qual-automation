from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

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
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
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
    ("device_manager_disk_mgmt", "Appears in Device Manager & Disk Management"),
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

    document.add_heading("Drive Qualification Report.", level=1)
    _add_revision_table(document)
    _add_drive_info(document, data.get("drive_info"), report_path)
    _add_qualification_equipment(document, data.get("equipment"))
    _add_test_procedure(document)

    document.add_heading("Test Results", level=1)
    _add_power_data(document, data.get("power"), shade_cell)
    _add_compatibility_data(document, data.get("compatibility"), shade_cell)
    _add_temperature_data(document, data.get("temperature"), shade_cell)
    _add_disk_performance(document, data.get("performance"))
    _add_compliance(document, data.get("compliance"), shade_cell)
    document.add_heading("Datasheet", level=2)
    _add_raw_screenshot_index(document)
    _add_result_and_notes(document, evaluated)
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
        tc_pr = cell._tc.get_or_add_tcPr()  # noqa: SLF001
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), STATUS_COLORS[status])
        tc_pr.append(shading)

    return Document, Inches, shade_cell


def _set_margins(document: Any, inches: Any) -> None:
    for section in document.sections:
        section.left_margin = inches(0.6)
        section.right_margin = inches(0.6)
        section.top_margin = inches(0.6)
        section.bottom_margin = inches(0.6)


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
        for software in _software_entries(host.get("software")):
            _list_line(document, f"Software: {software}")


def _scope_lines(document: Any, equipment: dict[str, Any]) -> None:
    scope = equipment.get("scope")
    if isinstance(scope, dict):
        _list_line(document, f"Measuring Device: {_field(scope, 'model')}")
        _list_line(document, f"Scope Serial Number: {_field(scope, 'serial_number')}")
        _list_line(document, f"Version: {_field(scope, 'version')}")
    _probe_line(document, equipment.get("probe_current"), "Current")
    _probe_line(document, equipment.get("probe_voltage"), "Voltage")


def _probe_line(document: Any, probe: object, role: str) -> None:
    if not isinstance(probe, dict):
        return
    channel = _field(probe, "channel")
    channel_text = f" - Channel {channel}" if channel else ""
    _list_line(document, f"Probe Type: {_field(probe, 'model')}{channel_text} ({role})")
    _list_line(document, f"Serial Number: {_field(probe, 'serial_number')}")


def _dut_lines(document: Any, dut_data: object) -> None:
    _list_line(document, "Device Under Test (DUT):")
    if not isinstance(dut_data, dict) or not dut_data:
        _list_line(document, "No DUT data recorded.")
        return
    for dut_name, binding in dut_data.items():
        serial = _field(binding, "serial_number") if isinstance(binding, dict) else ""
        _list_line(document, f"{dut_name}: {serial}")


def _add_test_procedure(document: Any) -> None:
    document.add_heading("Test Procedure", level=2)
    _list_line(document, "1006 HDD Qualification Work Instruction")


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


def _add_compatibility_data(document: Any, compatibility: object, shade_cell: Callable[[Any, Status], None]) -> None:
    document.add_heading("Compatibility Data", level=2)
    document.add_paragraph(
        "Include any failures for a specific product in the corresponding row/column using the product name in red."
    )
    table = _table(document, ["Test", "Linux", "MacOS", "Windows"])
    for key, label in COMPATIBILITY_ROWS:
        row = table.add_row().cells
        row[0].text = label
        for index, (os_key, _display) in enumerate(OS_COLUMNS, start=1):
            status = _compatibility_status(compatibility, key, os_key)
            row[index].text = _status_text(status)
            shade_cell(row[index], status)


def _add_temperature_data(document: Any, temperature: object, shade_cell: Callable[[Any, Status], None]) -> None:
    document.add_heading("Temperature Data", level=2)
    if not isinstance(temperature, dict) or not temperature:
        document.add_paragraph("No temperature data recorded.")
        return
    sections = _temperature_sections(temperature)
    for dut_name, dut_data in sections:
        if len(sections) > 1:
            document.add_paragraph(str(dut_name))
        table = _table(document, ["Temperature", "Read MB/s", "Write MB/s"])
        for temp_label, values in _temperature_rows(dut_data):
            row = table.add_row().cells
            row[0].text = _format_temperature_label(temp_label)
            _set_temperature_cell(row[1], values.get("read_mb_s"), values.get("error"), shade_cell)
            _set_temperature_cell(row[2], values.get("write_mb_s"), values.get("error"), shade_cell)


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


def _add_compliance(document: Any, compliance: object, shade_cell: Callable[[Any, Status], None]) -> None:
    document.add_heading("Compliance/Reliability Test", level=2)
    table = _table(document, ["Program", "Iterations/Loops", "Result"])
    _compliance_row(
        table,
        shade_cell,
        "USB-IF Mass Storage Compliance (MSC)",
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
    table.add_row()


def _add_raw_screenshot_index(document: Any) -> None:
    document.add_heading("Disk Performance Raw Data & Screenshots", level=2)
    document.add_paragraph("")


def _add_result_and_notes(document: Any, evaluated: EvaluatedReport) -> None:
    document.add_heading("Drive Qualification Result", level=2)
    document.add_paragraph(_result_sentence(evaluated))
    document.add_heading("Notes and Considerations", level=2)
    document.add_paragraph("")


def _add_appendix(document: Any, data: dict[str, Any], part_root: Path, inches: Any) -> None:
    document.add_heading("Appendix", level=2)
    duts = _report_duts(data)
    for dut_name in duts:
        document.add_heading(f"Disk Performance Raw Data & Measurements ({dut_name})", level=2)
        for os_name in ("Windows", "Linux", "MAC"):
            _add_platform_artifact_table(document, part_root, dut_name, os_name, inches)


def _add_platform_artifact_table(document: Any, part_root: Path, dut_name: str, os_name: str, inches: Any) -> None:
    table = _table(document, [os_name, ""])
    for label in ("Inrush Summary", "Max IO Summary", "Performance"):
        row = table.add_row().cells
        row[0].text = label
        _add_matching_artifacts_to_cell(row[1], part_root, dut_name, os_name, label, inches)
    if os_name == "Windows":
        row = table.add_row().cells
        row[0].text = "Drive Information"
        _add_matching_artifacts_to_cell(row[1], part_root, dut_name, os_name, "Drive Information", inches)


def _table(document: Any, headers: Iterable[str]) -> Any:
    header_list = list(headers)
    table = document.add_table(rows=1, cols=len(header_list))
    table.style = "Table Grid"
    for cell, header in zip(table.rows[0].cells, header_list, strict=True):
        cell.text = header
    return table


def _add_matching_artifacts_to_cell(
    cell: Any, part_root: Path, dut_name: str, os_name: str, label: str, inches: Any
) -> None:
    artifacts = _matching_artifacts(part_root, dut_name, os_name, label)
    image_artifacts = _image_artifacts(artifacts)
    if image_artifacts:
        _add_images_to_cell(cell, image_artifacts, width=inches(APPENDIX_IMAGE_WIDTH_INCHES))
        return
    cell.text = _artifact_names(part_root, artifacts)


def _add_images_to_cell(cell: Any, artifacts: Iterable[Path], *, width: Any) -> None:
    cell.text = ""
    paragraphs = cell.paragraphs
    first = True
    for artifact in artifacts:
        paragraph = paragraphs[0] if first and paragraphs else cell.add_paragraph()
        first = False
        _add_picture_to_paragraph(paragraph, artifact, width=width)


def _add_picture_to_paragraph(paragraph: Any, artifact: Path, *, width: Any) -> None:
    try:
        paragraph.add_run().add_picture(str(artifact), width=width)
    except Exception:
        paragraph.add_run(str(artifact.name))


def _list_line(document: Any, text: str) -> None:
    document.add_paragraph(text, style="List Paragraph")


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


def _format_temperature_label(value: str) -> str:
    match = TEMP_RE.search(value)
    if match is None:
        return value
    numeric = float(match.group("value"))
    label = str(int(numeric)) if numeric.is_integer() else str(numeric)
    return f"{label}°C"


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
    return sorted(path for path in part_root.rglob("*") if path.is_file() and path.name not in excluded_names)


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
    return matches[:4]


def _image_artifacts(artifacts: Iterable[Path]) -> list[Path]:
    return [artifact for artifact in artifacts if artifact.suffix.casefold() in IMAGE_EXTENSIONS]


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
