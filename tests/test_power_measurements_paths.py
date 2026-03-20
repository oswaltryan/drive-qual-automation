from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core import power_measurements
from drive_qual.core.report_session import report_path_for
from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, artifact_dir, artifact_file
from drive_qual.integrations.instruments import tektronix

EXPECTED_MAX_RW_CURRENT = 453.56
EXPECTED_RMS_RW_CURRENT = 258.6
TEK_CSV_LINES = [
    "TekScope,Version 2.0.3",
    "Date-Time,2026-03-06T11:25:30-08:00",
    "",
    "Measurement Results",
    (
        "Name,Measurement,Label,Source,Mean',Min',Max',Pk-Pk',Std Dev',Population',"
        "Accum-Mean,Accum-Min,Accum-Max,Accum-Pk-Pk,Accum-Std Dev,Accum-Population,"
    ),
    (
        'Meas1, Maximum, Maximum," Ch 4 ",448.62 mA,448.62 mA,448.62 mA,0.0000 A,'
        "0.0000 A,1,448.48 mA,444.94 mA,453.56 mA,8.6250 mA,1.5484 mA,132, , , , "
        ", , , , , , , "
    ),
    "",
    (
        'Meas3, RMS, RMS," Ch 4 ",258.70 mA,258.70 mA,258.70 mA,0.0000 A,0.0000 A,1,'
        "258.60 mA,258.04 mA,259.17 mA,1.1256 mA,212.51 uA,132, , , , , , , , , , , , "
    ),
]


def _write_max_io_csv(csv_path: Path) -> None:
    csv_path.write_text("\n".join(TEK_CSV_LINES), encoding="utf-8")


def test_artifact_paths_use_configured_scope_root() -> None:
    assert SCOPE_ARTIFACT_ROOT == "Z:/"
    assert artifact_dir("69-420", "Windows", "Max IO") == r"Z:\69-420\Windows\Max IO"
    assert (
        artifact_file("69-420", "Windows", "Max IO", "Secure Key 3.0.csv")
        == r"Z:\69-420\Windows\Max IO\Secure Key 3.0.csv"
    )
    assert report_path_for("69-420") == Path(r"Z:\69-420\drive_qualification_report_atomic_tests.json")


def test_save_measurements_writes_directly_to_scope_artifact_path(monkeypatch: MonkeyPatch) -> None:
    commands: list[str] = []
    updated_paths: list[str] = []

    monkeypatch.setattr(
        tektronix,
        "_ensure_share_structure",
        lambda part_number, category: commands.append(f"mkdir:{part_number}:{category}"),
    )
    monkeypatch.setattr(tektronix, "scpi_command", lambda cmd, **kwargs: commands.append(cmd))
    monkeypatch.setattr(tektronix, "update_report_power_from_csv_path", lambda path: updated_paths.append(path))

    saved_path = tektronix.save_measurements(r"Z:\69-420\Windows\Max IO\Padlock Dt.csv")

    assert saved_path == r"Z:/69-420/Windows/Max IO/Padlock Dt.csv"
    assert 'SAVe:EVENTtable:MEASUrement "Z:/69-420/Windows/Max IO/Padlock Dt.csv"' in commands
    assert updated_paths == [r"Z:/69-420/Windows/Max IO/Padlock Dt.csv"]


def test_extract_power_values_from_max_io_csv() -> None:
    workspace_tmp = Path("tests/.tmp/test_extract_power_values")
    if workspace_tmp.exists():
        shutil.rmtree(workspace_tmp)
    csv_path = workspace_tmp / "Z" / "69-420" / "Windows" / "Max IO" / "Secure Key 3.0.csv"
    csv_path.parent.mkdir(parents=True)
    _write_max_io_csv(csv_path)

    values = power_measurements.extract_power_values_from_csv(str(csv_path))

    assert values["max_read_write_current"] == EXPECTED_MAX_RW_CURRENT
    assert values["rms_read_write_current"] == EXPECTED_RMS_RW_CURRENT
    shutil.rmtree(workspace_tmp)


