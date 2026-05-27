from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from drive_qual.core.report_session import TEMPLATE_NAME
from drive_qual.reports.cdi import CDI_APPENDIX_FIELDS
from drive_qual.reports.constants import (
    APPENDIX_IMAGE_WIDTH_INCHES,
    APPENDIX_MEASUREMENT_COLUMN_WIDTH_FRACTION,
    APPENDIX_OS_ARTIFACT_WIDTH_INCHES,
    APPENDIX_OS_LABEL_WIDTH_INCHES,
    CSV_ENCODING_CANDIDATES,
    DEFAULT_OUTPUT_NAME,
    EXCLUDED_ACCUM_FIELDS,
    EXCLUDED_MEASUREMENT_ROWS,
    IMAGE_EXTENSIONS,
    KEY_VALUE_CSV_ROW_WIDTH,
    LINUX_DISKS_SUMMARY_COLUMN_COUNT,
    MEASUREMENT_LABELS,
    OBJECT_ICON_WIDTH_INCHES,
    PERFORMANCE_LABEL,
    WINDOWS_PERFORMANCE_BLANK_LINES_BEFORE_FIRST_OBJECT,
    WINDOWS_PERFORMANCE_BLANK_LINES_BETWEEN_OBJECTS,
)
from drive_qual.reports.docx_shared import (
    _add_heading,
    _add_minimized_empty_paragraph,
    _add_nested_table,
    _add_picture_to_paragraph,
    _center_cell_paragraphs,
    _center_table_column,
    _center_table_columns,
    _minimize_empty_cell_paragraphs,
    _minimize_trailing_empty_cell_paragraph,
    _normalize_table_rows,
    _normalize_text,
    _remove_extra_empty_paragraphs,
    _set_table_column_widths,
    _shade_cell,
    _table,
)
from drive_qual.reports.embedded import _add_embedded_package_to_paragraph
from drive_qual.reports.evaluation import Status

ATTO_EXCLUDED_IO_SIZE_BYTES = {32 * 1024, 128 * 1024, 512 * 1024, 2 * 1024 * 1024}
ATTO_MAX_IO_SIZE_BYTES = 4 * 1024 * 1024


def _add_appendix(document: Any, data: dict[str, Any], part_root: Path, inches: Any) -> None:
    duts = _report_duts(data)
    for dut_name in duts:
        _add_heading(document, f"Disk Performance Raw Data & Measurements ({dut_name})", level=2)
        for os_name in ("Windows", "Linux", "macOS"):
            _add_platform_artifact_table(document, data, part_root, dut_name, os_name, inches)
            document.add_paragraph("")


def _add_platform_artifact_table(
    document: Any, data: dict[str, Any], part_root: Path, dut_name: str, os_name: str, inches: Any
) -> None:
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
        _add_drive_information_artifacts_to_row(row, data, part_root, dut_name, os_name, inches)
    _center_table_column(table, 0)
    _set_table_column_widths(table, [inches(APPENDIX_OS_LABEL_WIDTH_INCHES), inches(APPENDIX_OS_ARTIFACT_WIDTH_INCHES)])


def _appendix_row_label(label: str) -> str:
    if label in MEASUREMENT_LABELS:
        return label.removesuffix(" Summary")
    return label


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
    data: dict[str, Any],
    part_root: Path,
    dut_name: str,
    os_name: str,
    inches: Any,
) -> None:
    label_cell = row_cells[0]
    artifact_cell = row_cells[1]
    artifacts = _matching_artifacts(part_root, dut_name, os_name, "Drive Information")
    image_artifacts = _image_artifacts(artifacts)
    if image_artifacts:
        _add_artifact_objects_to_cell(label_cell, image_artifacts, inches)
    non_image_names = _artifact_names(part_root, _non_image_artifacts(artifacts))
    if non_image_names:
        artifact_cell.text = non_image_names
    else:
        artifact_cell.text = ""
    _add_cdi_details_table_to_cell(artifact_cell, _cdi_details(data, dut_name), inches)


def _add_cdi_details_table_to_cell(cell: Any, cdi_details: dict[str, Any], inches: Any) -> None:
    if any(paragraph.text for paragraph in cell.paragraphs):
        cell.add_paragraph()
    table = _add_nested_table(
        cell,
        [["Field", "Value"], *[[label, _format_cdi_value(cdi_details.get(key))] for key, label in CDI_APPENDIX_FIELDS]],
        inches(APPENDIX_OS_ARTIFACT_WIDTH_INCHES),
    )
    for row in table.rows[1:]:
        if not row.cells[1].text.strip():
            _shade_cell(row.cells[1], Status.MISSING)
    _center_table_column(table, 1)


