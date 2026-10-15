"""Prepare a fresh Fortress L2 report from an archived L3 project's metadata."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from drive_qual.core.config import local_storage_root
from drive_qual.core.report_session import (
    TEMPLATE_NAME,
    load_report,
    report_path_for,
    sanitize_dir_name,
    save_report,
    set_current_session,
)
from drive_qual.core.storage_paths import localize_windows_path
from drive_qual.workflows.drive_info import DEFAULT_TEMPLATE, FIELDS

SOURCE_ROOT = local_storage_root() / "Done" / "L3"
PRODUCT_NAME = "Fortress L2"
COPIED_EQUIPMENT_FIELDS = (
    "scope",
    "probe_current",
    "probe_voltage",
    "windows_host",
    "usb_if_host",
    "linux_host",
    "macos_host",
)


def _source_part_number(folder: Path, report: dict[str, Any] | None) -> str:
    info = report.get("drive_info") if isinstance(report, dict) else None
    if isinstance(info, dict):
        value = info.get("apricorn_part_number")
        if isinstance(value, str) and value.strip():
            return value.strip()
    match = re.match(r"\d{2}-[0-9A-Za-z]+", folder.name)
    return match.group() if match else folder.name


def source_projects() -> list[tuple[str, Path, dict[str, Any] | None]]:
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"L3 project folder not found: {SOURCE_ROOT}")
    projects = []
    for folder in sorted((path for path in SOURCE_ROOT.iterdir() if path.is_dir()), key=lambda p: p.name.casefold()):
        source_report = folder / TEMPLATE_NAME
        report = json.loads(source_report.read_text(encoding="utf-8")) if source_report.is_file() else None
        if report is not None and not isinstance(report, dict):
            raise ValueError(f"Source report is not a JSON object: {source_report}")
        projects.append((_source_part_number(folder, report), folder, report))
    return projects


def resolve_source_project(selection: str) -> tuple[str, Path, dict[str, Any] | None]:
    key = selection.strip().casefold()
    matches = [
        project
        for project in source_projects()
        if key in {project[0].casefold(), project[1].name.casefold(), sanitize_dir_name(project[1].name).casefold()}
    ]
    if len(matches) != 1:
        if not matches:
            raise ValueError(f"No project matching {selection!r} was found in {SOURCE_ROOT}.")
        raise ValueError(f"More than one L3 project matches {selection!r}; use the full folder name.")
    return matches[0]


def list_l2_projects() -> None:
    for part_number, folder, report in source_projects():
        info = report.get("drive_info") if isinstance(report, dict) else None
        model = info.get("manufacturer_part_number") if isinstance(info, dict) else None
        if report is None:
            status = "metadata entry required"
        elif not isinstance(model, str) or model.strip().upper() in {"", "XX", "XXXX"}:
            status = "model entry required"
        else:
            status = "metadata ready"
        print(f"{part_number:20} {folder.name} ({status})")


def _fill_missing_drive_info(info: dict[str, Any], source_folder: Path) -> None:
    if info.get("apricorn_part_number") is None:
        info["apricorn_part_number"] = _source_part_number(source_folder, None)
    if source_folder.name.startswith("28-0056"):
        for field, default_value in (("manufacturer", "Samsung"), ("capacity", "4TB"), ("form_factor", "2.5")):
            if not info.get(field):
                info[field] = default_value
    for key, label in FIELDS:
        value = info.get(key)
        if (
            not isinstance(value, str)
            or not value.strip()
            or (key == "manufacturer_part_number" and value.strip().upper() in {"XX", "XXXX"})
        ):
            entered = input(f"{label} for {source_folder.name}: ").strip()
            if not entered:
                raise ValueError(f"{label} is required to prepare this L2 report.")
            info[key] = entered


def _create_l2_report(
    source_folder: Path,
    source_report: dict[str, Any] | None,
    output_path: Path,
    folder_name: str,
) -> None:
    data = json.loads(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    if source_report is not None:
        data["drive_info"] = deepcopy(source_report.get("drive_info", {}))
        source_equipment = source_report.get("equipment")
        if isinstance(source_equipment, dict):
            equipment = data["equipment"]
            for field in COPIED_EQUIPMENT_FIELDS:
                if isinstance(source_equipment.get(field), dict):
                    equipment[field] = deepcopy(source_equipment[field])
    info = data.get("drive_info")
    if not isinstance(info, dict):
        raise ValueError(f"Source drive metadata is invalid: {source_folder}")
    _fill_missing_drive_info(info, source_folder)
    if sanitize_dir_name(str(info["apricorn_part_number"])) != folder_name:
        raise ValueError(f"Source part number does not match selected project: {source_folder}")
    data["qualification_product"] = PRODUCT_NAME
    data["source_project"] = str(source_folder)
    save_report(output_path, data)
    print(f"Created Fortress L2 report from drive metadata: {output_path}")


def run_l2_setup(selection: str) -> str:
    part_number, source_folder, source_report = resolve_source_project(selection)
    folder_name = sanitize_dir_name(part_number)
    if not folder_name:
        raise ValueError(f"Invalid project part number: {part_number!r}")
    output_path = report_path_for(folder_name)
    if localize_windows_path(output_path).exists():
        existing = load_report(output_path)
        if existing.get("qualification_product") != PRODUCT_NAME:
            raise ValueError(f"Existing report is not a Fortress L2 report: {output_path}")
        print(f"Continuing existing Fortress L2 report: {output_path}")
    else:
        _create_l2_report(source_folder, source_report, output_path, folder_name)

    manufacturer = load_report(output_path).get("drive_info", {}).get("manufacturer")
    set_current_session(folder_name, manufacturer if isinstance(manufacturer, str) else None)
    return folder_name
