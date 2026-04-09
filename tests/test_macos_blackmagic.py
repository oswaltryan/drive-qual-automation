from __future__ import annotations

from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.platforms.macos import blackmagic


def test_choose_drive_script_keeps_applescript_modifier_braces(monkeypatch: MonkeyPatch) -> None:
    rendered_scripts: list[str] = []

    monkeypatch.setattr(blackmagic, "_blackmagic_process_name_candidates", lambda: ("Blackmagic Disk Speed Test",))

    def fake_run_osascript(script: str) -> str:
        rendered_scripts.append(script)
        return "ok"

    monkeypatch.setattr(blackmagic, "_run_osascript", fake_run_osascript)

    blackmagic._run_ui_script(blackmagic._CHOOSE_DRIVE_IN_DIALOG_SCRIPT, target_path="/Volumes/DUT")

    assert rendered_scripts
    assert 'keystroke "g" using {command down, shift down}' in rendered_scripts[0]


def test_window_bounds_script_keeps_applescript_list_braces(monkeypatch: MonkeyPatch) -> None:
    rendered_scripts: list[str] = []

    monkeypatch.setattr(blackmagic, "_blackmagic_process_name_candidates", lambda: ("Blackmagic Disk Speed Test",))

    def fake_run_osascript(script: str) -> str:
        rendered_scripts.append(script)
        return "ok"

    monkeypatch.setattr(blackmagic, "_run_osascript", fake_run_osascript)

    blackmagic._run_ui_script(blackmagic._WINDOW_BOUNDS_SCRIPT)

    assert rendered_scripts
    assert "set {xPos, yPos} to position of targetWindow" in rendered_scripts[0]
    assert "set {winWidth, winHeight} to size of targetWindow" in rendered_scripts[0]


def test_run_automation_uses_hard_coded_dut_volume_path(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    target_volume = tmp_path / "DUT"
    target_volume.mkdir()
    calls: list[tuple[str, dict[str, str]]] = []

    monkeypatch.setattr(blackmagic.sys, "platform", "darwin")
    monkeypatch.setattr(blackmagic, "HARD_CODED_TARGET_VOLUME_PATH", target_volume)
    monkeypatch.setattr(blackmagic, "_close_blackmagic_app", lambda: None)
    monkeypatch.setattr(blackmagic, "_launch_blackmagic_app", lambda: None)
    monkeypatch.setattr(blackmagic, "_click_blackmagic_by_relative_coordinate", lambda _x, _y: "clicked")
    monkeypatch.setattr(blackmagic.time, "sleep", lambda _seconds: None)

    def fake_run_ui_script(script_template: str, **values: str) -> str:
        calls.append((script_template, values))
        if script_template == blackmagic._ENSURE_MAIN_WINDOW_READY_SCRIPT:
            return "main-window-ready"
        return "ok"

    monkeypatch.setattr(blackmagic, "_run_ui_script", fake_run_ui_script)

    blackmagic.run_blackmagic_benchmark_automation("Padlock 3.0", duration_seconds=1)

    choose_calls = [values for template, values in calls if template == blackmagic._CHOOSE_DRIVE_IN_DIALOG_SCRIPT]
    assert len(choose_calls) == 1
    assert choose_calls[0]["target_path"] == target_volume.resolve().as_posix()


def test_parse_blackmagic_read_write_mb_s_parses_labeled_values() -> None:
    raw_text = """
WRITE
456.7
READ
345.6
"""
    parsed = blackmagic.parse_blackmagic_read_write_mb_s(raw_text)
    assert parsed == (345.6, 456.7)


def test_parse_blackmagic_read_write_mb_s_returns_none_when_missing_values() -> None:
    raw_text = "WRITE\n456.7\nSOMETHING ELSE"
    assert blackmagic.parse_blackmagic_read_write_mb_s(raw_text) is None


def test_extract_blackmagic_read_write_from_screenshot_uses_swift_ocr(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    screenshot_path = tmp_path / "capture.png"
    screenshot_path.write_bytes(b"png")
    calls: list[list[str]] = []
    ocr_output = "WRITE\n500.5\nREAD\n400.4\n"

    def fake_run(command: list[str], **_kwargs: object) -> object:
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": ocr_output, "stderr": ""})()

    monkeypatch.setattr("drive_qual.platforms.macos.blackmagic.subprocess.run", fake_run)

    parsed = blackmagic.extract_blackmagic_read_write_from_screenshot(screenshot_path)

    assert calls
    assert calls[0][0] == "swift"
    assert calls[0][1] == "-e"
    assert calls[0][-1] == str(screenshot_path)
    assert parsed == (400.4, 500.5)


def test_extract_blackmagic_read_write_from_screenshot_returns_none_when_unparseable(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    screenshot_path = tmp_path / "capture.png"
    screenshot_path.write_bytes(b"png")

    def fake_run(command: list[str], **_kwargs: object) -> object:
        return type("Result", (), {"returncode": 0, "stdout": "NO READ WRITE VALUES", "stderr": ""})()

    monkeypatch.setattr("drive_qual.platforms.macos.blackmagic.subprocess.run", fake_run)

    parsed = blackmagic.extract_blackmagic_read_write_from_screenshot(screenshot_path)

    assert parsed is None
