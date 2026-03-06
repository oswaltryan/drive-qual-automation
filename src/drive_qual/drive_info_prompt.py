from __future__ import annotations

import json
from pathlib import Path

from drive_qual.report_session import report_path_for, sanitize_dir_name, save_report, set_current_session

DEFAULT_TEMPLATE = Path("tests/drive_qualification_report_atomic_tests.json")

FIELDS: tuple[tuple[str, str], ...] = (
    ("apricorn_part_number", "Apricorn Part Number"),
    ("manufacturer", "Manufacturer"),
    ("manufacturer_part_number", "Manufacturer Part Number"),
    ("capacity", "Capacity"),
    ("firmware", "Firmware"),
    ("form_factor", "Form Factor"),
    ("interface", "Interface"),
    ("technology", "Technology"),
)


def _prompt(label: str, current: str) -> str:
    if current:
        entry = input(f"{label} [{current}]: ").strip()
        return entry or current
    return input(f"{label}: ").strip()


def run_drive_info_prompt() -> None:
    template_path = DEFAULT_TEMPLATE
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    data = json.loads(template_path.read_text(encoding="utf-8"))
    drive_info = data.get("drive_info")
    if not isinstance(drive_info, dict):
        raise ValueError("Missing or invalid 'drive_info' section in template.")

    for key, label in FIELDS:
        current = drive_info.get(key, "")
        if not isinstance(current, str):
            current = ""
        drive_info[key] = _prompt(label, current)

    part_number = drive_info.get("apricorn_part_number", "").strip()
    if not part_number:
        raise ValueError("Apricorn Part Number is required to create the output directory.")

    folder_name = sanitize_dir_name(part_number)
    if not folder_name:
        raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")

    output_path = report_path_for(folder_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_report(output_path, data)
    set_current_session(folder_name)
    print(f"Wrote updated template to {output_path}")
    print(f"Set current session to {folder_name}")


if __name__ == "__main__":
    run_drive_info_prompt()
