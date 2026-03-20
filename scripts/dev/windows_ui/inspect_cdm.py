from __future__ import annotations

import time

from pywinauto import Application  # type: ignore

from drive_qual.integrations.apricorn.usb_cli import find_apricorn_device


def inspect_crystal_disk_mark(drive_letter: str) -> None:
    """Inspect CrystalDiskMark GUI."""
    try:
        app = Application(backend="uia").connect(path="DiskMark64.exe")
        print("Connected to existing CrystalDiskMark.")
    except Exception:
        print("Launching CrystalDiskMark...")
        app = Application(backend="uia").start(r"C:\Program Files\CrystalDiskMark8\DiskMark64.exe")
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
