from __future__ import annotations

import importlib
import sys
import time
from typing import Any

from drive_qual.integrations.apricorn.usb_cli import find_apricorn_device


def _pywinauto_application_class() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("pywinauto is only available on Windows.")
    return importlib.import_module("pywinauto").Application


def inspect_crystal_disk_mark(drive_letter: str) -> None:
    """Inspect CrystalDiskMark GUI."""
    try:
        app = _pywinauto_application_class()(backend="uia").connect(path="DiskMark64.exe")
        print("Connected to existing CrystalDiskMark.")
    except Exception:
        print("Launching CrystalDiskMark...")
        app = _pywinauto_application_class()(backend="uia").start(r"C:\Program Files\CrystalDiskMark8\DiskMark64.exe")
        time.sleep(5)

    try:
        main_window = app.window(title_re=".*CrystalDiskMark.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()
        print(f"Focused on: {main_window.window_text()}")
    except Exception as e:
        print(f"Could not find or focus CrystalDiskMark window: {e}")
        return

    print("\n--- Control Identifiers ---")
    main_window.print_control_identifiers()

    print(f"\nSearching for drive selection for letter: {drive_letter}")


if __name__ == "__main__":
    dut = find_apricorn_device()
    if dut and dut.driveLetter:
        letter = dut.driveLetter.strip().replace(":", "").replace("\\", "")
        inspect_crystal_disk_mark(letter)
    else:
        print("No Apricorn device with drive letter found.")
