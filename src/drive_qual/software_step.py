from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from PIL import ImageGrab  # type: ignore
from pywinauto import Application  # type: ignore

from drive_qual.apricorn_usb_cli import ApricornDevice, find_apricorn_device
from drive_qual.io_utils import mk_dir
from drive_qual.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.storage_paths import artifact_dir

CRYSTAL_DISK_INFO_PATH = Path("C:/Program Files/CrystalDiskInfo/DiskInfo64.exe")


def _find_drive_button(main_window: Any, drive_letter: str) -> Any | None:
    """Find the CDI drive button for a specific drive letter."""
    buttons = main_window.descendants(control_type="Button")
    for btn in buttons:
        title = btn.window_text()
        if title and title.strip().endswith(f"{drive_letter}:"):
            return btn
    return None


def _get_tight_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Get the tight window rectangle using DWM (excludes invisible borders/shadows)."""
    rect = wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    return (rect.left, rect.top, rect.right, rect.bottom)


def _capture_window(main_window: Any, part_number: str, dut_name: str) -> None:
    """Helper to capture and save the window screenshot."""
    ss_dir = artifact_dir(part_number, "Windows", "CrystalDiskInfo")
    mk_dir(ss_dir)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    ss_path = Path(ss_dir) / f"{dut_name}_{timestamp}.png"

    hwnd = main_window.handle
    rect = _get_tight_rect(hwnd)

    img = ImageGrab.grab(bbox=rect, all_screens=True)
    img.save(str(ss_path))
    print(f"Screenshot saved to: {ss_path}")


def automate_crystal_disk_info(drive_letter: str, part_number: str, dut_name: str) -> bool:
    """Launch CrystalDiskInfo, select the specific drive, and save a screenshot."""
    if not CRYSTAL_DISK_INFO_PATH.exists():
        print(f"\nCrystalDiskInfo not found at {CRYSTAL_DISK_INFO_PATH}")
        return False

    try:
        try:
            app = Application(backend="uia").connect(path="DiskInfo64.exe")
            print("Connected to existing CrystalDiskInfo.")
        except Exception:
            print(f"Launching CrystalDiskInfo from {CRYSTAL_DISK_INFO_PATH}...")
            app = Application(backend="uia").start(str(CRYSTAL_DISK_INFO_PATH))
            time.sleep(5)

        main_window = app.window(title_re=".*CrystalDiskInfo.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()

        btn = _find_drive_button(main_window, drive_letter)
        if btn is None:
            print(f"Warning: Could not find drive button for {drive_letter}:")
            return False

        print(f"Selecting drive button: {btn.window_text().replace('\r\n', ' ')}")
        btn.click_input()
        time.sleep(1)

        print("\nCrystalDiskInfo automation successful. Taking screenshot...")
        _capture_window(main_window, part_number, dut_name)
        return True

    except Exception as e:
        print(f"Error during CrystalDiskInfo automation: {e}")
        return False


def _wait_for_device_present(prompt: str) -> ApricornDevice:
    """Wait for an Apricorn device to be connected and return it."""
    dut = find_apricorn_device()
    if dut is None:
        print(f"\n{prompt}")
    while dut is None:
        time.sleep(1)
        dut = find_apricorn_device()
    return dut


def _sync_performance_section(data: dict[str, Any], equipment: dict[str, Any]) -> None:
    """Re-sync performance section with current equipment software."""
    performance = data.setdefault("performance", {})
    duts = equipment.get("dut", [])
    host_map = {"windows_host": "Windows", "linux_host": "Linux", "macos_host": "macOS"}

    for dut in duts:
        perf_dut = performance.setdefault(dut, {"Windows": {}, "Linux": {}, "macOS": {}})
        for host_key, os_key in host_map.items():
            host_data = equipment.get(host_key, {})
            software_list = host_data.get("software", [])
            if isinstance(software_list, list):
                os_perf = perf_dut.setdefault(os_key, {})
                for sw in software_list:
                    if isinstance(sw, dict) and sw.get("name"):
                        os_perf.setdefault(sw.get("name"), {"read": None, "write": None})


def _load_part_number_and_report(folder_name: str) -> tuple[str, Path]:
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    drive_info = data.get("drive_info")
    part_number = folder_name
    if isinstance(drive_info, dict):
        raw = drive_info.get("apricorn_part_number")
        if isinstance(raw, str) and raw.strip():
            part_number = raw.strip()
    return part_number, report_path


def run_software_step(part_number: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    actual_part_number, report_path = _load_part_number_and_report(folder_name)
    data = load_report(report_path)

    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section.")

    has_cdi = False
    for host_key in ["windows_host", "usb_if_host", "linux_host", "macos_host"]:
        software_list = equipment.get(host_key, {}).get("software", [])
        for sw in software_list:
            if isinstance(sw, dict) and sw.get("name") == "CrystalDiskInfo":
                has_cdi = True

    _sync_performance_section(data, equipment)
    save_report(report_path, data)
    print(f"\nSync complete. Updated report at {report_path}")

    if has_cdi:
        prompt = "Please connect the Apricorn device to continue with automation..."
        dut_info = _wait_for_device_present(prompt)
        if dut_info and dut_info.driveLetter:
            letter = dut_info.driveLetter.strip().replace(":", "").replace("\\", "")
            dut_name = (dut_info.iProduct or "unknown_device").strip()
            automate_crystal_disk_info(letter, actual_part_number, dut_name)
        else:
            print("\nError: Could not determine drive letter for the connected device.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync software entries to performance section.")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    args = parser.parse_args()
    run_software_step(part_number=args.part_number)
