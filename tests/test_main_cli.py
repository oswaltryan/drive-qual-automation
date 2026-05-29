from __future__ import annotations

import builtins
import importlib
import sys
from types import ModuleType
from typing import Any

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch


def test_main_cli_prints_same_man_page_for_empty_and_help(capsys: CaptureFixture[str]) -> None:
    from drive_qual.cli.main import main

    main([])
    empty_output = capsys.readouterr().out
    main(["--help"])
    help_output = capsys.readouterr().out

    assert empty_output == help_output
    assert "Drive Qualification Automation" in empty_output
    assert "drive-qual step power --part-number 69-420" in empty_output


def test_main_cli_help_does_not_import_windows_workflows(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.cli.main", None)
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name in {
            "drive_qual.platforms.windows.performance",
            "drive_qual.platforms.windows.power_measurements",
            "drive_qual.platforms.windows.usb_if",
        }:
            raise AssertionError(f"drive-qual help imported {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module = importlib.import_module("drive_qual.cli.main")

    module.main([])


def test_main_cli_step_alias_dispatches_to_report_workflow(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.cli import main as cli_main

    calls: list[dict[str, Any]] = []

    class FakeReportModule(ModuleType):
        STEP_ORDER = ("drive_info", "equipment", "power_measurements", "performance", "usb_if", "temperature")

        def run_report_workflow(
            self,
            steps: list[str] | None = None,
            *,
            part_number: str | None = None,
            scope_profile: str | None = None,
            profile: str | None = None,
            resume: bool = False,
        ) -> None:
            calls.append(
                {
                    "steps": steps,
                    "part_number": part_number,
                    "scope_profile": scope_profile,
                    "profile": profile,
                    "resume": resume,
                }
            )

    monkeypatch.setitem(sys.modules, "drive_qual.workflows.report", FakeReportModule("drive_qual.workflows.report"))

    cli_main.main(["step", "power", "--part-number", "69-420"])

    assert calls == [
        {
            "steps": ["power_measurements"],
            "part_number": "69-420",
            "scope_profile": None,
            "profile": None,
            "resume": False,
        }
    ]


def test_main_cli_usbif_alias_dispatches_to_report_workflow(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.cli import main as cli_main

    calls: list[dict[str, Any]] = []

    class FakeReportModule(ModuleType):
        STEP_ORDER = ("drive_info", "equipment", "power_measurements", "performance", "usb_if", "temperature")

        def run_report_workflow(
            self,
            steps: list[str] | None = None,
            *,
            part_number: str | None = None,
            scope_profile: str | None = None,
            profile: str | None = None,
            resume: bool = False,
        ) -> None:
            calls.append(
                {
                    "steps": steps,
                    "part_number": part_number,
                    "scope_profile": scope_profile,
                    "profile": profile,
                    "resume": resume,
                }
            )

    monkeypatch.setitem(sys.modules, "drive_qual.workflows.report", FakeReportModule("drive_qual.workflows.report"))

    cli_main.main(["step", "usbif", "--part-number", "69-420"])

    assert calls == [
        {
            "steps": ["usb_if"],
            "part_number": "69-420",
            "scope_profile": None,
            "profile": None,
            "resume": False,
        }
    ]
