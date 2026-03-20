from __future__ import annotations

import csv
import ctypes
import importlib
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from drive_qual.core.io_utils import mk_dir
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.core.storage_paths import artifact_dir, localize_windows_path
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice, find_apricorn_device

CRYSTAL_DISK_INFO_PATH = Path("C:/Program Files/CrystalDiskInfo/DiskInfo64.exe")
CRYSTAL_DISK_MARK_PATH = Path("C:/Program Files/CrystalDiskMark8/DiskMark64.exe")
ATTO_PATH = Path("C:/Program Files (x86)/ATTO Technology/Disk Benchmark/ATTODiskBenchmark.exe")

ATTO_TIMEOUT = 1800
CDM_TIMEOUT = 1200
CURRENT_HOST_BY_PLATFORM = {
    "windows": "windows_host",
    "linux": "linux_host",
    "macos": "macos_host",
}
CURRENT_OS_BY_HOST = {
    "windows_host": "Windows",
    "linux_host": "Linux",
    "macos_host": "macOS",
}


def _pywinauto_module() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("pywinauto is only available on Windows.")
    return importlib.import_module("pywinauto")


def _pywinauto_application_class() -> Any:
    return _pywinauto_module().Application


def _pywinauto_desktop_class() -> Any:
    return _pywinauto_module().Desktop


def _current_host_key() -> str:
    if sys.platform.startswith("linux"):
        return CURRENT_HOST_BY_PLATFORM["linux"]
    if sys.platform == "darwin":
        return CURRENT_HOST_BY_PLATFORM["macos"]
    return CURRENT_HOST_BY_PLATFORM["windows"]


def _current_os_name() -> str:
    return CURRENT_OS_BY_HOST[_current_host_key()]


def _software_entries_for_current_host(equipment: dict[str, Any]) -> list[dict[str, Any]]:
    host_data = equipment.get(_current_host_key(), {})
    if not isinstance(host_data, dict):
        return []
    software = host_data.get("software", [])
    if not isinstance(software, list):
        return []
    return [entry for entry in software if isinstance(entry, dict)]


def _resolve_report_dut_key(performance: dict[str, Any], dut_name: str) -> str | None:
    report_dut_key = _find_report_dut_key(performance, dut_name)
    if report_dut_key is not None:
        return report_dut_key
    if len(performance) == 1:
        return next(iter(performance))
    return None


def _prompt_manual_float(label: str, current: float | None) -> float | None:
    current_text = "" if current is None else str(current)
    prompt = f"{label} [{current_text}]: " if current_text else f"{label}: "
    while True:
        response = input(prompt).strip()
        if not response:
            return current
        value = _to_float(response)
        if value is not None:
            return value
        print("Enter a numeric value in MB/s or leave the field blank to keep the current value.")


def _run_manual_performance_flow(report_path: Path, data: dict[str, Any], equipment: dict[str, Any]) -> None:
    software_entries = _software_entries_for_current_host(equipment)
    if not software_entries:
        print(f"No performance software configured for {_current_os_name()}.")
        return

    performance = data.setdefault("performance", {})
    if not isinstance(performance, dict):
        raise ValueError("Missing or invalid 'performance' section in report.")

    dut_info = _wait_for_device_present("Connect the Apricorn device to continue...")
    dut_name = (dut_info.iProduct or "unknown_device").strip()
    report_dut_key = _resolve_report_dut_key(performance, dut_name)
    if report_dut_key is None:
        raise RuntimeError(f"Could not map performance results for DUT {dut_name!r}.")

    os_name = _current_os_name()
    os_perf = performance.setdefault(report_dut_key, {"Windows": {}, "Linux": {}, "macOS": {}}).setdefault(os_name, {})
    for software in software_entries:
        name = software.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        entry = os_perf.setdefault(name, {"read": None, "write": None})
        if not isinstance(entry, dict):
            entry = {"read": None, "write": None}
            os_perf[name] = entry
        current_read = entry.get("read") if isinstance(entry.get("read"), (int, float)) else None
        current_write = entry.get("write") if isinstance(entry.get("write"), (int, float)) else None
        entry["read"] = _prompt_manual_float(f"{os_name} {name} read MB/s for {dut_name}", current_read)
        entry["write"] = _prompt_manual_float(f"{os_name} {name} write MB/s for {dut_name}", current_write)

    save_report(report_path, data)
    print(f"Updated {os_name} performance in {report_path}")


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
    if sys.platform != "win32":
        raise RuntimeError("Tight window capture is only supported on Windows.")
    rect = wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise RuntimeError("ctypes.windll is unavailable on this platform.")
    windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    return (rect.left, rect.top, rect.right, rect.bottom)


