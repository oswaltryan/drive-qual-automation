from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.cli import main as cli_main
from drive_qual.core import config, power_measurements, report_session, storage_paths
from drive_qual.core.product_profiles import required_power_fields_for_dut
from drive_qual.core.report_session import TEMPLATE_NAME
from drive_qual.integrations.instruments import tektronix
from drive_qual.platforms.performance_common import find_report_dut_key
from drive_qual.workflows import equipment, fortress_l2, orchestrator
from drive_qual.workflows import report as report_workflow


def test_l2_setup_copies_metadata_without_l3_results(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source_root = tmp_path / "L3"
    source = source_root / "28-0017(WD 500GB)"
    source.mkdir(parents=True)
    (source / TEMPLATE_NAME).write_text(
        json.dumps(
            {
                "drive_info": {
                    "apricorn_part_number": "28-0017",
                    "manufacturer": "Western Digital",
                    "manufacturer_part_number": "WD500LPZX",
                    "capacity": "500GB",
                    "form_factor": "2.5",
                    "technology": "HDD",
                },
                "equipment": {
                    "scope": {"model": "Tektronix"},
                    "dut": {"Fortress L3": {"serial_number": "old-serial"}},
                },
                "power": {"Fortress L3": {"max_inrush_current": {"windows": 1.5}}},
                "performance": {"Fortress L3": {"Windows": {"ATTO": {"read": 1}}}},
            }
        ),
        encoding="utf-8",
    )
    output_root = tmp_path / "L2"
    sessions: list[tuple[str, str | None]] = []
    monkeypatch.setattr(fortress_l2, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(
        fortress_l2,
        "report_path_for",
        lambda folder: output_root / folder / TEMPLATE_NAME,
    )
    monkeypatch.setattr(fortress_l2, "set_current_session", lambda folder, product: sessions.append((folder, product)))

    assert fortress_l2.run_l2_setup("28-0017(WD 500GB)") == "28-0017"
    destination = output_root / "28-0017" / TEMPLATE_NAME
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["qualification_product"] == "Fortress L2"
    assert report["drive_info"]["manufacturer_part_number"] == "WD500LPZX"
    assert report["equipment"]["scope"] == {"model": "Tektronix"}
    assert "dut" not in report["equipment"]
    assert report["power"] == {}
    assert report["performance"] == {}
    assert sessions == [("28-0017", "Western Digital")]

    report["power"] = {"Fortress L2": {"captured": True}}
    destination.write_text(json.dumps(report), encoding="utf-8")
    fortress_l2.run_l2_setup("28-0017")
    assert json.loads(destination.read_text(encoding="utf-8"))["power"]["Fortress L2"] == {"captured": True}


def test_l2_equipment_uses_only_l2_dut() -> None:
    data = {"qualification_product": "Fortress L2", "drive_info": {"form_factor": "2.5"}}
    assert equipment._dut_from_form_factor(data) == {"Fortress L2": {"serial_number": None}}
    assert "Fortress L3" in equipment._dut_from_form_factor({"drive_info": {"form_factor": "2.5"}})


def test_l2_profile_and_exact_performance_key() -> None:
    assert orchestrator.WORKFLOW_PROFILES["fortress-l2"] == (
        "drive_info",
        "equipment",
        "power_measurements",
        "performance",
        "temperature",
    )
    assert find_report_dut_key({"Fortress": {}, "Fortress L2": {}}, "Fortress L2") == "Fortress L2"


def test_output_root_override_applies_to_windows_paths(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv(config.OUTPUT_ROOT_ENV_VAR, "Z:/Done/L2")
    assert config.windows_share_root() == "Z:/Done/L2"
    assert config.local_storage_root("win32") == Path("Z:\\")


def test_power_csv_resolves_report_below_l2_root(monkeypatch: MonkeyPatch) -> None:
    report_path = Path("Z:/Done/L2/28-0017/drive_qualification_report_atomic_tests.json")
    monkeypatch.setattr(power_measurements, "SCOPE_ARTIFACT_ROOT", "Z:/Done/L2")
    monkeypatch.setattr(
        power_measurements,
        "report_path_for",
        lambda folder: report_path if folder == "28-0017" else None,
    )
    monkeypatch.setattr(power_measurements, "load_report", lambda path: {"power": {"Fortress L2": {}}})
    resolved = power_measurements._report_power_data("Z:/Done/L2/28-0017/Windows/In Rush Current/Fortress.csv")
    assert resolved is not None
    assert resolved[1] == report_path


def test_l2_capture_validation_rejects_missing_values(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(report_workflow, "platform_key", lambda: "windows")
    monkeypatch.setattr(report_workflow, "report_path_for", lambda _folder: Path("report.json"))
    monkeypatch.setattr(
        report_workflow,
        "load_report",
        lambda _path: {
            "power": {"Fortress L2": {"max_inrush_current": {"windows": 0.4}}},
            "equipment": {"windows_host": {"software": [{"name": "CrystalDiskMark"}]}},
            "performance": {"Fortress L2": {"Windows": {"CrystalDiskMark": {"read": 400, "write": None}}}},
        },
    )
    with pytest.raises(RuntimeError, match="max_read_write_current"):
        report_workflow._validate_l2_power_capture("28-0017")
    with pytest.raises(RuntimeError, match="CrystalDiskMark"):
        report_workflow._validate_l2_performance_capture("28-0017")


def test_normal_step_command_routes_archived_project_to_l2(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    archive = tmp_path / "L3"
    source = archive / "28-0017(WD 500GB)"
    source.mkdir(parents=True)
    (source / TEMPLATE_NAME).write_text(
        json.dumps({"drive_info": {"apricorn_part_number": "28-0017"}}), encoding="utf-8"
    )
    monkeypatch.setattr(cli_main, "L3_SOURCE_ROOT", archive)
    monkeypatch.setenv(config.OUTPUT_ROOT_ENV_VAR, "")
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeReportModule(ModuleType):
        def run_report_workflow(self, steps: list[str], **kwargs: object) -> None:
            calls.append((steps, kwargs))

    monkeypatch.setitem(sys.modules, "drive_qual.workflows.report", FakeReportModule("drive_qual.workflows.report"))
    cli_main.main(["step", "power", "--part-number", "28-0017"])

    assert calls == [
        (
            ["power_measurements"],
            {"part_number": "28-0017", "scope_profile": None, "l2": True},
        )
    ]
    assert config.windows_share_root() == "Z:/Done/L2"


@pytest.mark.parametrize(
    ("host", "os_name", "tool"),
    [
        ("windows", "Windows", "CrystalDiskMark"),
        ("linux", "Linux", "Disks (native)"),
        ("macos", "macOS", "Blackmagic Disk Speed Test"),
    ],
)
def test_l2_validates_results_for_current_host(monkeypatch: MonkeyPatch, host: str, os_name: str, tool: str) -> None:
    monkeypatch.setattr(report_workflow, "platform_key", lambda: host)
    fields = {
        field: {"windows": None, "linux": None, "macos": None, host: 500}
        for field in required_power_fields_for_dut("Fortress L2")
    }
    performance_values: dict[str, int | None] = {"read": 400, "write": 300}
    report = {
        "power": {"Fortress L2": fields},
        "equipment": {f"{host}_host": {"software": [{"name": tool}]}},
        "performance": {"Fortress L2": {os_name: {tool: performance_values}}},
    }
    monkeypatch.setattr(report_workflow, "load_report", lambda _path: report)

    report_workflow._validate_l2_power_capture("28-0017")
    report_workflow._validate_l2_performance_capture("28-0017")

    fields["max_inrush_current"][host] = None
    with pytest.raises(RuntimeError, match="max_inrush_current"):
        report_workflow._validate_l2_power_capture("28-0017")
    performance_values["write"] = None
    with pytest.raises(RuntimeError, match=tool.replace("(", r"\(").replace(")", r"\)")):
        report_workflow._validate_l2_performance_capture("28-0017")


def test_reopening_l2_uses_local_mount_and_preserves_captures(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source_root = tmp_path / "Done" / "L3"
    source = source_root / "88-0042"
    source.mkdir(parents=True)
    (source / TEMPLATE_NAME).write_text(
        json.dumps({"drive_info": {"apricorn_part_number": "88-0042"}}), encoding="utf-8"
    )
    monkeypatch.setattr(fortress_l2, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(report_session, "SCOPE_ARTIFACT_ROOT", "Z:/Done/L2")
    monkeypatch.setattr(storage_paths, "SCOPE_ARTIFACT_ROOT", "Z:/Done/L2")
    monkeypatch.setattr(storage_paths, "local_storage_root", lambda: tmp_path)
    monkeypatch.setattr(fortress_l2, "set_current_session", lambda *_args: None)
    destination = tmp_path / "Done" / "L2" / "88-0042" / TEMPLATE_NAME
    destination.parent.mkdir(parents=True)
    captures = {
        "qualification_product": "Fortress L2",
        "drive_info": {"manufacturer": "Samsung"},
        "power": {"Fortress L2": {"max_inrush_current": {"linux": 100}}},
    }
    destination.write_text(json.dumps(captures), encoding="utf-8")

    fortress_l2.run_l2_setup("88-0042")

    assert json.loads(destination.read_text(encoding="utf-8")) == captures


@pytest.mark.parametrize("os_name", ["Windows", "Linux", "macOS"])
def test_scope_capture_creates_directories_under_l2_root(monkeypatch: MonkeyPatch, os_name: str) -> None:
    commands: list[str] = []
    updated: list[str] = []
    monkeypatch.setattr(tektronix, "SCOPE_ARTIFACT_ROOT", "Z:/Done/L2")
    monkeypatch.setattr(tektronix, "scpi_command", lambda command, **_kwargs: commands.append(command))
    monkeypatch.setattr(tektronix, "update_report_power_from_csv_path", lambda path: updated.append(path))
    capture = f"Z:/Done/L2/28-0017/{os_name}/Max IO/Fortress.csv"

    tektronix.save_measurements(capture)

    assert f'FILESystem:MKDir "Z:/Done/L2/28-0017/{os_name}/Max IO"' in commands
    assert f'SAVe:EVENTtable:MEASUrement "{capture}"' in commands
    assert updated == [capture]


@pytest.mark.parametrize("host", ["windows", "linux", "macos"])
def test_l2_resume_tracks_each_host_separately(monkeypatch: MonkeyPatch, tmp_path: Path, host: str) -> None:
    monkeypatch.setattr(orchestrator, "platform_key", lambda: host)
    legacy_path = tmp_path / "workflow_run_manifest.json"
    legacy_path.write_text(
        json.dumps({"profile": "fortress-l2", "steps": [{"name": "power_measurements", "status": "completed"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestrator, "_manifest_path_for_folder", lambda _folder: legacy_path)

    path, manifest = orchestrator._initialize_manifest(
        selected_steps=("power_measurements", "performance"),
        effective_profile="fortress-l2",
        part_number="28-0017",
        resume=True,
    )

    assert path.name == f"workflow_run_manifest_{host}.json"
    assert manifest["steps"][0]["status"] == ("completed" if host == "windows" else "pending")
