from __future__ import annotations

import csv
import json
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from drive_qual.core.io_utils import mk_dir
from drive_qual.core.report_session import load_report, resolve_folder_name, save_report
from drive_qual.core.storage_paths import artifact_dir, localize_windows_path
from drive_qual.platforms.macos.blackmagic import (
    DEFAULT_BENCHMARK_DURATION_SECONDS,
    BlackmagicAutomationResult,
    extract_blackmagic_read_write_from_screenshot,
    run_blackmagic_benchmark_automation,
)
from drive_qual.platforms.performance_common import (
    load_part_number_and_report,
    resolve_report_dut_key,
    software_entries_for_host,
    sync_performance_section,
    wait_for_device_present,
)

BLACKMAGIC_TOOL_NAME = "Blackmagic Disk Speed Test"
BLACKMAGIC_LEGACY_TOOL_NAMES = frozenset({"BlackMagic RAW Speed Test"})
BLACKMAGIC_ARTIFACT_CATEGORY = BLACKMAGIC_TOOL_NAME
BLACKMAGIC_APP_NAME = BLACKMAGIC_TOOL_NAME
BLACKMAGIC_APP_PATH = Path("/Applications/Blackmagic Disk Speed Test.app")
BLACKMAGIC_WINDOW_CAPTURE_INSET_X = 24
BLACKMAGIC_WINDOW_CAPTURE_INSET_Y = 24
BLACKMAGIC_AUTOMATION_MODE = "auto-with-manual-fallback"
BLACKMAGIC_AUTOMATION_DURATION_SECONDS = DEFAULT_BENCHMARK_DURATION_SECONDS
BLACKMAGIC_AUTOMATION_POST_STOP_SETTLE_SECONDS = 3
BLACKMAGIC_WINDOW_BOUNDS_SCRIPT = """
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{process_name}"
        delay 0.2
        set targetWindow to front window
        set {{xPos, yPos}} to position of targetWindow
        set {{winWidth, winHeight}} to size of targetWindow
        return (xPos as text) & "," & (yPos as text) & "," & (winWidth as text) & "," & (winHeight as text)
    end tell
end tell
"""


def _configured_blackmagic_tool_name(equipment: dict[str, Any]) -> str | None:
    software_names = {
        name.strip()
        for entry in software_entries_for_host(equipment, "macos_host")
        if isinstance((name := entry.get("name")), str) and name.strip()
    }
    if BLACKMAGIC_TOOL_NAME in software_names:
        return BLACKMAGIC_TOOL_NAME
    for legacy_name in BLACKMAGIC_LEGACY_TOOL_NAMES:
        if legacy_name in software_names:
            return legacy_name
    return None


def _blackmagic_artifact_paths(part_number: str, dut_name: str) -> tuple[Path, Path, Path]:
    output_dir = localize_windows_path(Path(artifact_dir(part_number, "macOS", BLACKMAGIC_ARTIFACT_CATEGORY)))
    mk_dir(output_dir)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    stem = f"{dut_name}_{timestamp}"
    return (
        output_dir / f"{stem}.png",
        output_dir / f"{stem}.json",
        output_dir / f"{stem}.csv",
    )


