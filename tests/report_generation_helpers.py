from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path
from shutil import copyfile
from typing import Any, cast

EXPECTED_INLINE_IMAGE_COUNT = 1
EXPECTED_POWER_OBJECT_COUNT = 7
EXPECTED_MEDIA_FILE_COUNT = 9
EXPECTED_WINDOWS_PERFORMANCE_OBJECT_COUNT = 2
EXPECTED_COMPLIANCE_TABLE_ROW_COUNT = 3
EXPECTED_TEMPERATURE_TABLE_COLUMN_COUNT = 4
EXPECTED_TEMPERATURE_TABLE_ROW_COUNT = 12
EXPECTED_TEMPERATURE_CHART_LEADING_BREAKS = 3
WINDOWS_PERFORMANCE_BLANK_LINES_BEFORE_FIRST_OBJECT = 2
WINDOWS_PERFORMANCE_BLANK_LINES_BETWEEN_OBJECTS = 13
MAX_WORD_OBJECT_ID = 2_000_000_000


def _assert_appendix_object_layout(document: Any, output_path: Path) -> None:
    assert len(document.inline_shapes) == EXPECTED_INLINE_IMAGE_COUNT
    assert _embedded_object_count(output_path) == EXPECTED_POWER_OBJECT_COUNT
    assert _media_file_count(output_path) == EXPECTED_MEDIA_FILE_COUNT
    _assert_appendix_object_cells(document)
    _assert_appendix_spacing(document)
    _assert_embedded_object_payloads(output_path)


def _assert_appendix_object_cells(document: Any) -> None:
    assert _table_cell_object_count(document.tables[6], 1, 0) == 1
    assert _table_cell_object_count(document.tables[6], 2, 0) == 1
    assert _table_cell_object_count(document.tables[6], 3, 0) == EXPECTED_WINDOWS_PERFORMANCE_OBJECT_COUNT
    assert _table_cell_object_count(document.tables[6], 4, 0) == 1
    assert _table_cell_object_count(document.tables[7], 3, 0) == 1
    assert _table_cell_object_count(document.tables[8], 3, 0) == 1
    assert _table_cell_object_count(document.tables[6], 1, 1) == 0
    assert _table_cell_object_count(document.tables[6], 2, 1) == 0
    assert _table_cell_object_count(document.tables[6], 3, 1) == 0
    assert _table_cell_object_count(document.tables[6], 4, 1) == 0


def _assert_appendix_spacing(document: Any) -> None:
    assert _cell_paragraph_texts(document.tables[6], 1, 0)[:2] == ["Inrush", ""]
    assert _cell_paragraph_texts(document.tables[6], 2, 0)[:2] == ["Max IO", ""]
    assert _table_column_paragraphs_are_centered(document.tables[6], 0)
    assert _table_column_paragraphs_are_centered(document.tables[7], 0)
    assert _table_column_paragraphs_are_centered(document.tables[8], 0)
    assert _cell_child_tags(document.tables[6], 1, 1) == ["tcPr", "p", "tbl", "p"]
    assert _cell_child_tags(document.tables[6], 2, 1) == ["tcPr", "p", "tbl", "p"]
    assert _empty_cell_paragraph_line_sizes(document.tables[6], 1, 1) == ["20", "20"]
    assert _empty_cell_paragraph_line_sizes(document.tables[6], 2, 1) == ["20", "20"]
    assert _cell_child_tags(document.tables[6], 3, 1) == ["tcPr", "p", "tbl", "p", "p", "tbl", "p"]
    assert _empty_cell_paragraph_line_sizes(document.tables[6], 3, 1) == ["20", "20"]
    assert (
        _cell_paragraph_texts(document.tables[6], 3, 0)[1:3]
        == [""] * WINDOWS_PERFORMANCE_BLANK_LINES_BEFORE_FIRST_OBJECT
    )
    assert (
        _performance_object_gap(document.tables[6], first_object_index=3)
        == WINDOWS_PERFORMANCE_BLANK_LINES_BETWEEN_OBJECTS
    )
    assert _table_cell_drawing_count(document.tables[6], 2, 1) == 0
    assert _table_cell_drawing_count(document.tables[6], 3, 1) == 0


