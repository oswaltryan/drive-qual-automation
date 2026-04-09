from __future__ import annotations

import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

BLACKMAGIC_APP_NAME = "Blackmagic Disk Speed Test"
BLACKMAGIC_APP_PATH = Path("/Applications/Blackmagic Disk Speed Test.app")
DEFAULT_BENCHMARK_DURATION_SECONDS = 60
HARD_CODED_TARGET_VOLUME_PATH = Path("/Volumes/DUT")
HARD_CODED_CLICK_REL_X = 0.50
HARD_CODED_CLICK_REL_Y = 0.31

_SELECT_TARGET_DRIVE_MENU_SCRIPT = """
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{process_name}"
        set frontmost to true
        delay 0.4
        set menuFound to false
        repeat with barItem in menu bar items of menu bar 1
            try
                click (first menu item of menu 1 of barItem whose name contains "Select Target Drive")
                set menuFound to true
                exit repeat
            end try
        end repeat
        if menuFound is false then
            error "Could not find 'Select Target Drive...' menu item."
        end if
    end tell
end tell
"""

_CHOOSE_DRIVE_IN_DIALOG_SCRIPT = """
tell application "System Events"
    tell process "{process_name}"
        delay 1.2
        keystroke "g" using {{command down, shift down}}
        delay 1.0
        keystroke "{target_path}"
        delay 0.8
        key code 36
        delay 1.5
        key code 36
        delay 1.5
        key code 36
    end tell
end tell
"""

_WINDOW_BOUNDS_SCRIPT = """
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{process_name}"
        set frontmost to true
        delay 0.5
        set targetWindow to front window
        set {{xPos, yPos}} to position of targetWindow
        set {{winWidth, winHeight}} to size of targetWindow
        return (xPos as text) & "," & (yPos as text) & "," & (winWidth as text) & "," & (winHeight as text)
    end tell
end tell
"""

_CLICK_AT_COORDINATE_SCRIPT = """
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{process_name}"
        set frontmost to true
    end tell
    delay 0.2
    click at {{{x},{y}}}
    return "clicked-coordinate:{x},{y}"
end tell
"""

_ENSURE_MAIN_WINDOW_READY_SCRIPT = """
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{process_name}"
        set frontmost to true
        delay 0.5
        set targetWindow to front window
        repeat with i from 1 to 8
            if exists sheet 1 of targetWindow then
                key code 36
                delay 0.8
            else
                return "main-window-ready"
            end if
        end repeat
        if exists sheet 1 of targetWindow then
            error "Target drive dialog is still open after confirmation attempts."
        end if
        return "main-window-ready"
    end tell
end tell
"""

_SWIFT_VISION_OCR_SCRIPT = """
import AppKit
import Foundation
import Vision

let args = CommandLine.arguments
guard args.count >= 2 else {
    fputs("missing image path\\n", stderr)
    exit(2)
}

let imagePath = args[1]
guard let nsImage = NSImage(contentsOfFile: imagePath) else {
    fputs("unable to load image: \\(imagePath)\\n", stderr)
    exit(3)
}
guard let tiff = nsImage.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cgImage = bitmap.cgImage else {
    fputs("unable to decode image: \\(imagePath)\\n", stderr)
    exit(4)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

do {
    try handler.perform([request])
} catch {
    fputs("vision OCR failed: \\(error.localizedDescription)\\n", stderr)
    exit(5)
}

guard let results = request.results else {
    exit(0)
}

for observation in results {
    guard let candidate = observation.topCandidates(1).first else { continue }
    print(candidate.string)
}
"""


def _applescript_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return (result.stdout or "").strip()

    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(detail or "osascript call failed")