def _launch_blackmagic_app() -> bool:
    result = subprocess.run(
        ["open", "-a", BLACKMAGIC_APP_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True

    detail = (result.stderr or result.stdout).strip()
    if detail:
        print(f"Unable to launch {BLACKMAGIC_APP_NAME} automatically: {detail}")
    print(f"Launch {BLACKMAGIC_APP_NAME} manually and continue when the benchmark is visible.")
    return False


def _blackmagic_process_name_candidates() -> tuple[str, ...]:
    candidates: list[str] = [BLACKMAGIC_APP_NAME]
    info_path = BLACKMAGIC_APP_PATH / "Contents" / "Info.plist"
    if info_path.exists():
        try:
            info = plistlib.loads(info_path.read_bytes())
        except (plistlib.InvalidFileException, OSError):
            info = {}
        for key in ("CFBundleName", "CFBundleExecutable"):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            unique_candidates.append(candidate)
            seen.add(candidate)
    return tuple(unique_candidates)


def _parse_window_bounds(raw: str) -> tuple[int, int, int, int]:
    try:
        x_pos, y_pos, width, height = (int(part.strip()) for part in raw.split(",", maxsplit=3))
    except ValueError as exc:
        raise RuntimeError(f"macOS window detection returned invalid bounds: {raw!r}") from exc
    if width <= 0 or height <= 0:
        raise RuntimeError(f"macOS window detection returned non-positive bounds: {raw!r}")
    return (x_pos, y_pos, width, height)


def _tighten_window_bounds(bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x_pos, y_pos, width, height = bounds
    inset_x = min(BLACKMAGIC_WINDOW_CAPTURE_INSET_X, max(0, (width - 1) // 2))
    inset_y = min(BLACKMAGIC_WINDOW_CAPTURE_INSET_Y, max(0, (height - 1) // 2))
    tightened_width = width - (inset_x * 2)
    tightened_height = height - (inset_y * 2)
    if tightened_width <= 0 or tightened_height <= 0:
        return bounds
    return (x_pos + inset_x, y_pos + inset_y, tightened_width, tightened_height)


def _window_bounds_for_app(app_name: str) -> tuple[int, int, int, int]:
    last_detail = ""
    for process_name in _blackmagic_process_name_candidates():
        script = BLACKMAGIC_WINDOW_BOUNDS_SCRIPT.format(app_name=app_name, process_name=process_name)
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return _parse_window_bounds((result.stdout or "").strip())
        last_detail = (result.stderr or result.stdout).strip()

    suffix = f": {last_detail}" if last_detail else ""
    raise RuntimeError(
        "macOS window detection failed. Grant Accessibility access to System Events or the terminal and rerun the "
        f"performance step{suffix}"
    )


def _capture_blackmagic_screenshot(screenshot_path: Path) -> None:
    x_pos, y_pos, width, height = _tighten_window_bounds(_window_bounds_for_app(BLACKMAGIC_APP_NAME))
    result = subprocess.run(
        ["screencapture", "-x", f"-R{x_pos},{y_pos},{width},{height}", str(screenshot_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            "macOS screenshot capture failed. Grant this terminal Screen Recording permission and rerun the "
            f"performance step{suffix}"
        )


def _prompt_positive_mb_s(label: str) -> float:
    while True:
        response = input(f"{label} MB/s: ").strip()
        try:
            value = float(response)
        except ValueError:
            print("Enter a numeric MB/s value.")
            continue
        if value > 0:
            return value
        print("Enter a positive MB/s value greater than 0.")


def _collect_blackmagic_automation_result(dut_name: str, screenshot_path: Path) -> BlackmagicAutomationResult:
    warnings: list[str] = []
    benchmark_ran_automatically = _run_blackmagic_automation(dut_name)
    app_launched = True
    if not benchmark_ran_automatically:
        app_launched = _launch_blackmagic_app()
    _prompt_blackmagic_ready(
        dut_name,
        app_launched=app_launched,
        benchmark_ran_automatically=benchmark_ran_automatically,
    )
    _capture_blackmagic_screenshot(screenshot_path)

    read_mb_s: float | None = None
    write_mb_s: float | None = None
    try:
        extracted = extract_blackmagic_read_write_from_screenshot(screenshot_path)
    except Exception as exc:
        warnings.append(f"OCR extraction failed: {exc}")
        extracted = None

    if extracted is not None:
        read_mb_s, write_mb_s = extracted
        value_source = "ocr"
    else:
        value_source = "none"

    return BlackmagicAutomationResult(
        screenshot_path=screenshot_path,
        benchmark_ran_automatically=benchmark_ran_automatically,
        app_launched_for_manual=app_launched if not benchmark_ran_automatically else False,
        read_mb_s=read_mb_s,
        write_mb_s=write_mb_s,
        value_source=value_source,
        warnings=warnings,
    )


def _resolve_blackmagic_read_write_values(
    tool_name: str,
    dut_name: str,
    automation_result: BlackmagicAutomationResult,
) -> tuple[float, float, str]:
    for warning in automation_result.warnings:
        print(f"Automatic {tool_name} value extraction failed: {warning}")
    if automation_result.read_mb_s is not None and automation_result.write_mb_s is not None:
        print(
            f"Auto-extracted {tool_name} values for {dut_name}: "
            f"read={automation_result.read_mb_s} MB/s write={automation_result.write_mb_s} MB/s"
        )
        return (automation_result.read_mb_s, automation_result.write_mb_s, automation_result.value_source)

    print("Falling back to manual read/write entry.")
    read_mb_s = _prompt_positive_mb_s(f"macOS {tool_name} read for {dut_name}")
    write_mb_s = _prompt_positive_mb_s(f"macOS {tool_name} write for {dut_name}")
    return (read_mb_s, write_mb_s, "manual")


def _run_blackmagic_automation(dut_name: str) -> bool:
    if BLACKMAGIC_AUTOMATION_MODE != "auto-with-manual-fallback":
        return False

    try:
        run_blackmagic_benchmark_automation(
            dut_name,
            duration_seconds=BLACKMAGIC_AUTOMATION_DURATION_SECONDS,
        )
    except Exception as exc:
        print(f"Automatic {BLACKMAGIC_TOOL_NAME} run failed: {exc}")
        print("Falling back to manual-assisted benchmark entry.")
        return False

    print("Automatic Blackmagic benchmark run complete.")
    return True


def _prompt_blackmagic_ready(dut_name: str, *, app_launched: bool, benchmark_ran_automatically: bool) -> None:
    if benchmark_ran_automatically:
        print(
            f"Automatic {BLACKMAGIC_TOOL_NAME} run completed for {dut_name}. "
            f"Waiting {BLACKMAGIC_AUTOMATION_POST_STOP_SETTLE_SECONDS} seconds for UI to settle before screenshot..."
        )
        time.sleep(BLACKMAGIC_AUTOMATION_POST_STOP_SETTLE_SECONDS)
        return

    launch_note = "The app was opened automatically." if app_launched else "Open the app manually before continuing."
    input(
        f"Run {BLACKMAGIC_TOOL_NAME} for {dut_name}. {launch_note} "
        "Wait until the benchmark shows completed read/write results in MB/s, then press Enter to capture a "
        "screenshot. "
        "If macOS prompts for permission, allow Screen Recording for this terminal..."
    )


def _write_blackmagic_json(
    json_path: Path,
    *,
    tool_name: str,
    dut_name: str,
    read_mb_s: float,
    write_mb_s: float,
) -> None:
    payload = {
        "tool": tool_name,
        "dut": dut_name,
        "read_mb_s": read_mb_s,
        "write_mb_s": write_mb_s,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_blackmagic_csv(csv_path: Path, *, read_mb_s: float, write_mb_s: float) -> None:
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Read MB/s", read_mb_s])
        writer.writerow(["Write MB/s", write_mb_s])


def run_software_step(part_number: str | None = None) -> None:  # noqa: PLR0915
    if sys.platform != "darwin":
        raise RuntimeError("macOS performance step can only run on macOS.")

    folder_name = resolve_folder_name(part_number)
    actual_pn, report_path = load_part_number_and_report(folder_name)
    data = load_report(report_path)
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section.")

    sync_performance_section(data, equipment)
    save_report(report_path, data)
    print(f"\nSync complete. Updated report at {report_path}")

    tool_name = _configured_blackmagic_tool_name(equipment)
    if tool_name is None:
        print(f"No {BLACKMAGIC_TOOL_NAME} entry configured for macOS.")
        return

    performance = data.setdefault("performance", {})
    if not isinstance(performance, dict):
        raise ValueError("Missing or invalid 'performance' section in report.")

    dut_info = wait_for_device_present("Connect the Apricorn device to continue...")
    dut_name = (dut_info.iProduct or "unknown_device").strip()
    report_dut_key = resolve_report_dut_key(performance, dut_name)
    if report_dut_key is None:
        raise RuntimeError(f"Could not map performance results for DUT {dut_name!r}.")

    screenshot_path, json_path, csv_path = _blackmagic_artifact_paths(actual_pn, dut_name)
    automation_result = _collect_blackmagic_automation_result(
        dut_name,
        screenshot_path,
    )
    read_mb_s, write_mb_s, _value_source = _resolve_blackmagic_read_write_values(
        tool_name,
        dut_name,
        automation_result,
    )
    _write_blackmagic_json(
        json_path,
        tool_name=tool_name,
        dut_name=dut_name,
        read_mb_s=read_mb_s,
        write_mb_s=write_mb_s,
    )
    _write_blackmagic_csv(csv_path, read_mb_s=read_mb_s, write_mb_s=write_mb_s)

    os_perf = performance.setdefault(report_dut_key, {"Windows": {}, "Linux": {}, "macOS": {}}).setdefault("macOS", {})
    entry = os_perf.setdefault(tool_name, {"read": None, "write": None})
    if not isinstance(entry, dict):
        entry = {"read": None, "write": None}
        os_perf[tool_name] = entry
    entry["read"] = read_mb_s
    entry["write"] = write_mb_s

    save_report(report_path, data)
    print(f"Saved macOS benchmark screenshot to: {screenshot_path}")
    print(f"Saved macOS benchmark JSON to: {json_path}")
    print(f"Saved macOS benchmark CSV to: {csv_path}")
    print(f"Updated macOS performance in {report_path}")
