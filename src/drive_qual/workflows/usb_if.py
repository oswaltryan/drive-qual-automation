from __future__ import annotations

import sys

from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.storage_paths import localize_windows_path
from drive_qual.core.usb_if import update_usb_if_compliance, usb_if_artifact_dir


def run_usb_if_step(part_number: str | None = None, iterations: int = 3) -> None:
    if sys.platform != "win32":
        print("Skipping USB-IF MSC workflow: usb_if is Windows-only.")
        return

    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    artifact_dir = localize_windows_path(usb_if_artifact_dir(folder_name))

    from drive_qual.platforms.windows.usb_if import run_usb_if_msc

    result = run_usb_if_msc(
        part_number=folder_name,
        artifact_dir=artifact_dir,
        iterations=iterations,
    )

    data = load_report(report_path)
    update_usb_if_compliance(data, result)
    save_report(report_path, data)
    print(f"Updated USB-IF MSC compliance results in {report_path}")
