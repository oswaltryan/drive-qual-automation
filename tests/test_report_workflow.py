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
    sys.modules.pop("drive_qual.platforms.windows.power_measurements", None)

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
        }:
            raise AssertionError(f"workflows.report imported {name} eagerly")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("drive_qual.workflows.report")

    assert module.STEP_ORDER == EXPECTED_STEP_ORDER


def test_run_report_workflow_imports_performance_step_lazily(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    calls: list[str | None] = []

    class FakePerformanceModule(ModuleType):
        def run_software_step(self, *, part_number: str | None = None) -> None:
            calls.append(part_number)

    fake_software_step = FakePerformanceModule("drive_qual.platforms.performance")
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.performance", fake_software_step)

    module.run_report_workflow(["performance"], part_number="69-420")

    assert calls == ["69-420"]


def test_run_report_workflow_imports_power_measurements_step_lazily(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    calls: list[str] = []

    class FakePowerMeasurementsModule(ModuleType):
        def run_power_measurements_step(self) -> None:
            calls.append("called")

    fake_power_measurements = FakePowerMeasurementsModule("drive_qual.platforms.power_measurements")
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.power_measurements", fake_power_measurements)

    module.run_report_workflow(["power_measurements"])

    assert calls == ["called"]


def test_default_steps_include_all_workflow_steps() -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    assert module._default_steps() == EXPECTED_STEP_ORDER
