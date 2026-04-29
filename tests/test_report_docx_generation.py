from __future__ import annotations

import importlib
from pathlib import Path

import report_generation_helpers as h


def test_generate_report_docx_matches_reference_section_shape() -> None:
    from docx import Document

    source_root = Path("tests/.tmp/test_report_generation_shape")
    h._prepare_report_generation_shape_fixture(source_root)

    module = importlib.import_module("drive_qual.reports.generate")
    output_path = module.generate_report_docx(part_number="69-420", source_root=source_root)
    document = Document(output_path)
    headings = [
        paragraph.text
        for paragraph in document.paragraphs
        if paragraph.style is not None and paragraph.style.name.startswith("Heading")
    ]
    table_headers = [" | ".join(cell.text for cell in table.rows[0].cells) for table in document.tables]
    expected_base_headings = [
        "Drive Qualification Report",
        "Executive Summary",
        "Drive Info",
        "Qualification Equipment",
        "Power Data",
        "Compatibility Data",
        "Disk Performance",
        "Compliance/Reliability Test",
        "Temperature Data",
    ]
    assert headings[: len(expected_base_headings)] == expected_base_headings
    assert h._appendix_headings(headings) == ["Disk Performance Raw Data & Measurements (Padlock DT)"]
    assert "Power Data" in headings
    assert "Compatibility Data" in headings
    assert "Disk Performance" in headings
    h._assert_reordered_sections(document, headings, "Padlock DT")
    h._assert_removed_headings_are_absent(headings)
    assert h._heading_starts_after_page_break(document, "Power Data")
    assert table_headers[:6] == [
        "Revision | Name | Date | Description",
        "Test | Linux | macOS | Windows",
        "Test | Linux | macOS | Windows",
        "DUT | CDM-R | CDM-W | BM(R) | BM(W) | ATTO-R | ATTO-W",
        "Program | Iterations/Loops | Result",
        "Chart | Temperature | Read MB/s | Write MB/s",
    ]
    assert h._table_contains_text(document.tables[2], "Native Disk Utility")
    assert not h._table_contains_text(document.tables[2], "Appears in Device Manager & Disk Management")
    assert h._table_contains_text(document.tables[4], "USB-IF Mass Storage Compliance")
    assert not h._table_contains_text(document.tables[4], "USB-IF Mass Storage Compliance (MSC)")
    summary = next(
        paragraph for paragraph in document.paragraphs if paragraph.text.startswith("Results require review")
    )
    assert summary.text == "Results require review in sections: Power Data."
    assert [run.text for run in summary.runs if run.bold] == ["Power Data"]
    h._assert_result_table_alignment(document)
    assert "Artifact | Path" not in table_headers
    assert h._has_paragraph_between_tables(document, "Windows | ", "Linux | ")
    assert h._has_paragraph_between_tables(document, "Linux | ", "macOS | ")
    assert h._first_column_is_narrower_than_artifact_column(document.tables[6])


def test_generate_report_docx_embeds_appendix_images_instead_of_paths() -> None:
    from docx import Document

    source_root = Path("tests/.tmp/test_report_generation_images")
    windows_dir = h._prepare_report_generation_images_fixture(source_root)

    module = importlib.import_module("drive_qual.reports.generate")
    output_path = module.generate_report_docx(part_number="69-420", source_root=source_root)
    document = Document(output_path)

    h._assert_appendix_object_layout(document, output_path)
    assert "Artifact | Path" not in h._table_headers(document)
    assert str(windows_dir) not in h._document_text(document)
    assert h._nested_table_rows(document.tables[6].rows[2].cells[1]) == [
        ["Name", "Measurement", "Accum-Mean", "Accum-Min", "Accum-Max"],
        ["Meas1", "Maximum", "448.48 mA", "444.94 mA", "453.56 mA"],
        ["Meas3", "RMS", "258.60 mA", "258.04 mA", "259.17 mA"],
    ]
    assert h._nested_table_columns_evenly_fill_parent(document.tables[6].rows[2].cells[1])
    assert h._table_columns_are_centered(document.tables[6].rows[2].cells[1].tables[0], range(2, 5))
    assert h._nested_tables_rows(document.tables[6].rows[3].cells[1]) == [
        ["ATTO", ""],
        ["Metric", "Value"],
        ["Read MB/s", "350.93"],
        ["Write MB/s", "345.04"],
        ["Crystal Disk Mark", ""],
        ["Metric", "Value"],
        ["Read MB/s", "350.93"],
        ["Write MB/s", "345.04"],
    ]
    assert h._table_columns_are_centered(document.tables[6].rows[3].cells[1].tables[0], h._value_column_indexes)
    assert h._table_columns_are_centered(document.tables[6].rows[3].cells[1].tables[1], h._value_column_indexes)
    assert document.tables[7].rows[2].cells[1].text == "Linux\\Padlock DT Max IO Summary.csv"
    h._assert_linux_disks_summary_table(document.tables[7])
    assert h._nested_tables_rows(document.tables[8].rows[3].cells[1]) == [
        ["Blackmagic", "", ""],
        ["Metric", "Read", "Write"],
        ["Speed", "350.93", "345.04"],
    ]
    assert h._table_columns_are_centered(document.tables[8].rows[3].cells[1].tables[0], h._value_column_indexes)
