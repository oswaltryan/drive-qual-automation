from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOGS_DIR = Path("logs")
CURRENT_MARKER = LOGS_DIR / ".current"
TEMPLATE_NAME = "drive_qualification_report_atomic_tests.json"


def sanitize_dir_name(value: str) -> str:
    cleaned = []
    for ch in value.strip():
        if ch.isalnum() or ch in ("-", "_"):
            cleaned.append(ch)
        else:
            cleaned.append("_")
    return "".join(cleaned).strip("_")


def set_current_session(folder_name: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_MARKER.write_text(f"{folder_name}\n", encoding="utf-8")


def resolve_folder_name(part_number: str | None) -> str:
    if part_number:
        folder_name = sanitize_dir_name(part_number)
        if not folder_name:
            raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")
        return folder_name
    if CURRENT_MARKER.exists():
        return CURRENT_MARKER.read_text(encoding="utf-8").strip()
    entry = input("Apricorn Part Number (for logs folder): ").strip()
    if not entry:
        raise ValueError("Apricorn Part Number is required.")
    folder_name = sanitize_dir_name(entry)
    if not folder_name:
        raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")
    return folder_name


def report_path_for(folder_name: str) -> Path:
    return LOGS_DIR / folder_name / TEMPLATE_NAME


def load_report(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        raise FileNotFoundError(f"Report template not found at {report_path}. Run drive_info_prompt.py first.")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Report JSON is not an object.")
    return data


def save_report(report_path: Path, data: dict[str, Any]) -> None:
    report_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
