from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

BLACKMAGIC_APP_NAME = "Blackmagic Disk Speed Test"
BLACKMAGIC_APP_PATH = Path("/Applications/Blackmagic Disk Speed Test.app")
DEFAULT_DUT_NAME = "DUT"
DEFAULT_DURATION_SECONDS = 60
DEFAULT_VOLUME_ROOT = Path("/Volumes")
DEFAULT_BUTTON_INDEX = 1
DEFAULT_TOGGLE_MODE = "coordinate"
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

_BUTTON_INVENTORY_SCRIPT = """
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{process_name}"
        set frontmost to true
        delay 0.8
        set targetWindow to front window
        set winPos to position of targetWindow
        set winX to item 1 of winPos
        set winPos to position of targetWindow
        set winY to item 2 of winPos
        set buttonPool to {{}}
        try
            set buttonPool to (every button of entire contents of targetWindow)
        on error
            set buttonPool to (buttons of targetWindow)
        end try
        set rawCount to count of buttonPool
        set candidateCount to 0
        set details to ""
        repeat with i from 1 to rawCount
            set oneButton to item i of buttonPool
            set subRoleValue to ""
            set elementName to ""
            set xPos to 0
            set yPos to 0
            set posKnown to false
            try
                set subRoleValue to (subrole of oneButton) as text
            end try
            try
                set elementName to (name of oneButton) as text
            end try
            if elementName is missing value or elementName is "" then
                set elementName to "<missing>"
            end if
            try
                set elementPos to position of oneButton
                set xPos to item 1 of elementPos
                set yPos to item 2 of elementPos
                set posKnown to true
            end try
            set isTitleBarControl to false
            if subRoleValue is "AXCloseButton" or subRoleValue is "AXMinimizeButton" or subRoleValue is "AXZoomButton" or subRoleValue is "AXToolbarButton" then
                set isTitleBarControl to true
            end if
            if (not isTitleBarControl) and posKnown and (yPos <= (winY + 70)) and (xPos <= (winX + 220)) then
                set isTitleBarControl to true
            end if
            if not isTitleBarControl then
                set candidateCount to candidateCount + 1
                if details is "" then
                    set details to (candidateCount as text) & "(raw:" & (i as text) & "):" & subRoleValue & ":" & elementName
                else
                    set details to details & " | " & (candidateCount as text) & "(raw:" & (i as text) & "):" & subRoleValue & ":" & elementName
                end if
            end if
        end repeat
        return "raw_buttons=" & (rawCount as text) & ";count=" & (candidateCount as text) & ";controls=" & details
    end tell
end tell
"""