def _capture_window(main_window: Any, part_number: str, dut_name: str, tool_name: str) -> None:
    """Helper to capture and save the window screenshot."""
    from PIL import ImageGrab

    ss_dir = localize_windows_path(Path(artifact_dir(part_number, "Windows", tool_name)))
    mk_dir(ss_dir)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    ss_path = ss_dir / f"{dut_name}_{timestamp}.png"

    hwnd = main_window.handle
    rect = _get_tight_rect(hwnd)

    img = ImageGrab.grab(bbox=rect, all_screens=True)
    img.save(str(ss_path))
    print(f"Screenshot saved to: {ss_path}")


def _find_report_dut_key(performance: dict[str, Any], dut_name: str) -> str | None:
    for k in performance:
        if k.lower() in dut_name.lower() or dut_name.lower() in k.lower():
            return k
    return None


def _launch_or_connect_app(app_path: Path, exe_name: str, app_name: str) -> Any:
    """Helper to connect to an existing app or launch it."""
    try:
        app = _pywinauto_application_class()(backend="uia").connect(path=exe_name)
        print(f"Connected to existing {app_name}.")
        return app
    except Exception:
        print(f"Launching {app_name} from {app_path}...")
        app = _pywinauto_application_class()(backend="uia").start(str(app_path))
        time.sleep(5)
        return app


def _to_float(val: str | None) -> float | None:
    """Safely convert a string to a float, returning None if conversion fails."""
    if val is None:
        return None
    try:
        clean_val = "".join(c for k, c in enumerate(val) if c.isdigit() or c == "." or (c == "-" and k == 0))
        return float(clean_val)
    except (ValueError, TypeError):
        return None


def _update_cdi_json(report_path: Path, data: dict[str, Any], dut_name: str, val: bool | None) -> None:
    performance = data.setdefault("performance", {})
    report_dut_key = _find_report_dut_key(performance, dut_name)
    if report_dut_key:
        win_perf = performance[report_dut_key].setdefault("Windows", {})
        cdi_perf = win_perf.setdefault("CrystalDiskInfo", {"screenshot": None})
        cdi_perf["screenshot"] = val
        save_report(report_path, data)
        print(f"Updated JSON report for '{report_dut_key}' CDI screenshot: {val}")


def automate_crystal_disk_info(
    drive_letter: str, part_number: str, dut_name: str, report_path: Path, data: dict[str, Any]
) -> bool:
    """Launch CrystalDiskInfo, select the specific drive, and save a screenshot."""
    is_ask3 = "ASK3" in dut_name.upper()

    if is_ask3:
        print(f"Skipping CrystalDiskInfo for {dut_name} (ASK3 device).")
        _update_cdi_json(report_path, data, dut_name, False)
        return False

    if not CRYSTAL_DISK_INFO_PATH.exists():
        print(f"\nCrystalDiskInfo not found at {CRYSTAL_DISK_INFO_PATH}")
        _update_cdi_json(report_path, data, dut_name, False)
        return False

    try:
        app = _launch_or_connect_app(CRYSTAL_DISK_INFO_PATH, "DiskInfo64.exe", "CrystalDiskInfo")
        main_window = app.window(title_re=".*CrystalDiskInfo.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()

        btn = _find_drive_button(main_window, drive_letter)
        if btn is None:
            print(f"Warning: Could not find drive button for {drive_letter}:")
            _update_cdi_json(report_path, data, dut_name, False)
            return False

        btn.click_input()
        time.sleep(1)
        _capture_window(main_window, part_number, dut_name, "CrystalDiskInfo")
        _update_cdi_json(report_path, data, dut_name, True)
        app.kill()
        return True
    except Exception as e:
        print(f"Error during CrystalDiskInfo automation: {e}")
        _update_cdi_json(report_path, data, dut_name, False)
        return False


def _atto_select_drive(main_window: Any, drive_letter: str) -> None:
    """Helper to select the drive in ATTO."""
    drive_combo = main_window.child_window(auto_id="1000", control_type="ComboBox")
    drive_combo.click_input()
    time.sleep(0.5)
    try:
        target_item = drive_combo.child_window(title_re=f".*{drive_letter}:.*", control_type="ListItem")
        target_item.click_input()
    except Exception:
        drive_combo.type_keys(f"{drive_letter}:{{ENTER}}")


def _atto_wait_for_completion(app: Any) -> None:
    """Wait for ATTO benchmark to complete."""
    print("Waiting for ATTO benchmark to complete (this may take several minutes)...")
    start_time = time.time()
    while time.time() - start_time < ATTO_TIMEOUT:
        time.sleep(10)
        try:
            main_window = app.window(title_re=".*ATTO Disk Benchmark.*")
            current_btn = main_window.child_window(auto_id="1002", control_type="Button")
            if current_btn.exists() and current_btn.is_enabled() and current_btn.window_text() == "Start":
                break
        except Exception:
            continue


def _atto_extract_results(
    main_window: Any, csv_path: Path, report_path: Path, data: dict[str, Any], dut_name: str
) -> None:
    """Extract results from ATTO GUI and save to CSV/JSON."""
    csv_rows = []
    for i in range(21):
        try:
            label = main_window.child_window(auto_id=str(1100 + i)).window_text().strip()
            if not label:
                continue
            write_val = main_window.child_window(auto_id=str(1200 + i)).window_text().strip()
            read_val = main_window.child_window(auto_id=str(1300 + i)).window_text().strip()
            csv_rows.append([label, write_val, read_val])
        except Exception:
            break

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["I/O Size", "Write", "Read"])
        writer.writerows(csv_rows)

    if csv_rows:
        performance = data.setdefault("performance", {})
        report_dut_key = _find_report_dut_key(performance, dut_name)
        if report_dut_key:
            win_perf = performance[report_dut_key].setdefault("Windows", {})
            atto_perf = win_perf.setdefault("ATTO", {"read": None, "write": None})
            atto_perf["read"] = _to_float(csv_rows[-1][2])
            atto_perf["write"] = _to_float(csv_rows[-1][1])
            save_report(report_path, data)


