from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
from typing import Any

from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, localize_windows_path

REPORT_ROOT = Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT)))
CURRENT_MARKER = Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, ".current")))
TEMPLATE_NAME = "drive_qualification_report_atomic_tests.json"


def sanitize_dir_name(value: str) -> str:
    cleaned = []
    for ch in value.strip():
        if ch.isalnum() or ch in ("-", "_"):
            cleaned.append(ch)
        else:
            cleaned.append("_")
    return "".join(cleaned).strip("_")


def set_current_session(folder_name: str, product_name: str | None = None) -> None:
    marker_path = localize_windows_path(CURRENT_MARKER)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    session_data = {
        "folder": folder_name,
        "product": product_name,
    }
    marker_path.write_text(json.dumps(session_data) + "\n", encoding="utf-8")


def current_session_folder_name() -> str | None:
    marker_path = localize_windows_path(CURRENT_MARKER)
    if not marker_path.exists():
        return None

    raw_text = marker_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return None

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text

    if not isinstance(data, dict):
        return None

    folder = data.get("folder")
    if folder is None:
        return None

    folder_name = str(folder).strip()
    return folder_name or None


def resolve_folder_name(part_number: str | None) -> str:
    if part_number:
        folder_name = sanitize_dir_name(part_number)
        if not folder_name:
            raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")
        return folder_name

    current_folder = current_session_folder_name()
    if current_folder is not None:
        return current_folder

    entry = input("Apricorn Part Number (for report folder): ").strip()
    if not entry:
        raise ValueError("Apricorn Part Number is required.")
    folder_name = sanitize_dir_name(entry)
    if not folder_name:
        raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")
    return folder_name


def report_path_for(folder_name: str) -> Path:
    return Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, folder_name, TEMPLATE_NAME)))


def load_report(report_path: Path) -> dict[str, Any]:
    local_path = localize_windows_path(report_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Report template not found at {report_path}. Run drive_info_prompt.py first.")
    data = json.loads(local_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Report JSON is not an object.")
    return data


def save_report(report_path: Path, data: dict[str, Any]) -> None:
    local_path = localize_windows_path(report_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