def _cdi_details(data: dict[str, Any], dut_name: str) -> dict[str, Any]:
    performance = data.get("performance")
    if not isinstance(performance, dict):
        return {}
    dut_performance = performance.get(dut_name)
    if not isinstance(dut_performance, dict):
        return {}
    windows_performance = dut_performance.get("Windows")
    if not isinstance(windows_performance, dict):
        return {}
    cdi_details = windows_performance.get("CrystalDiskInfo")
    return cdi_details if isinstance(cdi_details, dict) else {}


def _format_cdi_value(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value)


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
        utility_label = _performance_utility_label(artifact)
        utility_csv_paths = [
            csv_path for csv_path in csv_paths if _performance_utility_label(csv_path) == utility_label
        ]
        csv_path = _matching_measurement_csv(artifact, utility_csv_paths)
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


def _merge_linux_disks_access_time_row(table: Any) -> None:
    for row in table.rows:
        if row.cells[0].text == "Average Access Time" and len(row.cells) >= LINUX_DISKS_SUMMARY_COLUMN_COUNT:
            merged_cell = row.cells[1].merge(row.cells[2])
            _remove_extra_empty_paragraphs(merged_cell)
            return


def _matching_measurement_csv(image_artifact: Path, measurement_csvs: list[Path]) -> Path | None:
    same_stem = [csv_path for csv_path in measurement_csvs if csv_path.stem == image_artifact.stem]
    if same_stem:
        return same_stem[0]
    return measurement_csvs[0] if len(measurement_csvs) == 1 else None


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
    os_token = "macOS" if os_name == "macOS" else os_name
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
    if label == PERFORMANCE_LABEL:
        return _matching_performance_artifacts(matches, os_name)
    return matches if label in MEASUREMENT_LABELS else matches[:4]


def _matching_performance_artifacts(artifacts: Iterable[Path], os_name: str) -> list[Path]:
    if os_name != "Windows":
        return list(artifacts)[:4]
    selected: list[Path] = []
    for utility_label in ("ATTO", "Crystal Disk Mark"):
        utility_artifacts = [
            artifact for artifact in artifacts if _performance_utility_label(artifact) == utility_label
        ]
        selected.extend(_latest_artifacts_by_stem_pair(utility_artifacts))
    return selected


def _latest_artifacts_by_stem_pair(artifacts: list[Path]) -> list[Path]:
    image_artifacts = _image_artifacts(artifacts)
    csv_artifacts = _measurement_csvs(artifacts)
    if not image_artifacts:
        return artifacts[:2]
    latest_image = max(image_artifacts, key=_artifact_sort_key)
    selected = [latest_image]
    matching_csv = _matching_measurement_csv(latest_image, csv_artifacts)
    if matching_csv is not None:
        selected.append(matching_csv)
    return sorted(selected)


def _artifact_sort_key(artifact: Path) -> tuple[float, str]:
    try:
        mtime = artifact.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (mtime, str(artifact))


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
    if utility_label == "ATTO":
        return _atto_summary_rows(rows)
    if utility_label == "Disks":
        return _linux_disks_summary_rows(rows)
    if utility_label == "Blackmagic":
        return _read_write_summary_rows(rows)
    return rows


def _atto_summary_rows(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []
    return [rows[0], *[row for row in rows[1:] if _include_atto_io_size_row(row)]]


def _include_atto_io_size_row(row: list[str]) -> bool:
    if not row:
        return True
    size_bytes = _atto_io_size_bytes(row[0])
    if size_bytes is None:
        return True
    return size_bytes <= ATTO_MAX_IO_SIZE_BYTES and size_bytes not in ATTO_EXCLUDED_IO_SIZE_BYTES


def _atto_io_size_bytes(value: str) -> int | None:
    text = value.strip().replace(" ", "").casefold()
    units = {"kb": 1024, "mb": 1024 * 1024}
    for suffix, multiplier in units.items():
        if not text.endswith(suffix):
            continue
        number_text = text[: -len(suffix)]
        try:
            return int(float(number_text) * multiplier)
        except ValueError:
            return None
    return None


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
