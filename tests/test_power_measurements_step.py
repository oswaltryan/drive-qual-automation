from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.integrations.apricorn.usb_cli import ApricornDevice
from drive_qual.platforms import power_measurements as power_measurements_dispatch
from drive_qual.platforms import power_measurements_mixed
from drive_qual.platforms.power_measurements_mixed import (
    _load_part_number_and_report,
    _run_in_rush,
    _run_max_io,
    _run_max_io_benchmark,
)


def _write_report(report_path: Path) -> None:
    report_path.write_text(
        json.dumps(
            {
                "equipment": {"dut": {"Padlock DT": {"serial_number": "ABC123"}}},
                "compatibility": {
                    "recognized_by_os": {"linux": None, "macos": None, "windows": None},
                    "hot_pluggable": {"linux": None, "macos": None, "windows": None},
                    "safely_remove": {"linux": None, "macos": None, "windows": None},
                    "copy_to_drive": {"linux": None, "macos": None, "windows": None},
                    "copy_from_drive": {"linux": None, "macos": None, "windows": None},
                    "delete_data": {"linux": None, "macos": None, "windows": None},
                    "partition_drive": {"linux": None, "macos": None, "windows": None},
                    "format_drive": {"linux": None, "macos": None, "windows": None},
                    "device_manager_disk_mgmt": {"windows": None},
                },
            }
        ),
        encoding="utf-8",
    )


def _setup_common_mocks(monkeypatch: MonkeyPatch, dut: ApricornDevice, artifact_os: str = "Windows") -> None:
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.require_fio", lambda: "fio")
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed._select_report_dut_name", lambda report_path: "Padlock DT"
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed._resolve_device_for_report_dut",
        lambda report_path, dut_name, prompt, required_fields=None: dut,
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed._refresh_device_for_report_dut",
        lambda report_path, dut_name, prompt, required_fields=None: dut,
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed._wait_for_device_removed", lambda dut, prompt: None
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.mk_dir", lambda path: None)
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.artifact_dir",
        lambda *args: f"Z:/69-420/{artifact_os}/Max IO",
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.artifact_file",
        lambda *args: f"Z:/69-420/{artifact_os}/Max IO/DUT.csv",
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.tektronix.recall_setup",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.tektronix.stop_run", lambda: None)
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.tektronix.save_measurements", lambda path: path)
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.tektronix.backup_session",
        lambda path: None,
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed._write_measurement_backup", lambda *args: None)