def test_resolve_dut_key_uses_business_name_aliases() -> None:
    power: dict[str, dict[str, Any]] = {
        "Padlock DT": {},
        "Padlock DT FIPS": {},
    }

    assert power_measurements._resolve_dut_key(power, "Secure Key 3.0") == "Padlock DT"
    assert power_measurements._resolve_dut_key(power, "Secure Key 3.0 FIPS") == "Padlock DT FIPS"


def test_apply_csv_to_power_uses_alias_mapping_for_max_io() -> None:
    workspace_tmp = Path("tests/.tmp/test_apply_csv_alias")
    if workspace_tmp.exists():
        shutil.rmtree(workspace_tmp)
    csv_path = workspace_tmp / "Z" / "69-420" / "Windows" / "Max IO" / "Secure Key 3.0.csv"
    csv_path.parent.mkdir(parents=True)
    _write_max_io_csv(csv_path)

    power: dict[str, dict[str, dict[str, float | None]]] = {
        "Padlock DT": {
            "max_read_write_current": {"linux": None, "macos": None, "windows": None},
            "rms_read_write_current": {"linux": None, "macos": None, "windows": None},
        },
        "Padlock DT FIPS": {
            "max_read_write_current": {"linux": None, "macos": None, "windows": None},
            "rms_read_write_current": {"linux": None, "macos": None, "windows": None},
        },
    }

    changed = power_measurements._apply_csv_to_power(power, csv_path)

    assert changed is True
    assert power["Padlock DT"]["max_read_write_current"]["windows"] == EXPECTED_MAX_RW_CURRENT
    assert power["Padlock DT"]["rms_read_write_current"]["windows"] == EXPECTED_RMS_RW_CURRENT
    shutil.rmtree(workspace_tmp)


def test_apply_csv_to_power_updates_linux_bucket() -> None:
    workspace_tmp = Path("tests/.tmp/test_apply_csv_linux")
    if workspace_tmp.exists():
        shutil.rmtree(workspace_tmp)
    csv_path = workspace_tmp / "Z" / "69-420" / "Linux" / "Max IO" / "Secure Key 3.0.csv"
    csv_path.parent.mkdir(parents=True)
    _write_max_io_csv(csv_path)

    power: dict[str, dict[str, dict[str, float | None]]] = {
        "Padlock DT": {
            "max_read_write_current": {"linux": None, "macos": None, "windows": None},
            "rms_read_write_current": {"linux": None, "macos": None, "windows": None},
        }
    }

    changed = power_measurements._apply_csv_to_power(power, csv_path)

    assert changed is True
    assert power["Padlock DT"]["max_read_write_current"]["linux"] == EXPECTED_MAX_RW_CURRENT
    assert power["Padlock DT"]["rms_read_write_current"]["linux"] == EXPECTED_RMS_RW_CURRENT
    shutil.rmtree(workspace_tmp)


def test_update_report_power_from_csv_path_aborts_when_share_file_missing(monkeypatch: MonkeyPatch) -> None:
    workspace_tmp = Path("tests/.tmp/test_update_report_power_missing")
    if workspace_tmp.exists():
        shutil.rmtree(workspace_tmp)
    report_path = workspace_tmp / "logs" / "69-420" / "drive_qualification_report_atomic_tests.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")

    saved_payloads: list[tuple[Path, dict[str, Any]]] = []

    monkeypatch.setattr(power_measurements, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(power_measurements, "load_report", lambda path: {"power": {"Secure Key 3.0": {}}})
    monkeypatch.setattr(power_measurements, "save_report", lambda path, data: saved_payloads.append((path, data)))
    monkeypatch.setattr(power_measurements, "_wait_for_csv", lambda path, **kwargs: False)

    changed = power_measurements.update_report_power_from_csv_path("Z:/69-420/windows/Max IO/Secure Key 3.0.csv")

    assert changed is False
    assert saved_payloads == []
    shutil.rmtree(workspace_tmp)
