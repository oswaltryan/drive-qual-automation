from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from drive_qual.core.report_session import TEMPLATE_NAME, report_path_for, resolve_folder_name
from drive_qual.core.storage_paths import localize_windows_path
from drive_qual.reports.appendix import _add_appendix
from drive_qual.reports.constants import DEFAULT_OUTPUT_NAME
from drive_qual.reports.docx_shared import _add_footer, _add_header_logo, _add_title, _load_docx_tools, _set_margins
from drive_qual.reports.evaluation import EvaluatedReport, evaluate_report
from drive_qual.reports.sections import (
    _add_compatibility_data,
    _add_compliance,
    _add_disk_performance,
    _add_drive_info,
    _add_executive_summary,
    _add_power_data,
    _add_qualification_equipment,
    _add_revision_table,
    _add_temperature_data,
)


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
    _add_header_logo(document, Inches)
    _add_footer(document)

    from docx.shared import Pt

    # Set default font for the entire document
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    _add_title(document)
    _add_revision_table(document)
    _add_executive_summary(document, evaluated)
    _add_drive_info(document, data.get("drive_info"), report_path)
    _add_qualification_equipment(document, data.get("equipment"))

    document.add_page_break()
    _add_power_data(document, data.get("power"), shade_cell)
    _add_compatibility_data(document, data.get("compatibility"), shade_cell)
    _add_disk_performance(document, data.get("performance"))
    _add_compliance(document, data.get("compliance"), data.get("reliability"), shade_cell)
    _add_temperature_data(document, data.get("temperature"), report_path.parent, shade_cell, Inches)
    document.add_page_break()
    _add_appendix(document, data, report_path.parent, Inches)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)


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