def test_power_measurements_dispatch_routes_to_mixed_module(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []

    class FakePowerMeasurementsMixedModule(ModuleType):
        def run_power_measurements_step(self) -> None:
            calls.append("called")

    fake_module = FakePowerMeasurementsMixedModule("drive_qual.platforms.power_measurements_mixed")
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.power_measurements_mixed", fake_module)
    importlib.reload(power_measurements_dispatch)

    power_measurements_dispatch.run_power_measurements_step()

    assert calls == ["called"]


@pytest.mark.parametrize(
    ("platform_name", "expected_artifact_os"),
    [("linux", "Linux"), ("darwin", "macOS"), ("win32", "Windows")],
)
def test_ensure_local_artifact_dir_uses_platform_os_name(
    monkeypatch: MonkeyPatch,
    platform_name: str,
    expected_artifact_os: str,
) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_artifact_dir(part_number: str, artifact_os: str, category: str) -> str:
        calls.append((part_number, artifact_os, category))
        return "Z:/69-420/mock"

    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", platform_name)
    monkeypatch.setattr(
        power_measurements_mixed,
        "artifact_dir",
        fake_artifact_dir,
    )
    monkeypatch.setattr(power_measurements_mixed, "localize_windows_path", lambda path: path)
    monkeypatch.setattr(power_measurements_mixed, "mk_dir", lambda path: None)

    power_measurements_mixed._ensure_local_artifact_dir("69-420", "Max IO")

    assert calls == [("69-420", expected_artifact_os, "Max IO")]


@pytest.mark.parametrize(("platform_name", "slot"), [("linux", "linux"), ("darwin", "macos")])
def test_run_max_io_benchmark_non_windows_uses_native_disk_ops_and_not_windows_disk_management(
    monkeypatch: MonkeyPatch, tmp_path: Path, platform_name: str, slot: str
) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    benchmark_file = tmp_path / "benchmark_file.dat"
    benchmark_file.write_text("probe", encoding="utf-8")
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123")
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", platform_name)
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.require_fio", lambda: "fio")

    prepare_calls: list[ApricornDevice] = []

    def fake_prepare_device(selected_dut: ApricornDevice) -> Any:
        prepare_calls.append(selected_dut)
        return type("Prepared", (), {"mount_point": str(tmp_path)})()

    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.native_disk_ops.prepare_device_for_benchmark",
        fake_prepare_device,
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.benchmark.benchmark_file_path",
        lambda *args: str(benchmark_file),
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed._cleanup_test_file", lambda path: True)

    def unexpected_windows_call(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Windows Disk Management helpers should not be called for non-Windows hosts.")

    monkeypatch.setattr(
        "drive_qual.platforms.windows.power_measurements.partition_and_format_drive",
        unexpected_windows_call,
    )
    monkeypatch.setattr(
        "drive_qual.platforms.windows.power_measurements.prompt_disk_management_visible", unexpected_windows_call
    )
    monkeypatch.setattr(
        "drive_qual.platforms.windows.power_measurements.run_safe_eject_script",
        unexpected_windows_call,
    )

    async def fake_run_fio(*args: Any, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.run_fio", fake_run_fio)

    asyncio.run(_run_max_io_benchmark(dut, report_path))

    assert prepare_calls == [dut]
    data = json.loads(report_path.read_text(encoding="utf-8"))
    compatibility = data["compatibility"]
    assert compatibility["partition_drive"][slot] is True
    assert compatibility["format_drive"][slot] is True
    assert compatibility["copy_to_drive"][slot] is True
    assert compatibility["copy_from_drive"][slot] is True
    assert compatibility["delete_data"][slot] is True
    assert compatibility["device_manager_disk_mgmt"]["windows"] is None


def test_run_max_io_marks_windows_compatibility_fields(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    benchmark_file = tmp_path / "benchmark_file.dat"
    benchmark_file.write_text("probe", encoding="utf-8")
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123", driveLetter="D:")
    _setup_common_mocks(monkeypatch, dut)
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", "win32")

    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.benchmark.benchmark_file_path",
        lambda *args: str(benchmark_file),
    )
    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.partition_and_format_drive", lambda dut: True)
    monkeypatch.setattr(
        "drive_qual.platforms.windows.power_measurements.prompt_disk_management_visible", lambda dut: True
    )
    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.run_safe_eject_script", lambda dut: True)

    async def fake_run_fio(target_dir: str, mode: str, file_size_mb: int, num_passes: int) -> int:
        return 0 if mode in {"write", "read"} else 1

    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.run_fio", fake_run_fio)

    asyncio.run(_run_max_io("69-420", report_path))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    compatibility = data["compatibility"]
    assert compatibility["recognized_by_os"]["windows"] is True
    assert compatibility["partition_drive"]["windows"] is True
    assert compatibility["format_drive"]["windows"] is True
    assert compatibility["device_manager_disk_mgmt"]["windows"] is True
    assert compatibility["copy_to_drive"]["windows"] is True
    assert compatibility["copy_from_drive"]["windows"] is True
    assert compatibility["delete_data"]["windows"] is True
    assert compatibility["safely_remove"]["windows"] is True


def test_run_max_io_marks_delete_data_false_when_cleanup_fails(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123", driveLetter="D:")
    _setup_common_mocks(monkeypatch, dut)
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", "win32")

    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.partition_and_format_drive", lambda dut: True)
    monkeypatch.setattr(
        "drive_qual.platforms.windows.power_measurements.prompt_disk_management_visible", lambda dut: False
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.benchmark.benchmark_file_path",
        lambda *args: str(tmp_path / "missing.dat"),
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed._cleanup_test_file", lambda path: False)
    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.run_safe_eject_script", lambda dut: True)

    async def fake_run_fio(*args: Any, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.run_fio", fake_run_fio)

    asyncio.run(_run_max_io("69-420", report_path))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    compatibility = data["compatibility"]
    assert compatibility["recognized_by_os"]["windows"] is True
    assert compatibility["partition_drive"]["windows"] is True
    assert compatibility["format_drive"]["windows"] is True
    assert compatibility["device_manager_disk_mgmt"]["windows"] is False
    assert compatibility["copy_to_drive"]["windows"] is True
    assert compatibility["copy_from_drive"]["windows"] is True
    assert compatibility["delete_data"]["windows"] is False
    assert compatibility["safely_remove"]["windows"] is True


def test_run_max_io_marks_ops_fail(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123", driveLetter="D:")
    _setup_common_mocks(monkeypatch, dut)
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", "win32")

    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.partition_and_format_drive", lambda dut: False)
    monkeypatch.setattr("drive_qual.platforms.windows.power_measurements.run_safe_eject_script", lambda dut: True)

    asyncio.run(_run_max_io("69-420", report_path))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    compatibility = data["compatibility"]
    assert compatibility["recognized_by_os"]["windows"] is True
    assert compatibility["partition_drive"]["windows"] is False
    assert compatibility["format_drive"]["windows"] is False
    assert compatibility["safely_remove"]["windows"] is True


def test_run_max_io_marks_linux_compatibility_fields(  # noqa: PLR0915
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    benchmark_file = tmp_path / "benchmark_file.dat"
    benchmark_file.write_text("probe", encoding="utf-8")
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123")
    _setup_common_mocks(monkeypatch, dut, artifact_os="Linux")
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", "linux")
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.native_disk_ops.prepare_device_for_benchmark",
        lambda dut: type("Prepared", (), {"mount_point": str(tmp_path)})(),
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.native_disk_ops.safe_remove_device", lambda dut: True
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.benchmark.benchmark_file_path",
        lambda *args: str(benchmark_file),
    )

    async def fake_run_fio(*args: Any, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.run_fio", fake_run_fio)

    asyncio.run(_run_max_io("69-420", report_path))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    compatibility = data["compatibility"]
    assert compatibility["recognized_by_os"]["linux"] is True
    assert compatibility["partition_drive"]["linux"] is True
    assert compatibility["format_drive"]["linux"] is True
    assert compatibility["copy_to_drive"]["linux"] is True
    assert compatibility["copy_from_drive"]["linux"] is True
    assert compatibility["delete_data"]["linux"] is True
    assert compatibility["safely_remove"]["linux"] is True
    assert compatibility["device_manager_disk_mgmt"]["windows"] is None
    assert compatibility["recognized_by_os"]["windows"] is None


def test_run_max_io_marks_linux_copy_actions_false_when_benchmark_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    benchmark_file = tmp_path / "missing.dat"
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123")
    _setup_common_mocks(monkeypatch, dut, artifact_os="Linux")
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", "linux")
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.native_disk_ops.prepare_device_for_benchmark",
        lambda dut: type("Prepared", (), {"mount_point": str(tmp_path)})(),
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.native_disk_ops.safe_remove_device", lambda dut: True
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.benchmark.benchmark_file_path",
        lambda *args: str(benchmark_file),
    )

    async def fake_run_fio(*args: Any, **kwargs: Any) -> int:
        return 1

    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.run_fio", fake_run_fio)

    asyncio.run(_run_max_io("69-420", report_path))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    compatibility = data["compatibility"]
    assert compatibility["partition_drive"]["linux"] is True
    assert compatibility["format_drive"]["linux"] is True
    assert compatibility["copy_to_drive"]["linux"] is False
    assert compatibility["copy_from_drive"]["linux"] is False
    assert compatibility["delete_data"]["linux"] is False
    assert compatibility["safely_remove"]["linux"] is True


def test_run_max_io_marks_macos_compatibility_fields(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    benchmark_file = tmp_path / "benchmark_file.dat"
    benchmark_file.write_text("probe", encoding="utf-8")
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123")
    _setup_common_mocks(monkeypatch, dut, artifact_os="macOS")
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", "darwin")
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.native_disk_ops.prepare_device_for_benchmark",
        lambda dut: type("Prepared", (), {"mount_point": str(tmp_path)})(),
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.native_disk_ops.safe_remove_device", lambda dut: True
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.benchmark.benchmark_file_path",
        lambda *args: str(benchmark_file),
    )

    async def fake_run_fio(*args: Any, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.benchmark.run_fio", fake_run_fio)

    asyncio.run(_run_max_io("69-420", report_path))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    compatibility = data["compatibility"]
    assert compatibility["recognized_by_os"]["macos"] is True
    assert compatibility["partition_drive"]["macos"] is True
    assert compatibility["format_drive"]["macos"] is True
    assert compatibility["copy_to_drive"]["macos"] is True
    assert compatibility["copy_from_drive"]["macos"] is True
    assert compatibility["delete_data"]["macos"] is True
    assert compatibility["safely_remove"]["macos"] is True


@pytest.mark.parametrize(
    ("platform_name", "slot", "artifact_os"),
    [("linux", "linux", "Linux"), ("darwin", "macos", "macOS"), ("win32", "windows", "Windows")],
)
def test_run_in_rush_marks_hot_pluggable(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    platform_name: str,
    slot: str,
    artifact_os: str,
) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    _write_report(report_path)

    dut = ApricornDevice(iProduct="Secure Key 3.0", iSerial="ABC123", driveLetter="D:")
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.sys.platform", platform_name)

    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed._select_report_dut_name", lambda report_path: "Padlock DT"
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed._refresh_device_for_report_dut",
        lambda report_path, dut_name, prompt, required_fields=None: dut,
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.mk_dir", lambda path: None)
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.artifact_dir",
        lambda *args: f"Z:/69-420/{artifact_os}/In Rush Current",
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.artifact_file",
        lambda *args: f"Z:/69-420/{artifact_os}/In Rush Current/Secure Key 3.0.csv",
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.tektronix.recall_setup",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.tektronix.stop_run", lambda: None)
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed.tektronix.save_measurements", lambda path: path)
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.tektronix.backup_session",
        lambda path: None,
    )
    monkeypatch.setattr("drive_qual.platforms.power_measurements_mixed._write_measurement_backup", lambda *args: None)

    asyncio.run(_run_in_rush("69-420", report_path, dut))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["compatibility"]["hot_pluggable"][slot] is True


def test_load_part_number_and_report_uses_canonical_part_number_report_path(monkeypatch: MonkeyPatch) -> None:
    source_report = Path("/tmp/legacy-folder.json")
    canonical_report = Path("/tmp/69-420.json")
    saved: list[tuple[Path, dict[str, Any]]] = []
    sessions: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.report_path_for",
        lambda folder_name: canonical_report if folder_name == "69-420" else source_report,
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.load_report",
        lambda report_path: {"drive_info": {"apricorn_part_number": "69-420"}},
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.save_report",
        lambda report_path, data: saved.append((report_path, data)),
    )
    monkeypatch.setattr(
        "drive_qual.platforms.power_measurements_mixed.set_current_session",
        lambda folder_name, product_name=None: sessions.append((folder_name, product_name)),
    )

    part_number, report_path = _load_part_number_and_report("legacy-folder")

    assert part_number == "69-420"
    assert report_path == canonical_report
    assert saved == [(canonical_report, {"drive_info": {"apricorn_part_number": "69-420"}})]
    assert sessions == [("69-420", None)]
