from __future__ import annotations

import ctypes
import importlib
import sys
import time
from typing import Any

from drive_qual.integrations.apricorn.usb_cli import find_apricorn_device
from drive_qual.platforms.windows.performance import CDI_FIELD_BY_AUTOMATION_ID


def _pywinauto_application_class() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("pywinauto is only available on Windows.")
    return importlib.import_module("pywinauto").Application


def _get_clipboard_text() -> str:
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(0):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


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


def _connect_or_start_cdi_app() -> Any:
    try:
        app = _pywinauto_application_class()(backend="uia").connect(path="DiskInfo64.exe")
        print("Connected to existing CrystalDiskInfo.")
        return app
    except Exception:
        print("Launching CrystalDiskInfo...")
        app = _pywinauto_application_class()(backend="uia").start(r"C:\Program Files\CrystalDiskInfo\DiskInfo64.exe")
        time.sleep(5)
        return app


def _focused_cdi_window(app: Any) -> Any | None:
    try:
        main_window = app.window(title_re=".*CrystalDiskInfo.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()
        print(f"Focused on: {main_window.window_text()}")
        return main_window
    except Exception as e:
        print(f"Could not find or focus CrystalDiskInfo window: {e}")
        return None


def _extract_cdi_data(main_window: Any) -> dict[str, str]:
    extracted_data: dict[str, str] = {}
    for edit in main_window.descendants(control_type="Edit"):
        auto_id = str(edit.element_info.automation_id)
        if auto_id not in CDI_FIELD_BY_AUTOMATION_ID:
            continue
        try:
            text = edit.get_value()
        except Exception:
            try:
                text = edit.window_text()
            except Exception:
                text = "ERROR"
        if text and text.strip() and text.strip() != "----":
            extracted_data[CDI_FIELD_BY_AUTOMATION_ID[auto_id]] = text.strip()
    return extracted_data


def _print_cdi_data(main_window: Any) -> None:
    import json

    try:
        print("\nExtracting data directly from Edit controls:")
        print(json.dumps(_extract_cdi_data(main_window), indent=4))
    except Exception as ex:
        print(f"Error extracting Edit controls: {ex}")


def inspect_crystal_disk_info(drive_letter: str) -> None:
    """Inspect and interact with CrystalDiskInfo GUI."""
    app = _connect_or_start_cdi_app()
    main_window = _focused_cdi_window(app)
    if main_window is None:
        return

    print(f"Searching for drive letter button: {drive_letter}")
    if _find_and_click_drive(main_window, drive_letter):
        print("Waiting 1s")
        time.sleep(1)
        _print_cdi_data(main_window)
    else:
        print(f"Could not find Button ending with '{drive_letter}:'")


if __name__ == "__main__":
    import argparse

    from drive_qual.integrations.apricorn.usb_cli import get_usb_payload, resolve_apricorn_device_by_serial

    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", help="Serial number of the device to inspect")
    args = parser.parse_args()

    dut = None
    if args.serial:
        payload = get_usb_payload()
        if payload:
            dut = resolve_apricorn_device_by_serial(payload, args.serial)
    else:
        dut = find_apricorn_device()

    if dut and dut.driveLetter:
        letter = dut.driveLetter.strip().replace(":", "").replace("\\", "")
        inspect_crystal_disk_info(letter)
    else:
        print("No Apricorn device with drive letter found.")
