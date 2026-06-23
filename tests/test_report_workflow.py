from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

EXPECTED_STEP_ORDER = (
    "drive_info",
    "equipment",
    "power_measurements",
    "performance",
    "usb_if",
    "temperature",
    "reliability",
)
EXPECTED_DEFAULT_PROFILE = ("drive_info", "equipment", "power_measurements", "performance", "usb_if", "reliability")


def _complete_report_payload() -> dict[str, Any]:
    return {
        "equipment": {
            "dut": {"Padlock DT": {"serial_number": "ABC123"}},
            "windows_host": {
                "software": [
                    {"name": "CrystalDiskInfo", "version": "8.8.9"},
                    {"name": "CrystalDiskMark", "version": "7.0.0"},
                    {"name": "ATTO", "version": "4.0.0f1"},
                ]
            },
            "linux_host": {"software": [{"name": "Disks (native)", "version": None}]},
            "macos_host": {"software": [{"name": "Blackmagic Disk Speed Test", "version": "4.2"}]},
        },
        "power": {
            "Padlock DT": {
                "max_inrush_current_5v": {"windows": 1.0, "linux": 1.0, "macos": 1.0},
                "max_inrush_current_12v": {"windows": 1.0, "linux": 1.0, "macos": 1.0},
                "max_read_write_current_5v": {"windows": 1.0, "linux": 1.0, "macos": 1.0},
                "rms_read_write_current_5v": {"windows": 1.0, "linux": 1.0, "macos": 1.0},
                "max_read_write_current_12v": {"windows": 1.0, "linux": 1.0, "macos": 1.0},
                "rms_read_write_current_12v": {"windows": 1.0, "linux": 1.0, "macos": 1.0},
            }
        },
        "performance": {
            "Padlock DT": {
                "Windows": {
                    "CrystalDiskInfo": {"screenshot": "cdi.png"},
                    "CrystalDiskMark": {"read": 100.0, "write": 100.0},
                    "ATTO": {"read": 100.0, "write": 100.0},
                },
                "Linux": {"Disks (native)": {"read": 100.0, "write": 100.0}},
                "macOS": {"Blackmagic Disk Speed Test": {"read": 100.0, "write": 100.0}},
            }
        },
        "reliability": {
            "windows": {
                "passes_required": 3,
                "passes_completed": 3,
                "status": "pass",
            }
        },
    }


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
            "drive_qual.platforms.windows.usb_if",
            "drive_qual.platforms.windows.reliability",
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


def test_run_report_workflow_imports_usb_if_step_lazily(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    calls: list[str | None] = []

    class FakeUsbIfModule(ModuleType):
        def run_usb_if_step(self, part_number: str | None = None) -> None:
            calls.append(part_number)

    fake_usb_if = FakeUsbIfModule("drive_qual.workflows.usb_if")
    monkeypatch.setitem(sys.modules, "drive_qual.workflows.usb_if", fake_usb_if)

    module.run_report_workflow(["usb_if"], part_number="69-420")

    assert calls == ["69-420"]


def test_run_report_workflow_imports_reliability_step_lazily(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    calls: list[str | None] = []

    class FakeReliabilityModule(ModuleType):
        def run_reliability_step(self, *, part_number: str | None = None) -> None:
            calls.append(part_number)

    fake_reliability = FakeReliabilityModule("drive_qual.platforms.windows.reliability")
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.windows.reliability", fake_reliability)

    module.run_report_workflow(["reliability"], part_number="69-420")

    assert calls == ["69-420"]


def test_default_steps_include_all_workflow_steps() -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    assert module._default_steps() == EXPECTED_STEP_ORDER


def test_run_report_workflow_rejects_steps_and_profile() -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    with pytest.raises(ValueError, match="Use either --steps or --profile"):
        module.run_report_workflow(["performance"], profile="default")


def test_run_report_workflow_delegates_profile_execution_to_orchestrator(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")

    captured: dict[str, Any] = {}

    def fake_execute_orchestrated_workflow(
        *,
        selected_steps: tuple[str, ...],
        step_runners: dict[str, Any],
        profile: str | None,
        part_number: str | None,
        resume: bool,
    ) -> None:
        captured["selected_steps"] = selected_steps
        captured["step_runner_keys"] = tuple(step_runners)
        captured["profile"] = profile
        captured["part_number"] = part_number
        captured["resume"] = resume

    monkeypatch.setattr(module, "execute_orchestrated_workflow", fake_execute_orchestrated_workflow)

    module.run_report_workflow(
        part_number="69-420",
        profile="default",
        resume=True,
    )

    assert captured["selected_steps"] == EXPECTED_DEFAULT_PROFILE
    assert captured["step_runner_keys"] == EXPECTED_STEP_ORDER
    assert captured["profile"] == "default"
    assert captured["part_number"] == "69-420"
    assert captured["resume"] is True


def test_run_report_workflow_clears_current_marker_when_report_is_complete(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")
    cleared: list[str] = []

    monkeypatch.setattr(module, "execute_orchestrated_workflow", lambda **kwargs: None)
    monkeypatch.setattr(module, "report_path_for", lambda folder_name: Path(f"Z:/{folder_name}/report.json"))
    monkeypatch.setattr(module, "load_report", lambda report_path: _complete_report_payload())
    monkeypatch.setattr(module, "clear_current_session", lambda: cleared.append("cleared"))

    module.run_report_workflow(["drive_info"], part_number="69-420")

    assert cleared == ["cleared"]


def test_run_report_workflow_keeps_current_marker_when_report_is_incomplete(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.workflows.report", None)
    module = importlib.import_module("drive_qual.workflows.report")
    cleared: list[str] = []
    payload = _complete_report_payload()
    payload["power"]["Padlock DT"]["max_read_write_current_12v"]["windows"] = None

    monkeypatch.setattr(module, "execute_orchestrated_workflow", lambda **kwargs: None)
    monkeypatch.setattr(module, "report_path_for", lambda folder_name: Path(f"Z:/{folder_name}/report.json"))
    monkeypatch.setattr(module, "load_report", lambda report_path: payload)
    monkeypatch.setattr(module, "clear_current_session", lambda: cleared.append("cleared"))

    module.run_report_workflow(["drive_info"], part_number="69-420")

    assert cleared == []