def _launch_blackmagic_app() -> None:
    result = subprocess.run(
        ["open", "-a", BLACKMAGIC_APP_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Unable to launch {BLACKMAGIC_APP_NAME}: {detail}")
    time.sleep(2.0)


def _close_blackmagic_app() -> None:
    subprocess.run(
        ["osascript", "-e", f'tell application "{BLACKMAGIC_APP_NAME}" to quit'],
        check=False,
        capture_output=True,
        text=True,
    )
    for process_name in _blackmagic_process_name_candidates():
        subprocess.run(
            ["pkill", "-x", process_name],
            check=False,
            capture_output=True,
            text=True,
        )
    time.sleep(1.0)


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

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return tuple(unique)


def _run_ui_script(script_template: str, **values: str) -> str:
    last_error = ""
    for process_name in _blackmagic_process_name_candidates():
        quoted_values = {
            "app_name": _applescript_quote(BLACKMAGIC_APP_NAME),
            "process_name": _applescript_quote(process_name),
        }
        quoted_values.update({key: _applescript_quote(value) for key, value in values.items()})
        script = script_template.format(**quoted_values)
        try:
            return _run_osascript(script)
        except RuntimeError as exc:
            last_error = str(exc)
    raise RuntimeError(last_error or "Blackmagic UI automation failed")


def _parse_window_bounds(raw: str) -> tuple[int, int, int, int]:
    try:
        x_pos, y_pos, width, height = (int(part.strip()) for part in raw.split(",", maxsplit=3))
    except ValueError as exc:
        raise RuntimeError(f"Invalid window bounds from AppleScript: {raw!r}") from exc
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Non-positive window bounds from AppleScript: {raw!r}")
    return (x_pos, y_pos, width, height)


def _click_blackmagic_by_relative_coordinate(rel_x: float, rel_y: float) -> str:
    bounds_raw = _run_ui_script(_WINDOW_BOUNDS_SCRIPT)
    win_x, win_y, width, height = _parse_window_bounds(bounds_raw)
    target_x = win_x + int(width * rel_x)
    target_y = win_y + int(height * rel_y)
    result = _run_ui_script(_CLICK_AT_COORDINATE_SCRIPT, x=str(target_x), y=str(target_y))
    return f"{result};window={win_x},{win_y},{width},{height};rel={rel_x:.3f},{rel_y:.3f}"


def _number_from_text(raw: str) -> float | None:
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", raw)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_labeled_value(raw_text: str, label: str) -> float | None:
    patterns = (
        rf"{label}\s*[:=]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        rf"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:MB/?S|MBPS)?\s*{label}",
    )
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match is None:
            continue
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            continue
    return None


def parse_blackmagic_read_write_mb_s(raw_text: str) -> tuple[float, float] | None:  # noqa: PLR0912
    text = raw_text.strip()
    if not text:
        return None

    read_value = _extract_labeled_value(text, "READ")
    write_value = _extract_labeled_value(text, "WRITE")
    if read_value is not None and write_value is not None and read_value > 0 and write_value > 0:
        return (read_value, write_value)

    lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    if len(lines) == 1:
        lines = [piece.strip() for piece in re.split(r"\s*,\s*", text) if piece.strip()]

    pending_label: str | None = None
    for line in lines:
        line_upper = line.upper()
        number = _number_from_text(line)
        if "READ" in line_upper:
            pending_label = "READ"
            if number is not None:
                read_value = number
            continue
        if "WRITE" in line_upper:
            pending_label = "WRITE"
            if number is not None:
                write_value = number
            continue
        if number is not None and pending_label == "READ" and read_value is None:
            read_value = number
            pending_label = None
            continue
        if number is not None and pending_label == "WRITE" and write_value is None:
            write_value = number
            pending_label = None

    if read_value is None or write_value is None:
        return None
    if read_value <= 0 or write_value <= 0:
        return None
    return (read_value, write_value)


def _ocr_screenshot_text_via_swift(screenshot_path: Path) -> str:
    try:
        result = subprocess.run(
            ["swift", "-e", _SWIFT_VISION_OCR_SCRIPT, str(screenshot_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(f"Swift OCR command failed to start: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or "Swift OCR command failed")

    return (result.stdout or "").strip()


def extract_blackmagic_read_write_from_screenshot(screenshot_path: Path) -> tuple[float, float] | None:
    raw_text = _ocr_screenshot_text_via_swift(screenshot_path)
    return parse_blackmagic_read_write_mb_s(raw_text)


def run_blackmagic_benchmark_automation(
    dut_name: str,
    *,
    duration_seconds: int = DEFAULT_BENCHMARK_DURATION_SECONDS,
) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Blackmagic automation can only run on macOS.")
    if duration_seconds < 1:
        raise ValueError("duration_seconds must be >= 1")

    target_path = HARD_CODED_TARGET_VOLUME_PATH.resolve()
    if not target_path.exists():
        raise RuntimeError(f"Expected DUT volume is not mounted: {target_path}")

    print(f"Closing existing {BLACKMAGIC_APP_NAME} process (if running)...")
    _close_blackmagic_app()
    print(f"Launching {BLACKMAGIC_APP_NAME}...")
    _launch_blackmagic_app()

    print(f"Selecting target drive for benchmark: {target_path.name} ({target_path})")
    _run_ui_script(_SELECT_TARGET_DRIVE_MENU_SCRIPT)
    time.sleep(1.0)
    _run_ui_script(_CHOOSE_DRIVE_IN_DIALOG_SCRIPT, target_path=target_path.as_posix())
    time.sleep(1.0)
    ready_result = _run_ui_script(_ENSURE_MAIN_WINDOW_READY_SCRIPT)
    print(f"Target-drive selection state: {ready_result}")

    start_result = _click_blackmagic_by_relative_coordinate(HARD_CODED_CLICK_REL_X, HARD_CODED_CLICK_REL_Y)
    print(f"Benchmark start action: {start_result}")
    print(f"Benchmark running for {duration_seconds} seconds...")
    time.sleep(duration_seconds)
    stop_result = _click_blackmagic_by_relative_coordinate(HARD_CODED_CLICK_REL_X, HARD_CODED_CLICK_REL_Y)
    print(f"Benchmark stop action: {stop_result}")