def _assert_embedded_object_payloads(output_path: Path) -> None:
    assert _embedded_object_payload_names(output_path) == [
        "Padlock DT Inrush Summary.png",
        "Padlock DT Max IO Summary.png",
        "Padlock DT ATTO Performance.png",
        "Padlock DT CrystalDiskMark Performance.png",
        "Padlock DT CrystalDiskInfo Drive Information.png",
        "Padlock DT Disks Performance.png",
        "Padlock DT Blackmagic Performance.png",
    ]
    shape_numbers = _embedded_object_shape_numbers(output_path)
    assert len(shape_numbers) == EXPECTED_POWER_OBJECT_COUNT
    assert shape_numbers == list(range(shape_numbers[0], shape_numbers[0] + (2 * EXPECTED_POWER_OBJECT_COUNT), 2))
    assert all(object_id < MAX_WORD_OBJECT_ID for object_id in _embedded_object_ids(output_path))
    _assert_footer_text(output_path)


def _table_headers(document: Any) -> list[str]:
    return [" | ".join(cell.text for cell in table.rows[0].cells) for table in document.tables]


def _assert_temperature_table_shape(table: Any) -> None:
    assert len(table.columns) == EXPECTED_TEMPERATURE_TABLE_COLUMN_COUNT
    assert len(table.rows) == EXPECTED_TEMPERATURE_TABLE_ROW_COUNT
    assert [cell.text for cell in table.rows[0].cells] == ["Chart", "Temperature", "Read MB/s", "Write MB/s"]
    assert _table_columns_are_centered(table, range(EXPECTED_TEMPERATURE_TABLE_COLUMN_COUNT))
    assert _table_cell_drawing_count(table, 1, 0) == 1
    assert _table_cell_line_break_count(table, 1, 0) == EXPECTED_TEMPERATURE_CHART_LEADING_BREAKS
    assert [row.cells[1].text for row in table.rows[1:]] == [
        "-40°C",
        "-30°C",
        "-20°C",
        "-10°C",
        "0°C",
        "10°C",
        "20°C",
        "30°C",
        "40°C",
        "50°C",
        "60°C",
    ]
    assert table.rows[1].cells[2].text == "107.59"
    assert table.rows[1].cells[3].text == "109.31"


def _assert_result_table_alignment(document: Any) -> None:
    assert _table_columns_are_centered(document.tables[1], range(1, 4))
    assert _table_columns_are_centered(document.tables[2], range(1, 4))
    assert _table_columns_are_centered(document.tables[3], range(1, 7))
    assert len(document.tables[4].rows) == EXPECTED_COMPLIANCE_TABLE_ROW_COUNT
    assert _table_columns_are_centered(document.tables[4], range(1, 3))
    _assert_temperature_table_shape(document.tables[5])


def _assert_linux_disks_summary_table(table: Any) -> None:
    assert _nested_table_physical_rows(table.rows[3].cells[1]) == [
        ["Disks", "", ""],
        ["Metric", "Read", "Write"],
        ["Minimum Rate", "111.1 MB/s", "210.0 MB/s"],
        ["Average Rate", "123.4 MB/s", "234.5 MB/s"],
        ["Maximum Rate", "130.0 MB/s", "240.0 MB/s"],
        ["Average Access Time", "0.12 ms"],
    ]
    assert _nested_table_physical_row_grid_spans(table.rows[3].cells[1], 5) == [1, 2]
    assert _nested_table_physical_row_paragraph_texts(table.rows[3].cells[1], 5) == [
        ["Average Access Time"],
        ["0.12 ms"],
    ]
    assert _table_columns_are_centered(table.rows[3].cells[1].tables[0], _value_column_indexes)


def _document_text(document: Any) -> str:
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    return text + "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)


def _paragraph_has_page_break(paragraph: Any) -> bool:
    return bool(paragraph._p.xpath(".//w:br[@w:type='page']"))


def _heading_starts_after_page_break(document: Any, heading_text: str) -> bool:
    heading_index = next(index for index, paragraph in enumerate(document.paragraphs) if paragraph.text == heading_text)
    return heading_index > 0 and _paragraph_has_page_break(document.paragraphs[heading_index - 1])


def _assert_removed_headings_are_absent(headings: list[str]) -> None:
    for heading in (
        "Drive Qualification Result",
        "Datasheet",
        "Appendix",
        "Disk Performance Raw Data & Screenshots",
        "Notes and Considerations",
    ):
        assert heading not in headings


def _appendix_headings(headings: list[str]) -> list[str]:
    return [heading for heading in headings if heading.startswith("Disk Performance Raw Data & Measurements (")]


