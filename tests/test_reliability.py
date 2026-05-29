from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core.reliability import (
    aggregate_reliability_summaries,
    parse_reliability_log_text,
    reliability_artifact_dir,
    update_reliability_report,
)

EXPECTED_COMPLETED_PASSES = 3
EXPECTED_MISSING_PASSES = 2
EXPECTED_WRITE_ERRORS = 2


SUMMARY_PASS_1 = "\n".join(
    [
        "[2026-05-18 20:40:46] --- Full Test Summary ---",
        "[2026-05-18 20:40:46]   Write Errors: 0",
        "[2026-05-18 20:40:46]   Read Errors: 0",
        "[2026-05-18 20:40:46]   Mismatches:   0",
        "[2026-05-18 20:40:46]   Total Non-Fatal Errors Reported: 0",
        "[2026-05-18 20:40:46] All checks passed. No errors detected.",
        "[2026-05-18 20:40:57] Operation completed successfully.",
    ]
)
SUMMARY_PASS_2 = SUMMARY_PASS_1.replace("20:40:46", "21:40:46").replace("20:40:57", "21:40:57")
SUMMARY_FAIL = SUMMARY_PASS_1.replace("Write Errors: 0", "Write Errors: 2")


def _patch_reliability_step_common(
    monkeypatch: MonkeyPatch,
    windows_reliability: Any,
    *,
    report_path: Path,
    artifact_log: Path,
    report_payload: dict[str, Any],
    candidate_logs: tuple[Path, Path],
) -> None:
    project_log, desktop_log = candidate_logs
    monkeypatch.setattr(windows_reliability.sys, "platform", "win32")
    monkeypatch.setattr(windows_reliability, "PROJECT_LOG", project_log)
    monkeypatch.setattr(windows_reliability, "DESKTOP_LOG", desktop_log)
    monkeypatch.setattr(windows_reliability, "LOG_IMPORT_CANDIDATES", (project_log, desktop_log))
    monkeypatch.setattr(windows_reliability, "resolve_folder_name", lambda part_number: "69-420")
    monkeypatch.setattr(windows_reliability, "load_part_number_and_report", lambda folder_name: ("69-420", report_path))
    monkeypatch.setattr(windows_reliability, "load_report", lambda path: report_payload)
    monkeypatch.setattr(windows_reliability, "reliability_artifact_log_path", lambda part_number: artifact_log)
    monkeypatch.setattr(windows_reliability, "localize_windows_path", lambda path: Path(path))


def test_parse_reliability_log_text_aggregates_all_summary_blocks() -> None:
    summaries = parse_reliability_log_text(f"{SUMMARY_PASS_1}\nnoise\n{SUMMARY_FAIL}\n{SUMMARY_PASS_2}")
    result = aggregate_reliability_summaries(summaries, passes_requested_this_run=2, return_code=0)

    assert result.passes_completed == EXPECTED_COMPLETED_PASSES
    assert result.passes_requested_this_run == EXPECTED_MISSING_PASSES
    assert result.write_errors == EXPECTED_WRITE_ERRORS
    assert result.read_errors == 0
    assert result.mismatches == 0
    assert result.total_non_fatal_errors == 0
    assert result.status == "fail"


def test_update_reliability_report_sets_new_contract_without_compliance_reliability_fields() -> None:
    summaries = parse_reliability_log_text("\n".join([SUMMARY_PASS_1, SUMMARY_PASS_2, SUMMARY_PASS_1]))
    result = aggregate_reliability_summaries(summaries, passes_requested_this_run=1, return_code=0)
    payload: dict[str, Any] = {"compliance": {}}

    update_reliability_report(payload, result)

    assert payload["reliability"]["windows"] == {
        "passes_required": 3,
        "passes_completed": 3,
        "passes_requested_this_run": 1,
        "status": "pass",
        "write_errors": 0,
        "read_errors": 0,
        "mismatches": 0,
        "total_non_fatal_errors": 0,
        "return_code": 0,
    }
    assert payload["compliance"] == {}


