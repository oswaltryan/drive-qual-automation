from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
from typing import Any

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core import report_session
from drive_qual.workflows import drive_info, equipment

DRIVE_INFO_VALUES = {
    "apricorn_part_number": "69-420",
    "manufacturer": "Apricorn",
    "manufacturer_part_number": "ASK-256",
    "capacity": "256GB",
    "firmware": "1.0.0",
    "form_factor": "nvme",
    "interface": "USB 3.2",
    "technology": "SSD",
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_current_marker(path: Path, folder: str, product: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"folder": folder, "product": product}) + "\n", encoding="utf-8")


def _localize_to_tmp(tmp_path: Path, path: str | Path) -> Path:
    windows_path = PureWindowsPath(str(path))
    return tmp_path.joinpath(*windows_path.parts[1:])


def _drive_info_template() -> dict[str, Any]:
    return {
        "drive_info": {key: None for key, _label in drive_info.FIELDS},
        "equipment": {},
        "power": {},
        "performance": {},
        "temperature": {},
    }


def _report_with_drive_info(**overrides: Any) -> dict[str, Any]:
    values = dict(DRIVE_INFO_VALUES)
    values.update(overrides)
    return {
        "drive_info": values,
        "equipment": {
            "scope": {"model": None, "version": None, "serial_number": None},
            "probe_current": {"model": None, "channel": None, "serial_number": None},
            "probe_voltage": {"model": None, "channel": None, "serial_number": None},
        },
        "power": {},
        "performance": {},
        "temperature": {},
    }


def test_current_session_folder_name_reads_localized_marker(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(report_session, "localize_windows_path", lambda path: _localize_to_tmp(tmp_path, path))
    _write_current_marker(_localize_to_tmp(tmp_path, report_session.CURRENT_MARKER), "69-420", product="Apricorn")

    assert report_session.current_session_folder_name() == "69-420"


def test_load_report_uses_localized_path(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(report_session, "localize_windows_path", lambda path: _localize_to_tmp(tmp_path, path))
    local_report_path = _localize_to_tmp(tmp_path, report_session.report_path_for("69-420"))
    _write_json(local_report_path, _report_with_drive_info())

    loaded = report_session.load_report(report_session.report_path_for("69-420"))

    assert loaded["drive_info"] == DRIVE_INFO_VALUES


def test_drive_info_reuses_current_report_from_localized_path_without_prompting(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    template_path = tmp_path / "template.json"
    report_path = report_session.report_path_for("69-420")
    local_report_path = _localize_to_tmp(tmp_path, report_path)
    _write_json(template_path, _drive_info_template())
    _write_json(local_report_path, _report_with_drive_info())
    _write_current_marker(_localize_to_tmp(tmp_path, report_session.CURRENT_MARKER), "69-420", product="Apricorn")

    saved_sessions: list[tuple[str, str | None]] = []

    monkeypatch.setattr(report_session, "localize_windows_path", lambda path: _localize_to_tmp(tmp_path, path))
    monkeypatch.setattr(drive_info, "DEFAULT_TEMPLATE", template_path)
    monkeypatch.setattr(
        drive_info,
        "set_current_session",
        lambda folder_name, product_name=None: saved_sessions.append((folder_name, product_name)),
    )

    def unexpected_input(prompt: str) -> str:
        raise AssertionError(f"drive_info prompted unexpectedly: {prompt}")

    monkeypatch.setattr("builtins.input", unexpected_input)

    drive_info.run_drive_info_prompt()

    updated = json.loads(local_report_path.read_text(encoding="utf-8"))
    assert updated["drive_info"] == DRIVE_INFO_VALUES
    assert saved_sessions == [("69-420", "Apricorn")]


def test_drive_info_reuses_current_report_without_prompting(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    template_path = tmp_path / "template.json"
    report_path = tmp_path / "report.json"
    _write_json(template_path, _drive_info_template())
    _write_json(report_path, _report_with_drive_info())

    saved_sessions: list[tuple[str, str | None]] = []

    monkeypatch.setattr(drive_info, "DEFAULT_TEMPLATE", template_path)
    monkeypatch.setattr(drive_info, "current_session_folder_name", lambda: "69-420")
    monkeypatch.setattr(drive_info, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(
        drive_info,
        "set_current_session",
        lambda folder_name, product_name=None: saved_sessions.append((folder_name, product_name)),
    )

    def unexpected_input(prompt: str) -> str:
        raise AssertionError(f"drive_info prompted unexpectedly: {prompt}")

    monkeypatch.setattr("builtins.input", unexpected_input)

    drive_info.run_drive_info_prompt()

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert updated["drive_info"] == DRIVE_INFO_VALUES
    assert saved_sessions == [("69-420", "Apricorn")]


def test_drive_info_only_prompts_for_missing_fields(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    template_path = tmp_path / "template.json"
    report_path = tmp_path / "report.json"
    _write_json(template_path, _drive_info_template())
    _write_json(report_path, _report_with_drive_info(manufacturer_part_number=None))

    prompts: list[str] = []

    monkeypatch.setattr(drive_info, "DEFAULT_TEMPLATE", template_path)
    monkeypatch.setattr(drive_info, "current_session_folder_name", lambda: "69-420")
    monkeypatch.setattr(drive_info, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(drive_info, "set_current_session", lambda folder_name, product_name=None: None)

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "ASK-256"

    monkeypatch.setattr("builtins.input", fake_input)

    drive_info.run_drive_info_prompt()

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert updated["drive_info"]["manufacturer_part_number"] == "ASK-256"
    assert prompts == ["Manufacturer Part Number: "]


def test_equipment_skips_scope_prompt_when_profile_data_exists(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report = _report_with_drive_info()
    report["equipment"] = {
        "scope": {"model": "Tektronix MSO54", "version": "2.0.3", "serial_number": "B013976"},
        "probe_current": {"model": "TCP202A", "channel": "4", "serial_number": "C004510"},
        "probe_voltage": {"model": "TPP0500B", "channel": "2", "serial_number": "C166742"},
    }
    _write_json(report_path, report)

    monkeypatch.setattr(equipment, "resolve_folder_name", lambda part_number: "69-420")
    monkeypatch.setattr(equipment, "report_path_for", lambda folder_name: report_path)

    def unexpected_input(prompt: str) -> str:
        raise AssertionError(f"equipment prompted unexpectedly: {prompt}")

    monkeypatch.setattr("builtins.input", unexpected_input)

    equipment.run_equipment_prompt()

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert updated["equipment"]["dut"] == ["Padlock NVX"]


def test_equipment_prompts_for_scope_profile_when_scope_data_missing(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    _write_json(report_path, _report_with_drive_info())

    prompts: list[str] = []

    monkeypatch.setattr(equipment, "resolve_folder_name", lambda part_number: "69-420")
    monkeypatch.setattr(equipment, "report_path_for", lambda folder_name: report_path)

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "tektronix"

    monkeypatch.setattr("builtins.input", fake_input)

    equipment.run_equipment_prompt()

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert updated["equipment"]["scope"]["model"] == "Tektronix MSO54"
    assert updated["equipment"]["probe_current"]["channel"] == "4"
    assert prompts == ["Scope profile (tektronix/rigol): "]