def automate_atto(drive_letter: str, part_number: str, dut_name: str, report_path: Path, data: dict[str, Any]) -> bool:
    """Launch ATTO, select drive, run benchmark, and save screenshot/CSV."""
    if not ATTO_PATH.exists():
        print(f"\nATTO not found at {ATTO_PATH}")
        return False
    try:
        app = _launch_or_connect_app(ATTO_PATH, "ATTODiskBenchmark.exe", "ATTO Disk Benchmark")
        main_window = app.window(title_re=".*ATTO Disk Benchmark.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()
        _atto_select_drive(main_window, drive_letter)
        start_btn = main_window.child_window(title="Start", auto_id="1002", control_type="Button")
        start_btn.click_input()
        _atto_wait_for_completion(app)
        main_window.set_focus()
        _capture_window(main_window, part_number, dut_name, "ATTO")
        ss_dir = localize_windows_path(Path(artifact_dir(part_number, "Windows", "ATTO")))
        mk_dir(ss_dir)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        csv_path = ss_dir / f"{dut_name}_{timestamp}.csv"
        _atto_extract_results(main_window, csv_path, report_path, data, dut_name)
        app.kill()
        return True
    except Exception as e:
        print(f"Error during ATTO automation: {e}")
        return False


def _cdm_select_drive(main_window: Any, drive_letter: str) -> None:
    """Helper to select the drive in CrystalDiskMark."""
    drive_combo = main_window.child_window(auto_id="1027", control_type="ComboBox")
    drive_combo.click_input()
    time.sleep(0.5)
    try:
        target_item = drive_combo.child_window(title_re=f"{drive_letter}:.*", control_type="ListItem")
        target_item.click_input()
    except Exception:
        combo_lbox = _pywinauto_desktop_class()(backend="uia").window(class_name="ComboLBox")
        if combo_lbox.exists():
            combo_lbox.child_window(title_re=f"{drive_letter}:.*").click_input()
        else:
            drive_combo.type_keys(f"{drive_letter}:{{ENTER}}")


def _cdm_wait_for_completion(app: Any) -> None:
    """Wait for CrystalDiskMark benchmark to complete."""
    print("Waiting for benchmark to complete (this may take several minutes)...")
    start_time = time.time()
    while time.time() - start_time < CDM_TIMEOUT:
        time.sleep(10)
        try:
            main_window = app.window(title_re=".*CrystalDiskMark.*")
            current_btn = main_window.child_window(title="All", auto_id="1003", control_type="Button")
            if current_btn.exists() and current_btn.is_enabled() and current_btn.window_text() == "All":
                break
        except Exception:
            continue


def _update_cdm_json(
    report_path: Path, data: dict[str, Any], dut_name: str, first_read: str | None, first_write: str | None
) -> None:
    performance = data.setdefault("performance", {})
    report_dut_key = _find_report_dut_key(performance, dut_name)
    if report_dut_key:
        win_perf = performance[report_dut_key].setdefault("Windows", {})
        cdm_perf = win_perf.setdefault("CrystalDiskMark", {"read": None, "write": None})
        cdm_perf["read"] = _to_float(first_read)
        cdm_perf["write"] = _to_float(first_write)
        save_report(report_path, data)
        print(f"Updated JSON report for '{report_dut_key}' CDM results: {cdm_perf['read']} / {cdm_perf['write']}")


def _cdm_extract_and_save_results(
    main_window: Any, part_number: str, dut_name: str, report_path: Path, data: dict[str, Any]
) -> None:
    """Extract results from CDM GUI, save to CSV, and update JSON report."""
    ss_dir = localize_windows_path(Path(artifact_dir(part_number, "Windows", "CrystalDiskMark")))
    mk_dir(ss_dir)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_path = ss_dir / f"{dut_name}_{timestamp}.csv"
    rows = [
        {"label_id": "1004", "read_id": "1009", "write_id": "1014"},
        {"label_id": "1005", "read_id": "1010", "write_id": "1015"},
        {"label_id": "1006", "read_id": "1011", "write_id": "1016"},
        {"label_id": "1007", "read_id": "1012", "write_id": "1017"},
    ]
    csv_rows = []
    first_read = None
    first_write = None
    for r in rows:
        try:
            label = main_window.child_window(auto_id=r["label_id"]).window_text().replace("\r\n", " ")
            read = main_window.child_window(auto_id=r["read_id"]).window_text()
            write = main_window.child_window(auto_id=r["write_id"]).window_text()
            csv_rows.append([label, read, write])
            if first_read is None:
                first_read, first_write = read, write
        except Exception:
            continue
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Test", "Read", "Write"])
        writer.writerows(csv_rows)
    _update_cdm_json(report_path, data, dut_name, first_read, first_write)


def automate_crystal_disk_mark(
    drive_letter: str, part_number: str, dut_name: str, report_path: Path, data: dict[str, Any]
) -> bool:
    """Launch CrystalDiskMark, select drive, run benchmark, and save screenshot/CSV."""
    if not CRYSTAL_DISK_MARK_PATH.exists():
        print(f"\nCrystalDiskMark not found at {CRYSTAL_DISK_MARK_PATH}")
        return False
    try:
        try:
            app = _pywinauto_application_class()(backend="uia").connect(path="DiskMark64.exe")
        except Exception:
            app = _pywinauto_application_class()(backend="uia").start(str(CRYSTAL_DISK_MARK_PATH))
            time.sleep(5)
        main_window = app.window(title_re=".*CrystalDiskMark.*")
        main_window.wait("visible", timeout=10)
        main_window.set_focus()
        _cdm_select_drive(main_window, drive_letter)
        all_btn = main_window.child_window(title="All", auto_id="1003", control_type="Button")
        all_btn.click_input()
        _cdm_wait_for_completion(app)
        main_window.set_focus()
        _capture_window(main_window, part_number, dut_name, "CrystalDiskMark")
        _cdm_extract_and_save_results(main_window, part_number, dut_name, report_path, data)
        app.kill()
        return True
    except Exception as e:
        print(f"Error during CrystalDiskMark automation: {e}")
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
            sw_list = host_data.get("software", [])
            if isinstance(sw_list, list):
                os_perf = perf_dut.setdefault(os_key, {})
                for sw in sw_list:
                    if isinstance(sw, dict) and sw.get("name"):
                        name = sw.get("name")
                        if name == "CrystalDiskInfo":
                            cdi_dict = os_perf.setdefault(name, {"screenshot": None})
                            cdi_dict.pop("read", None)
                            cdi_dict.pop("write", None)
                        else:
                            os_perf.setdefault(name, {"read": None, "write": None})


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


def _get_software_flags(equipment: dict[str, Any]) -> tuple[bool, bool, bool]:
    """Determine which software automations to run for the current host."""
    names = {entry.get("name") for entry in _software_entries_for_current_host(equipment)}
    return (
        "CrystalDiskInfo" in names,
        "CrystalDiskMark" in names,
        "ATTO" in names,
    )


def run_software_step(part_number: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    actual_pn, report_path = _load_part_number_and_report(folder_name)
    data = load_report(report_path)
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section.")
    has_cdi, has_cdm, has_atto = _get_software_flags(equipment)
    _sync_performance_section(data, equipment)
    save_report(report_path, data)
    print(f"\nSync complete. Updated report at {report_path}")

    if sys.platform == "win32":
        if has_cdi or has_cdm or has_atto:
            dut_info = _wait_for_device_present("Connect the Apricorn device to continue...")
            if dut_info and dut_info.driveLetter:
                letter = dut_info.driveLetter.strip().replace(":", "").replace("\\", "")
                dut_name = (dut_info.iProduct or "unknown_device").strip()
                if has_cdi:
                    automate_crystal_disk_info(letter, actual_pn, dut_name, report_path, data)
                if has_cdm:
                    automate_crystal_disk_mark(letter, actual_pn, dut_name, report_path, data)
                if has_atto:
                    automate_atto(letter, actual_pn, dut_name, report_path, data)
            else:
                raise RuntimeError("Could not determine drive letter for the connected device.")
        return

    _run_manual_performance_flow(report_path, data, equipment)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync software entries to performance section.")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    args = parser.parse_args()
    run_software_step(part_number=args.part_number)