def _assert_reordered_sections(document: Any, headings: list[str], dut_name: str) -> None:
    measurement_heading = f"Disk Performance Raw Data & Measurements ({dut_name})"
    assert headings.index("Executive Summary") < headings.index("Drive Info")
    assert headings.index("Compliance/Reliability Test") < headings.index("Temperature Data")
    assert headings.index("Temperature Data") < headings.index(measurement_heading)
    assert measurement_heading in headings
    assert _heading_starts_after_page_break(document, measurement_heading)


def _table_contains_text(table: Any, text: str) -> bool:
    return any(text in cell.text for row in table.rows for cell in row.cells)


def _write_png(path: Path) -> None:
    from PIL import Image

    seed = sum(path.name.encode("utf-8"))
    image = Image.new("RGB", (320, 320))
    pixels = [
        ((x * 13 + y * 7 + seed) % 256, (x * 5 + y * 17 + seed) % 256, (x * y + seed) % 256)
        for y in range(320)
        for x in range(320)
    ]
    image.putdata(cast(Any, pixels))
    image.save(path)


def _prepare_report_generation_shape_fixture(source_root: Path) -> None:
    part_dir = source_root / "69-420"
    temperature_dir = part_dir / "Temperature"
    part_dir.mkdir(parents=True, exist_ok=True)
    temperature_dir.mkdir(parents=True, exist_ok=True)
    report_path = part_dir / "drive_qualification_report_atomic_tests.json"
    report_path.write_text(json.dumps(_report_payload()), encoding="utf-8")
    _write_temperature_test_artifact(temperature_dir)


def _prepare_report_generation_images_fixture(source_root: Path) -> Path:
    part_dir = source_root / "69-420"
    temperature_dir = part_dir / "Temperature"
    windows_dir = part_dir / "Windows"
    linux_dir = part_dir / "Linux"
    macos_dir = part_dir / "macOS"
    windows_dir.mkdir(parents=True, exist_ok=True)
    linux_dir.mkdir(parents=True, exist_ok=True)
    macos_dir.mkdir(parents=True, exist_ok=True)
    temperature_dir.mkdir(parents=True, exist_ok=True)
    report_path = part_dir / "drive_qualification_report_atomic_tests.json"
    report_path.write_text(json.dumps(_report_payload()), encoding="utf-8")
    _write_appendix_test_artifacts(windows_dir, linux_dir, macos_dir)
    _write_temperature_test_artifact(temperature_dir)
    return windows_dir


def _write_appendix_test_artifacts(windows_dir: Path, linux_dir: Path, macos_dir: Path) -> None:
    _write_png(windows_dir / "Padlock DT Inrush Summary.png")
    _write_measurement_csv(windows_dir / "Padlock DT Inrush Summary.csv")
    _write_png(windows_dir / "Padlock DT Max IO Summary.png")
    _write_measurement_csv(windows_dir / "Padlock DT Max IO Summary.csv")
    old_atto_png = windows_dir / "Padlock DT ATTO Performance 20260101.png"
    old_atto_csv = windows_dir / "Padlock DT ATTO Performance 20260101.csv"
    _write_png(old_atto_png)
    _write_atto_performance_csv(old_atto_csv)
    os.utime(old_atto_png, (1, 1))
    os.utime(old_atto_csv, (1, 1))
    _write_png(windows_dir / "Padlock DT ATTO Performance.png")
    _write_atto_performance_csv(windows_dir / "Padlock DT ATTO Performance.csv")
    _write_png(windows_dir / "Padlock DT CrystalDiskMark Performance.png")
    (windows_dir / "._Padlock DT CrystalDiskMark Performance.png").write_text("not a png", encoding="utf-8")
    _write_performance_csv(windows_dir / "Padlock DT CrystalDiskMark Performance 20260101.csv")
    _write_png(windows_dir / "Padlock DT CrystalDiskInfo Drive Information.png")
    (linux_dir / "Padlock DT Max IO Summary.csv").write_text("time,current\n", encoding="utf-8")
    _write_png(linux_dir / "Padlock DT Disks Performance.png")
    _write_linux_disks_performance_csv(linux_dir / "Padlock DT Disks Performance.csv")
    _write_png(macos_dir / "Padlock DT Blackmagic Performance.png")
    _write_performance_csv(macos_dir / "Padlock DT Blackmagic Performance.csv")


