from __future__ import annotations

import time

from pywinauto import Application  # type: ignore

from drive_qual.apricorn_usb_cli import find_apricorn_device


def inspect_atto(drive_letter: str) -> None:
    """Inspect ATTO Disk Benchmark GUI."""
    try:
        app = Application(backend="uia").connect(path="ATTODiskBenchmark.exe")
        print("Connected to existing ATTO.")
    except Exception:
        print("Launching ATTO...")
        app = Application(backend="uia").start(
            r"C:\Program Files (x86)\ATTO Technology\Disk Benchmark\ATTODiskBenchmark.exe"
        )
        time.sleep(5)

    try:
        main_window = app.window(title_re=".*ATTO Disk Benchmark.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()
        print(f"Focused on: {main_window.window_text()}")
    except Exception as e:
        print(f"Could not find or focus ATTO window: {e}")
        return

    print("\n--- Control Identifiers ---")
    main_window.print_control_identifiers()

    print(f"\nSearching for drive selection for letter: {drive_letter}")


if __name__ == "__main__":
    dut = find_apricorn_device()
    if dut and dut.driveLetter:
        letter = dut.driveLetter.strip().replace(":", "").replace("\\", "")
        inspect_atto(letter)
    else:
        print("No Apricorn device with drive letter found.")
