from __future__ import annotations

import time
from typing import Any

from pywinauto import Application  # type: ignore

from drive_qual.apricorn_usb_cli import find_apricorn_device


def _find_and_click_drive(main_window: Any, drive_letter: str) -> bool:
    """Find and click the drive button in CDI."""
    buttons = main_window.descendants(control_type="Button")
    for btn in buttons:
        title = btn.window_text()
        if title and title.strip().endswith(f"{drive_letter}:"):
            print(f"Found drive button: {title.replace('\r\n', ' ')}")
            btn.click_input()
            return True
    return False


def inspect_crystal_disk_info(drive_letter: str) -> None:
    """Inspect and interact with CrystalDiskInfo GUI."""
    try:
        app = Application(backend="uia").connect(path="DiskInfo64.exe")
        print("Connected to existing CrystalDiskInfo.")
    except Exception:
        print("Launching CrystalDiskInfo...")
        app = Application(backend="uia").start(r"C:\Program Files\CrystalDiskInfo\DiskInfo64.exe")
        time.sleep(5)

    try:
        main_window = app.window(title_re=".*CrystalDiskInfo.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()
        print(f"Focused on: {main_window.window_text()}")
    except Exception as e:
        print(f"Could not find or focus CrystalDiskInfo window: {e}")
        return

    print("\n--- Control Identifiers ---")
    # main_window.print_control_identifiers()

    print(f"Searching for drive letter button: {drive_letter}")
    if not _find_and_click_drive(main_window, drive_letter):
        print(f"Could not find Button ending with '{drive_letter}:'")


if __name__ == "__main__":
    dut = find_apricorn_device()
    if dut and dut.driveLetter:
        letter = dut.driveLetter.strip().replace(":", "").replace("\\", "")
        inspect_crystal_disk_info(letter)
    else:
        print("No Apricorn device with drive letter found.")