def _write_temperature_test_artifact(temperature_dir: Path) -> None:
    source_image = Path(
        "tests/.tmp/test_report_generation_images/69-420/Windows/Padlock DT CrystalDiskInfo Drive Information.png"
    )
    copyfile(source_image, temperature_dir / "Padlock DT Temperature Data.png")


def _write_measurement_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "TekScope,Version 2.0.3",
                "",
                "Measurement Results",
                "Name,Measurement,Label,Source,Mean',Accum-Mean,Accum-Min,Accum-Max,Accum-Pk-Pk,"
                "Accum-Std Dev,Accum-Population",
                'Meas1,Maximum,Maximum," Ch 4 ",448.62 mA,448.48 mA,444.94 mA,453.56 mA,8.6250 mA,1.5484 mA,132',
                'Meas3,RMS,RMS," Ch 4 ",258.70 mA,258.60 mA,258.04 mA,259.17 mA,1.1256 mA,212.51 uA,132',
                'Meas9,Peak,Peak," Ch 4 ",999.00 mA,999.00 mA,998.00 mA,1000.00 mA,2.0000 mA,1.0000 mA,132',
            ]
        ),
        encoding="utf-8",
    )


def _write_performance_csv(path: Path) -> None:
    path.write_text("Metric,Value\nRead MB/s,350.93\nWrite MB/s,345.04\n", encoding="utf-8")


def _write_atto_performance_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "I/O Size,Write,Read",
                "4KB,120.00,130.00",
                "32KB,220.00,230.00",
                "64KB,240.00,250.00",
                "128KB,260.00,270.00",
                "512KB,300.00,310.00",
                "1MB,320.00,330.00",
                "2MB,340.00,350.00",
                "4MB,360.00,370.00",
                "8MB,380.00,390.00",
            ]
        ),
        encoding="utf-8",
    )


def _write_linux_disks_performance_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Metric,Value",
                "Minimum Read Rate,111.1 MB/s",
                "Average Read Rate,123.4 MB/s",
                "Maximum Read Rate,130.0 MB/s",
                "Minimum Write Rate,210.0 MB/s",
                "Average Write Rate,234.5 MB/s",
                "Maximum Write Rate,240.0 MB/s",
                "Average Access Time,0.12 ms",
                "Last Benchmark,2026-04-29",
            ]
        ),
        encoding="utf-8",
    )


def _table_cell_drawing_count(document_table: Any, row_index: int, cell_index: int) -> int:
    return len(_cell_xml(document_table, row_index, cell_index).xpath(".//w:drawing"))


def _table_cell_line_break_count(document_table: Any, row_index: int, cell_index: int) -> int:
    return len(_cell_xml(document_table, row_index, cell_index).xpath(".//w:br[not(@w:type='page')]"))


def _table_cell_object_count(document_table: Any, row_index: int, cell_index: int) -> int:
    return len(_cell_xml(document_table, row_index, cell_index).xpath(".//w:object"))


def _cell_xml(document_table: Any, row_index: int, cell_index: int) -> Any:
    return document_table.rows[row_index].cells[cell_index]._tc


def _cell_child_tags(document_table: Any, row_index: int, cell_index: int) -> list[str]:
    return [child.tag.rsplit("}", 1)[-1] for child in _cell_xml(document_table, row_index, cell_index)]


def _empty_cell_paragraph_line_sizes(document_table: Any, row_index: int, cell_index: int) -> list[str]:
    return [
        spacing.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}line")
        for paragraph in document_table.rows[row_index].cells[cell_index].paragraphs
        if not paragraph.text
        for spacing in paragraph._p.xpath("./w:pPr/w:spacing")
    ]


def _cell_paragraph_texts(document_table: Any, row_index: int, cell_index: int) -> list[str]:
    return [paragraph.text for paragraph in document_table.rows[row_index].cells[cell_index].paragraphs]


def _cell_paragraph_alignments(document_table: Any, row_index: int, cell_index: int) -> list[int | None]:
    return [paragraph.alignment for paragraph in document_table.rows[row_index].cells[cell_index].paragraphs]


def _table_column_paragraphs_are_centered(document_table: Any, column_index: int) -> bool:
    return all(
        paragraph.alignment == 1 for row in document_table.rows for paragraph in row.cells[column_index].paragraphs
    )


def _table_columns_are_centered(
    document_table: Any, column_indexes: Iterable[int] | Callable[[Any], Iterable[int]]
) -> bool:
    indexes = column_indexes(document_table) if callable(column_indexes) else column_indexes
    return all(_table_column_paragraphs_are_centered(document_table, column_index) for column_index in indexes)