def test_reliability_artifact_dir_uses_part_windows_reliability_layout() -> None:
    assert reliability_artifact_dir("69-420") == Path(r"Z:\69-420\Windows\Reliability")


def test_windows_reliability_step_runs_only_missing_passes_and_appends_new_log(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    from drive_qual.platforms.windows import reliability as windows_reliability

    report_path = tmp_path / "report.json"
    artifact_log = tmp_path / "Reliability" / "69-420_reliability.log"
    desktop_log = tmp_path / "disk_test.log"
    project_log = tmp_path / "missing_project_log.log"
    artifact_log.parent.mkdir()
    artifact_log.write_text(SUMMARY_PASS_1 + "\n", encoding="utf-8")
    desktop_log.write_text(f"{SUMMARY_PASS_2}\n{SUMMARY_PASS_1}\n", encoding="utf-8")
    report_payload: dict[str, Any] = {"drive_info": {"apricorn_part_number": "69-420"}, "compliance": {}}
    saved_payloads: list[dict[str, Any]] = []
    calls: list[tuple[str, int]] = []

    _patch_reliability_step_common(
        monkeypatch,
        windows_reliability,
        report_path=report_path,
        artifact_log=artifact_log,
        report_payload=report_payload,
        candidate_logs=(project_log, desktop_log),
    )
    monkeypatch.setattr(windows_reliability, "save_report", lambda path, data: saved_payloads.append(data.copy()))
    monkeypatch.setattr(windows_reliability, "_resolve_drive_target", lambda path: "F:")

    def fake_run_disk_tester(drive_target: str, passes: int) -> int:
        calls.append((drive_target, passes))
        return 0

    monkeypatch.setattr(windows_reliability, "_run_disk_tester", fake_run_disk_tester)

    windows_reliability.run_reliability_step(part_number="69-420")

    assert calls == [("F:", 2)]
    assert desktop_log.exists() is False
    assert parse_reliability_log_text(artifact_log.read_text(encoding="utf-8"))
    assert report_payload["reliability"]["windows"]["passes_completed"] == EXPECTED_COMPLETED_PASSES
    assert report_payload["reliability"]["windows"]["passes_requested_this_run"] == EXPECTED_MISSING_PASSES
    assert report_payload["reliability"]["windows"]["status"] == "pass"
    assert "disk_tester_reliability_result" not in saved_payloads[-1]["compliance"]


def test_windows_reliability_step_uses_project_log_before_desktop(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    from drive_qual.platforms.windows import reliability as windows_reliability

    report_path = tmp_path / "report.json"
    artifact_log = tmp_path / "Reliability" / "69-420_reliability.log"
    project_log = tmp_path / "repo" / "disk_test.log"
    desktop_log = tmp_path / "Desktop" / "disk_test.log"
    project_log.parent.mkdir()
    desktop_log.parent.mkdir()
    project_log.write_text("\n".join([SUMMARY_PASS_1, SUMMARY_PASS_2, SUMMARY_PASS_1]), encoding="utf-8")
    desktop_log.write_text(SUMMARY_PASS_1, encoding="utf-8")
    report_payload: dict[str, Any] = {"drive_info": {"apricorn_part_number": "69-420"}, "compliance": {}}

    _patch_reliability_step_common(
        monkeypatch,
        windows_reliability,
        report_path=report_path,
        artifact_log=artifact_log,
        report_payload=report_payload,
        candidate_logs=(project_log, desktop_log),
    )
    monkeypatch.setattr(windows_reliability, "save_report", lambda path, data: None)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    def fail_run_disk_tester(drive_target: str, passes: int) -> int:
        raise AssertionError("disk_tester.exe should be skipped when Desktop log already has 3 summaries")

    monkeypatch.setattr(windows_reliability, "_run_disk_tester", fail_run_disk_tester)

    windows_reliability.run_reliability_step(part_number="69-420")

    assert project_log.exists() is False
    assert desktop_log.exists() is True
    assert artifact_log.exists()
    assert report_payload["reliability"]["windows"]["passes_completed"] == EXPECTED_COMPLETED_PASSES
    assert report_payload["reliability"]["windows"]["status"] == "pass"


def test_windows_reliability_step_ignores_candidate_log_when_operator_declines(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    from drive_qual.platforms.windows import reliability as windows_reliability

    report_path = tmp_path / "report.json"
    artifact_log = tmp_path / "Reliability" / "69-420_reliability.log"
    project_log = tmp_path / "repo" / "disk_test.log"
    desktop_log = tmp_path / "Desktop" / "disk_test.log"
    project_log.parent.mkdir()
    desktop_log.parent.mkdir()
    project_log.write_text(SUMMARY_PASS_1, encoding="utf-8")
    desktop_log.write_text("\n".join([SUMMARY_PASS_1, SUMMARY_PASS_2, SUMMARY_PASS_1]), encoding="utf-8")
    report_payload: dict[str, Any] = {"drive_info": {"apricorn_part_number": "69-420"}, "compliance": {}}
    calls: list[tuple[str, int]] = []

    _patch_reliability_step_common(
        monkeypatch,
        windows_reliability,
        report_path=report_path,
        artifact_log=artifact_log,
        report_payload=report_payload,
        candidate_logs=(project_log, desktop_log),
    )
    monkeypatch.setattr(windows_reliability, "save_report", lambda path, data: None)
    monkeypatch.setattr(windows_reliability, "_resolve_drive_target", lambda path: "F:")
    monkeypatch.setattr("builtins.input", lambda prompt: "no")

    def fake_run_disk_tester(drive_target: str, passes: int) -> int:
        calls.append((drive_target, passes))
        project_log.write_text("\n".join([SUMMARY_PASS_1, SUMMARY_PASS_2, SUMMARY_PASS_1]), encoding="utf-8")
        return 0

    monkeypatch.setattr(windows_reliability, "_run_disk_tester", fake_run_disk_tester)

    windows_reliability.run_reliability_step(part_number="69-420")

    assert calls == [("F:", 3)]
    assert project_log.exists() is False
    assert desktop_log.exists() is True
    assert report_payload["reliability"]["windows"]["passes_requested_this_run"] == EXPECTED_COMPLETED_PASSES


def test_run_disk_tester_uses_full_test_subcommand(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    from drive_qual.platforms.windows import reliability as windows_reliability

    exe_path = tmp_path / "disk_tester.exe"
    exe_path.write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    class FakeProcess:
        stdout = ["line 1\n"]

        def wait(self) -> int:
            return 0

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        del kwargs
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(windows_reliability, "DISK_TESTER_EXE", exe_path)
    monkeypatch.setattr("drive_qual.platforms.windows.reliability.subprocess.Popen", fake_popen)

    assert windows_reliability._run_disk_tester("E:", 2) == 0
    assert commands == [
        [
            str(exe_path),
            "full-test",
            "--path",
            "E:",
            "--direct-io",
            "--preallocate",
            "--passes",
            "2",
        ]
    ]


def test_normalize_drive_target_accepts_drive_letter_forms() -> None:
    from drive_qual.platforms.windows.reliability import _normalize_drive_target

    assert _normalize_drive_target("f") == "F:"
    assert _normalize_drive_target("F:\\") == "F:"
    assert _normalize_drive_target("F:") == "F:"


def test_resolve_drive_target_uses_bound_apricorn_drive_letter(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.platforms.windows import reliability as windows_reliability

    monkeypatch.setattr(windows_reliability, "resolve_report_dut_name", lambda report_path: "Padlock DT")
    monkeypatch.setattr(
        windows_reliability,
        "resolve_or_bind_dut_device",
        lambda *args, **kwargs: SimpleNamespace(driveLetter="g:\\"),
    )

    assert windows_reliability._resolve_drive_target(Path("report.json")) == "G:"
