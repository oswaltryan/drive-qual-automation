from __future__ import annotations

import pytest
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.cli.interrupts import KEYBOARD_INTERRUPT_EXIT_CODE, run_cli_with_interrupt_handling
from drive_qual.core import report_session


def _raise_keyboard_interrupt(*_args: object, **_kwargs: object) -> None:
    raise KeyboardInterrupt


def test_shared_handler_returns_success_when_action_completes(capsys: CaptureFixture[str]) -> None:
    assert run_cli_with_interrupt_handling(lambda: None) == 0
    assert capsys.readouterr().err == ""


def test_shared_handler_reports_keyboard_interrupt_without_traceback(capsys: CaptureFixture[str]) -> None:
    assert run_cli_with_interrupt_handling(_raise_keyboard_interrupt) == KEYBOARD_INTERRUPT_EXIT_CODE
    assert capsys.readouterr().err == "\nCancelled by operator.\n"


def test_drive_qual_start_handles_keyboard_interrupt_from_workflow(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    from drive_qual.cli import main as cli_main

    sessions = (
        report_session.SessionEntry("69-420", "Apricorn"),
        report_session.SessionEntry("29-0031", "Apricorn"),
    )
    monkeypatch.setattr(report_session, "list_current_sessions", lambda: sessions)
    monkeypatch.setattr("builtins.input", _raise_keyboard_interrupt)

    assert cli_main.main(["start"]) == KEYBOARD_INTERRUPT_EXIT_CODE
    captured = capsys.readouterr()
    assert "Available drive sessions:" in captured.out
    assert captured.err == "\nCancelled by operator.\n"


@pytest.mark.parametrize(
    ("module_name", "private_entrypoint", "public_entrypoint"),
    [
        ("drive_qual.workflows.report", "_run_report_workflow_cli", "run_report_workflow_cli"),
        ("drive_qual.reports.generate", "_run_report_generate_cli", "run_report_generate_cli"),
        (
            "drive_qual.cli.post_process_temperature",
            "_run_temperature_post_process_cli",
            "run_temperature_post_process_cli",
        ),
    ],
)
def test_compatibility_entrypoints_handle_keyboard_interrupt(
    module_name: str,
    private_entrypoint: str,
    public_entrypoint: str,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    module = __import__(module_name, fromlist=[public_entrypoint])
    monkeypatch.setattr(module, private_entrypoint, _raise_keyboard_interrupt)

    assert getattr(module, public_entrypoint)() == KEYBOARD_INTERRUPT_EXIT_CODE
    assert capsys.readouterr().err == "\nCancelled by operator.\n"