def _value_column_indexes(document_table: Any) -> range:
    return range(1, min(3, len(document_table.columns)))


def _performance_object_gap(document_table: Any, *, first_object_index: int) -> int:
    paragraphs = document_table.rows[3].cells[0].paragraphs
    second_object_index = next(
        index for index in range(first_object_index + 1, len(paragraphs)) if _paragraph_object_count(paragraphs[index])
    )
    return second_object_index - first_object_index - 1


def _paragraph_object_count(paragraph: Any) -> int:
    return len(paragraph._p.xpath(".//w:object"))


def _embedded_object_count(path: Path) -> int:
    with zipfile.ZipFile(path) as docx_zip:
        return len([name for name in docx_zip.namelist() if name.startswith("word/embeddings/oleObject")])


def _media_file_count(path: Path) -> int:
    with zipfile.ZipFile(path) as docx_zip:
        return len([name for name in docx_zip.namelist() if name.startswith("word/media/")])


def _embedded_object_payload_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as docx_zip:
        object_names = [name for name in docx_zip.namelist() if name.startswith("word/embeddings/oleObject")]
        return [_ole10_native_label(docx_zip.read(name)) for name in object_names]


def _embedded_object_shape_ids(path: Path) -> list[str]:
    return [match.split('"')[1] for match in _embedded_object_xml_matches(path, 'ShapeID="')]


def _embedded_object_shape_numbers(path: Path) -> list[int]:
    return [int(shape_id.removeprefix("_x0000_i")) for shape_id in _embedded_object_shape_ids(path)]


def _embedded_object_ids(path: Path) -> list[int]:
    return [int(match.split('"')[1].removeprefix("_")) for match in _embedded_object_xml_matches(path, 'ObjectID="')]


def _embedded_object_xml_matches(path: Path, marker: str) -> list[str]:
    with zipfile.ZipFile(path) as docx_zip:
        xml = docx_zip.read("word/document.xml").decode("utf-8")
    return [token for token in xml.split() if token.startswith(marker)]


def _assert_footer_text(path: Path) -> None:
    with zipfile.ZipFile(path) as docx_zip:
        footer_xml = "\n".join(
            docx_zip.read(name).decode("utf-8") for name in docx_zip.namelist() if name.startswith("word/footer")
        )
    assert "Drive Qualification Report.docx" in footer_xml
    assert "Apricorn Confidential" in footer_xml
    assert '<w:b/><w:color w:val="FF0000"/>' in footer_xml
    assert " PAGE " in footer_xml
    assert " NUMPAGES " in footer_xml


def _ole10_native_label(blob: bytes) -> str:
    marker = "\x01Ole10Native".encode("utf-16le")
    directory_offset = blob.find(marker)
    assert directory_offset >= 0
    stream_start = int.from_bytes(blob[directory_offset + 116 : directory_offset + 120], "little", signed=True)
    sector_offset = (stream_start + 1) * 512
    stream = blob[sector_offset : sector_offset + 512]
    label_start = 6
    label_end = stream.index(b"\x00", label_start)
    return stream[label_start:label_end].decode("utf-8")


def _nested_table_rows(cell: Any) -> list[list[str]]:
    table = cell.tables[0]
    return [[nested_cell.text for nested_cell in row.cells] for row in table.rows]


def _nested_tables_rows(cell: Any) -> list[list[str]]:
    return [[nested_cell.text for nested_cell in row.cells] for table in cell.tables for row in table.rows]


def _nested_table_physical_rows(cell: Any) -> list[list[str]]:
    table = cell.tables[0]
    return [[_tc_text(tc) for tc in row._tr.tc_lst] for row in table.rows]


def _nested_table_physical_row_grid_spans(cell: Any, row_index: int) -> list[int]:
    table = cell.tables[0]
    return [_tc_grid_span(tc) for tc in table.rows[row_index]._tr.tc_lst]


def _nested_table_physical_row_paragraph_texts(cell: Any, row_index: int) -> list[list[str]]:
    table = cell.tables[0]
    return [[_paragraph_text(paragraph) for paragraph in tc.xpath("./w:p")] for tc in table.rows[row_index]._tr.tc_lst]


def _paragraph_text(paragraph: Any) -> str:
    return "".join(paragraph.xpath(".//w:t/text()"))


def _tc_text(tc: Any) -> str:
    return "".join(tc.xpath(".//w:t/text()"))