_CLICK_BUTTON_BY_INDEX_SCRIPT = """
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{process_name}"
        set frontmost to true
        delay 0.8
        set targetWindow to front window
        set winPos to position of targetWindow
        set winX to item 1 of winPos
        set winY to item 2 of winPos
        set buttonPool to {{}}
        try
            set buttonPool to (every button of entire contents of targetWindow)
        on error
            set buttonPool to (buttons of targetWindow)
        end try
        set candidatePool to {{}}
        repeat with i from 1 to (count of buttonPool)
            set oneButton to item i of buttonPool
            set subRoleValue to ""
            set xPos to 0
            set yPos to 0
            set posKnown to false
            try
                set subRoleValue to (subrole of oneButton) as text
            end try
            try
                set elementPos to position of oneButton
                set xPos to item 1 of elementPos
                set yPos to item 2 of elementPos
                set posKnown to true
            end try
            set isTitleBarControl to false
            if subRoleValue is "AXCloseButton" or subRoleValue is "AXMinimizeButton" or subRoleValue is "AXZoomButton" or subRoleValue is "AXToolbarButton" then
                set isTitleBarControl to true
            end if
            if (not isTitleBarControl) and posKnown and (yPos <= (winY + 70)) and (xPos <= (winX + 220)) then
                set isTitleBarControl to true
            end if
            if not isTitleBarControl then
                set end of candidatePool to oneButton
            end if
        end repeat
        set candidateCount to count of candidatePool
        if candidateCount is 0 then
            error "No candidate buttons found in Blackmagic main window."
        end if
        if {button_index} < 1 or {button_index} > candidateCount then
            error "Requested control index " & ({button_index} as text) & " out of range 1.." & (candidateCount as text)
        end if
        set targetControl to item {button_index} of candidatePool
        set controlName to ""
        set roleValue to ""
        set subRoleValue to ""
        try
            set controlName to (name of targetControl) as text
        end try
        if controlName is missing value or controlName is "" then
            set controlName to "<missing>"
        end if
        try
            set roleValue to (role of targetControl) as text
        end try
        try
            set subRoleValue to (subrole of targetControl) as text
        end try
        click targetControl
        return "clicked-index={button_index};count=" & (candidateCount as text) & ";role=" & roleValue & ";subrole=" & subRoleValue & ";name=" & controlName
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

    time.sleep(2)


def _close_blackmagic_app() -> None:
    # Reset window layout/state by ensuring a fresh app launch each run.
    subprocess.run(
        ["osascript", "-e", 'tell application "Blackmagic Disk Speed Test" to quit'],
        check=False,
        capture_output=True,
        text=True,
    )
    # Some app states ignore polite quit; terminate any remaining process.
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


def _inventory_candidate_count(inventory_result: str) -> int:
    for segment in inventory_result.split(";"):
        if segment.startswith("count="):
            _, raw_value = segment.split("=", maxsplit=1)
            try:
                return int(raw_value)
            except ValueError:
                return 0
    return 0


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


def _mounted_volumes(volume_root: Path) -> list[Path]:
    if not volume_root.exists():
        return []
    return sorted((path for path in volume_root.iterdir() if path.is_dir()), key=lambda path: path.name.casefold())


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _normalize_name_loose(value: str) -> str:
    return _normalize_name(value).rstrip("0")


def _pick_single_match(candidates: list[Path], *, match_type: str, dut_name: str) -> Path | None:
    if len(candidates) == 1:
        selected = candidates[0].resolve()
        print(f"Resolved DUT via {match_type} match: {selected.name}")
        return selected
    if len(candidates) > 1:
        joined = ", ".join(path.name for path in candidates)
        raise RuntimeError(f"Ambiguous DUT name {dut_name!r} ({match_type}): {joined}")
    return None


def _resolve_target_volume(dut_name: str, volume_root: Path) -> Path:
    requested = Path(dut_name)
    if requested.is_absolute():
        if requested.exists():
            return requested.resolve()
        raise RuntimeError(f"Target drive path does not exist: {requested}")

    direct = (volume_root / dut_name).resolve()
    if direct.exists():
        return direct

    mounted = _mounted_volumes(volume_root)
    if not mounted:
        raise RuntimeError(f"No mounted volumes found under: {volume_root}")

    normalized = dut_name.strip().casefold()
    normalized_compact = _normalize_name(dut_name)
    normalized_loose = _normalize_name_loose(dut_name)
    if not normalized:
        raise RuntimeError("DUT name cannot be empty.")

    exact_match = _pick_single_match(
        [path for path in mounted if path.name.casefold() == normalized],
        match_type="exact(case-insensitive)",
        dut_name=dut_name,
    )
    if exact_match is not None:
        return exact_match

    prefix_match = _pick_single_match(
        [path for path in mounted if path.name.casefold().startswith(normalized)],
        match_type="prefix",
        dut_name=dut_name,
    )
    if prefix_match is not None:
        return prefix_match

    contains_match = _pick_single_match(
        [path for path in mounted if normalized in path.name.casefold()],
        match_type="contains",
        dut_name=dut_name,
    )
    if contains_match is not None:
        return contains_match

    if normalized_compact:
        exact_compact = _pick_single_match(
            [path for path in mounted if _normalize_name(path.name) == normalized_compact],
            match_type="normalized-exact",
            dut_name=dut_name,
        )
        if exact_compact is not None:
            return exact_compact

        prefix_compact = _pick_single_match(
            [path for path in mounted if _normalize_name(path.name).startswith(normalized_compact)],
            match_type="normalized-prefix",
            dut_name=dut_name,
        )
        if prefix_compact is not None:
            return prefix_compact

        contains_compact = _pick_single_match(
            [path for path in mounted if normalized_compact in _normalize_name(path.name)],
            match_type="normalized-contains",
            dut_name=dut_name,
        )
        if contains_compact is not None:
            return contains_compact

    if normalized_loose:
        exact_loose = _pick_single_match(
            [path for path in mounted if _normalize_name_loose(path.name) == normalized_loose],
            match_type="normalized-loose-exact",
            dut_name=dut_name,
        )
        if exact_loose is not None:
            return exact_loose

        prefix_loose = _pick_single_match(
            [path for path in mounted if _normalize_name_loose(path.name).startswith(normalized_loose)],
            match_type="normalized-loose-prefix",
            dut_name=dut_name,
        )
        if prefix_loose is not None:
            return prefix_loose

        contains_loose = _pick_single_match(
            [path for path in mounted if normalized_loose in _normalize_name_loose(path.name)],
            match_type="normalized-loose-contains",
            dut_name=dut_name,
        )
        if contains_loose is not None:
            return contains_loose

    available = ", ".join(path.name for path in mounted)
    raise RuntimeError(
        f"Could not find mounted volume for {dut_name!r} under {volume_root}. Available: {available}"
    )


def run_blackmagic_benchmark(
    dut_name: str,
    duration_seconds: int,
    volume_root: Path,
    *,
    button_index: int,
    toggle_mode: str,
    list_buttons_only: bool,
) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("This script only runs on macOS.")

    target_path = _resolve_target_volume(dut_name, volume_root)

    print(f"Closing existing {BLACKMAGIC_APP_NAME} process (if running)...")
    _close_blackmagic_app()
    print(f"Launching {BLACKMAGIC_APP_NAME}...")
    _launch_blackmagic_app()

    try:
        print(f"Step 10: Selecting partition: {target_path.name} ({target_path})")
        print("Step 10.1: Opening Select Target Drive dialog...")
        _run_ui_script(_SELECT_TARGET_DRIVE_MENU_SCRIPT)
        time.sleep(1.0)
        print(f"Step 10.2: Choosing target path in dialog: {target_path.as_posix()}")
        _run_ui_script(_CHOOSE_DRIVE_IN_DIALOG_SCRIPT, target_path=target_path.as_posix())
        time.sleep(1.0)
        print("Step 13: Ensuring target-drive dialog is closed...")
        ready_result = _run_ui_script(_ENSURE_MAIN_WINDOW_READY_SCRIPT)
        print(f"Step 13 complete: {ready_result}")
        print("Step 13.1: Capturing Blackmagic control inventory...")
        inventory_result = _run_ui_script(_BUTTON_INVENTORY_SCRIPT)
        print(f"Control inventory: {inventory_result}")
        candidate_count = _inventory_candidate_count(inventory_result)
        if list_buttons_only:
            print("List-only mode enabled; exiting before benchmark start.")
            return

        print(f"Step 14: Starting benchmark with mode={toggle_mode}...")
        if toggle_mode == "controls" and candidate_count > 0:
            start_result = _run_ui_script(_CLICK_BUTTON_BY_INDEX_SCRIPT, button_index=str(button_index))
        elif toggle_mode == "controls" and candidate_count == 0:
            raise RuntimeError(
                "Requested --toggle-mode controls, but no candidate controls were found. "
                "Use --toggle-mode coordinate."
            )
        else:
            start_result = _click_blackmagic_by_relative_coordinate(HARD_CODED_CLICK_REL_X, HARD_CODED_CLICK_REL_Y)
        print(f"Step 14 complete: {start_result}")

        print(f"Benchmark running for {duration_seconds} seconds...")
        time.sleep(duration_seconds)

        print(f"Stopping benchmark with mode={toggle_mode}...")
        if toggle_mode == "controls" and candidate_count > 0:
            stop_result = _run_ui_script(_CLICK_BUTTON_BY_INDEX_SCRIPT, button_index=str(button_index))
        elif toggle_mode == "controls" and candidate_count == 0:
            raise RuntimeError(
                "Requested --toggle-mode controls, but no candidate controls were found for stop action."
            )
        else:
            stop_result = _click_blackmagic_by_relative_coordinate(HARD_CODED_CLICK_REL_X, HARD_CODED_CLICK_REL_Y)
        print(f"Stop action result: {stop_result}")
        print("Benchmark stopped.")
    finally:
        print(f"Closing {BLACKMAGIC_APP_NAME} at end of run...")
        _close_blackmagic_app()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automate Blackmagic benchmark for Padlock filesystem partition")
    parser.add_argument(
        "--dut-name",
        default=DEFAULT_DUT_NAME,
        help="Mounted filesystem partition name to select (default: DUT)",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
        help="How long to run benchmark before stopping",
    )
    parser.add_argument(
        "--volume-root",
        default=str(DEFAULT_VOLUME_ROOT),
        help="Root path where DUT volumes are mounted",
    )
    parser.add_argument(
        "--button-index",
        type=int,
        default=DEFAULT_BUTTON_INDEX,
        help="1-based pressable control index in Blackmagic main window to click for start/stop",
    )
    parser.add_argument(
        "--toggle-mode",
        choices=("coordinate", "controls"),
        default=DEFAULT_TOGGLE_MODE,
        help="How to toggle benchmark start/stop: coordinate click (hard-coded) or accessibility control index",
    )
    parser.add_argument(
        "--list-buttons-only",
        action="store_true",
        help="Open app/select target and print button inventory without starting benchmark",
    )
    return parser.parse_args()


def main() -> None:
    args = _args()
    if args.duration_seconds < 1:
        raise ValueError("--duration-seconds must be >= 1")
    if args.button_index < 1:
        raise ValueError("--button-index must be >= 1")

    run_blackmagic_benchmark(
        dut_name=args.dut_name,
        duration_seconds=args.duration_seconds,
        volume_root=Path(args.volume_root),
        button_index=args.button_index,
        toggle_mode=args.toggle_mode,
        list_buttons_only=args.list_buttons_only,
    )


if __name__ == "__main__":
    main()
