from __future__ import annotations

import builtins
import importlib
import sys
from types import ModuleType
from typing import Any

from _pytest.monkeypatch import MonkeyPatch

EXPECTED_STEP_ORDER = ("drive_info", "equipment", "power_measurements", "performance")


def test_report_workflow_import_does_not_import_software_step(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    sys.modules.pop("drive_qual.platforms.windows.performance", None)

    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "drive_qual.platforms.windows.performance":
            raise AssertionError("workflows.report imported platforms.windows.performance eagerly")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("drive_qual.workflows.report")

    assert module.STEP_ORDER == EXPECTED_STEP_ORDER


def test_run_report_workflow_imports_performance_step_lazily(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    calls: list[str | None] = []
    fake_software_step = ModuleType("drive_qual.platforms.windows.performance")

    def run_software_step(*, part_number: str | None = None) -> None:
        calls.append(part_number)

    fake_software_step.run_software_step = run_software_step  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.windows.performance", fake_software_step)

    module.run_report_workflow(["performance"], part_number="69-420")

    assert calls == ["69-420"]