def _tc_grid_span(tc: Any) -> int:
    spans = tc.xpath("./w:tcPr/w:gridSpan")
    if not spans:
        return 1
    return int(spans[0].get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"))


def _nested_table_columns_evenly_fill_parent(cell: Any) -> bool:
    widths = [nested_cell.width for nested_cell in cell.tables[0].rows[0].cells]
    return all(width is not None for width in widths) and len(set(widths)) == 1 and sum(widths) < cell.width


def _first_column_is_narrower_than_artifact_column(table: Any) -> bool:
    first_width = table.rows[0].cells[0].width
    second_width = table.rows[0].cells[1].width
    return first_width is not None and second_width is not None and first_width * 2 <= second_width


def _has_paragraph_between_tables(document: Any, first_header: str, second_header: str) -> bool:
    labels = _body_block_labels(document)
    first_index = labels.index(f"table:{first_header}")
    second_index = labels.index(f"table:{second_header}")
    return "paragraph" in labels[first_index + 1 : second_index]


def _body_block_labels(document: Any) -> list[str]:
    table_headers = iter(" | ".join(cell.text for cell in table.rows[0].cells) for table in document.tables)
    labels: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}tbl"):
            labels.append(f"table:{next(table_headers)}")
        elif child.tag.endswith("}p"):
            labels.append("paragraph")
    return labels


def _report_payload() -> dict[str, Any]:
    return {
        "drive_info": {
            "apricorn_part_number": "69-420",
            "manufacturer": "Apricorn",
            "manufacturer_part_number": "ABC123",
            "serial_number": "SER123",
            "capacity": "1TB",
            "firmware": "1.0",
            "form_factor": "2.5",
            "interface": "USB",
            "technology": "SSD",
        },
        "equipment": {
            "scope": {"model": "Tektronix MSO54", "version": "2.0.3", "serial_number": "B013976"},
            "probe_current": {"model": "TCP202A", "channel": "4", "serial_number": "C004510"},
            "probe_voltage": {"model": "TPP0500B", "channel": "2", "serial_number": "C166742"},
            "windows_host": {
                "hardware": "ASUS PRIME Z270-K, i5-7400K",
                "os_version": "Windows 10",
                "software": [{"name": "CrystalDiskMark", "version": "7.0.0"}, {"name": "ATTO", "version": "4.0"}],
            },
            "linux_host": {"hardware": "NUC", "os_version": "Ubuntu", "software": [{"name": "Disks", "version": None}]},
            "macos_host": {
                "hardware": "Mac Mini",
                "os_version": "OS 15",
                "software": [{"name": "Blackmagic Disk Speed Test", "version": "4.2"}],
            },
            "dut": {"Padlock DT": {"serial_number": "DUT123"}},
        },
        "compatibility": {
            "recognized_by_os": {"linux": True, "macos": True, "windows": True},
            "hot_pluggable": {"linux": True, "macos": True, "windows": True},
        },
        "power": {
            "Padlock DT": {
                "max_inrush_current_5v": {"linux": 700, "macos": 800, "windows": 750},
                "max_read_write_current_5v": {"linux": 850, "macos": 860, "windows": 870},
                "rms_read_write_current_5v": {"linux": 900, "macos": 510, "windows": 520},
            }
        },
        "performance": {
            "Padlock DT": {
                "Windows": {
                    "CrystalDiskInfo": {
                        "screenshot": True,
                        "model": "Apricorn Padlock DT",
                        "transfer_mode": "SATA/600 | SATA/600",
                        "standard": "ACS-4",
                        "features": "S.M.A.R.T., NCQ, TRIM",
                        "rotation_rate": "---- (SSD)",
                        "power_on_count": "12 count",
                        "power_on_hours": "34 hours",
                    },
                    "CrystalDiskMark": {"read": 350.93, "write": 345.04},
                    "ATTO": {"read": 334.95, "write": 318.74},
                },
                "macOS": {"Blackmagic Disk Speed Test": {"read": 293.2, "write": 844.2}},
            }
        },
        "temperature": {"Padlock DT": {"performance": {"-40c": {"read_mb_s": 107.59, "write_mb_s": 109.31}}}},
        "compliance": {
            "usb_if_msc_iterations": 3,
            "usb_if_msc_result": "Pass",
            "disk_tester_reliability_iterations": 3,
            "disk_tester_reliability_result": "Pass",
        },
    }
