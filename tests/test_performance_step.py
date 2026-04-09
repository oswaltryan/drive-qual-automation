from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.integrations.apricorn.usb_cli import ApricornDevice
from drive_qual.platforms import performance as performance_dispatch
from drive_qual.platforms.linux import performance as linux_performance
from drive_qual.platforms.macos import performance as macos_performance
from drive_qual.platforms.windows import performance as windows_performance

EXPECTED_LINUX_READ = 123.4
EXPECTED_LINUX_WRITE = 234.5
EXPECTED_SUDO_AUTH_AND_RUN_CALL_COUNT = 2
EXPECTED_MACOS_READ = 345.6
EXPECTED_MACOS_WRITE = 456.7


def _report_payload() -> dict[str, Any]:
    return {
        "drive_info": {"apricorn_part_number": "69-420"},
        "equipment": {
            "windows_host": {"software": []},
            "linux_host": {"software": [{"name": "Disks (native)", "version": None}]},
            "macos_host": {"software": [{"name": "Blackmagic Disk Speed Test", "version": "4.2"}]},
            "dut": ["Padlock DT"],
        },
        "performance": {"Padlock DT": {"Windows": {}, "Linux": {}, "macOS": {}}},
    }


def test_run_software_step_dispatches_to_macos_module(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    calls: list[str | None] = []

    class FakeMacOSPerformanceModule(ModuleType):
        def run_software_step(self, *, part_number: str | None = None) -> None:
            calls.append(part_number)

    fake_module = FakeMacOSPerformanceModule("drive_qual.platforms.macos.performance")
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.macos.performance", fake_module)

    performance_dispatch.run_software_step(part_number="69-420")

    assert calls == ["69-420"]


def test_run_software_step_dispatches_to_linux_module(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    calls: list[str | None] = []

    class FakeLinuxPerformanceModule(ModuleType):
        def run_software_step(self, *, part_number: str | None = None) -> None:
            calls.append(part_number)

    fake_module = FakeLinuxPerformanceModule("drive_qual.platforms.linux.performance")
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.linux.performance", fake_module)

    performance_dispatch.run_software_step(part_number="69-420")

    assert calls == ["69-420"]


def test_run_software_step_dispatches_to_windows_module(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[str | None] = []

    class FakeWindowsPerformanceModule(ModuleType):
        def run_software_step(self, *, part_number: str | None = None) -> None:
            calls.append(part_number)

    fake_module = FakeWindowsPerformanceModule("drive_qual.platforms.windows.performance")
    monkeypatch.setitem(sys.modules, "drive_qual.platforms.windows.performance", fake_module)

    performance_dispatch.run_software_step(part_number="69-420")

    assert calls == ["69-420"]


def test_run_software_step_records_linux_disks_results(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    report_path.write_text(json.dumps(_report_payload()), encoding="utf-8")

    json_path = tmp_path / "Secure Key DT.json"
    csv_path = tmp_path / "Secure Key DT.csv"
    metrics = {
        "average_read_rate": f"{EXPECTED_LINUX_READ} MB/s",
        "average_write_rate": f"{EXPECTED_LINUX_WRITE} MB/s",
    }

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(linux_performance, "resolve_folder_name", lambda part_number=None: "69-420")
    monkeypatch.setattr(linux_performance, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(
        linux_performance,
        "_wait_for_device_present",
        lambda prompt: ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123", blockDevice="/dev/sdb"),
    )
    monkeypatch.setattr(
        linux_performance,
        "_run_linux_disks_benchmark",
        lambda dut, part_number: (metrics, json_path, csv_path),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": (_ for _ in ()).throw(AssertionError("manual input not expected for Linux Disks benchmark")),
    )

    performance_dispatch.run_software_step(part_number="69-420")

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["performance"]["Padlock DT"]["Linux"]["Disks (native)"]["read"] == EXPECTED_LINUX_READ
    assert data["performance"]["Padlock DT"]["Linux"]["Disks (native)"]["write"] == EXPECTED_LINUX_WRITE
    assert data["performance"]["Padlock DT"]["Windows"] == {}


def test_run_software_step_records_macos_blackmagic_results(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    report_path.write_text(json.dumps(_report_payload()), encoding="utf-8")

    screenshot_path = tmp_path / "Secure Key DT.png"
    json_path = tmp_path / "Secure Key DT.json"
    csv_path = tmp_path / "Secure Key DT.csv"
    responses = iter([str(EXPECTED_MACOS_READ), str(EXPECTED_MACOS_WRITE)])

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos_performance, "resolve_folder_name", lambda part_number=None: "69-420")
    monkeypatch.setattr(macos_performance, "load_part_number_and_report", lambda folder_name: ("69-420", report_path))
    monkeypatch.setattr(
        macos_performance,
        "wait_for_device_present",
        lambda prompt: ApricornDevice(iProduct="Secure Key DT"),
    )
    monkeypatch.setattr(
        macos_performance,
        "_blackmagic_artifact_paths",
        lambda part_number, dut_name: (screenshot_path, json_path, csv_path),
    )
    monkeypatch.setattr("drive_qual.platforms.macos.performance.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(macos_performance, "_run_blackmagic_automation", lambda dut_name: True)
    monkeypatch.setattr(macos_performance, "_capture_blackmagic_screenshot", lambda path: path.write_bytes(b"png"))
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    performance_dispatch.run_software_step(part_number="69-420")

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["performance"]["Padlock DT"]["macOS"]["Blackmagic Disk Speed Test"]["read"] == EXPECTED_MACOS_READ
    assert data["performance"]["Padlock DT"]["macOS"]["Blackmagic Disk Speed Test"]["write"] == EXPECTED_MACOS_WRITE

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["tool"] == "Blackmagic Disk Speed Test"
    assert payload["read_mb_s"] == EXPECTED_MACOS_READ
    assert payload["write_mb_s"] == EXPECTED_MACOS_WRITE
    assert screenshot_path.exists()

    rows = list(csv.reader(csv_path.open(encoding="utf-8", newline="")))
    assert rows == [
        ["Metric", "Value"],
        ["Read MB/s", str(EXPECTED_MACOS_READ)],
        ["Write MB/s", str(EXPECTED_MACOS_WRITE)],
    ]


def test_run_software_step_rejects_invalid_macos_blackmagic_values(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    report_path.write_text(json.dumps(_report_payload()), encoding="utf-8")

    screenshot_path = tmp_path / "Secure Key DT.png"
    json_path = tmp_path / "Secure Key DT.json"
    csv_path = tmp_path / "Secure Key DT.csv"
    responses = iter(["", "not-a-number", "0", "-1", str(EXPECTED_MACOS_READ), str(EXPECTED_MACOS_WRITE)])
    prompts: list[str] = []

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos_performance, "resolve_folder_name", lambda part_number=None: "69-420")
    monkeypatch.setattr(macos_performance, "load_part_number_and_report", lambda folder_name: ("69-420", report_path))
    monkeypatch.setattr(
        macos_performance,
        "wait_for_device_present",
        lambda prompt: ApricornDevice(iProduct="Secure Key DT"),
    )
    monkeypatch.setattr(
        macos_performance,
        "_blackmagic_artifact_paths",
        lambda part_number, dut_name: (screenshot_path, json_path, csv_path),
    )
    monkeypatch.setattr(macos_performance, "_run_blackmagic_automation", lambda dut_name: False)
    monkeypatch.setattr(macos_performance, "_launch_blackmagic_app", lambda: False)
    monkeypatch.setattr(macos_performance, "_capture_blackmagic_screenshot", lambda path: path.write_bytes(b"png"))

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    performance_dispatch.run_software_step(part_number="69-420")

    data = json.loads(report_path.read_text(encoding="utf-8"))
    entry = data["performance"]["Padlock DT"]["macOS"]["Blackmagic Disk Speed Test"]
    assert entry["read"] == EXPECTED_MACOS_READ
    assert entry["write"] == EXPECTED_MACOS_WRITE
    assert json_path.exists()
    assert csv_path.exists()
    assert "Open the app manually before continuing" in prompts[0]
    assert "completed read/write results in MB/s" in prompts[0]
    assert "Screen Recording" in prompts[0]


def test_prompt_blackmagic_ready_auto_mode_waits_without_user_input(monkeypatch: MonkeyPatch) -> None:
    sleeps: list[int] = []
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": (_ for _ in ()).throw(AssertionError("input should not be called in auto mode")),
    )
    monkeypatch.setattr("drive_qual.platforms.macos.performance.time.sleep", lambda seconds: sleeps.append(seconds))

    macos_performance._prompt_blackmagic_ready(
        "Padlock DT",
        app_launched=True,
        benchmark_ran_automatically=True,
    )

    assert sleeps == [macos_performance.BLACKMAGIC_AUTOMATION_POST_STOP_SETTLE_SECONDS]


def test_capture_blackmagic_screenshot_uses_window_bounds(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    screenshot_path = tmp_path / "window.png"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(macos_performance, "_window_bounds_for_app", lambda app_name: (10, 20, 300, 400))
    monkeypatch.setattr("drive_qual.platforms.macos.performance.subprocess.run", fake_run)

    macos_performance._capture_blackmagic_screenshot(screenshot_path)

    assert calls == [["screencapture", "-x", "-R34,44,252,352", str(screenshot_path)]]


def test_blackmagic_artifact_paths_use_macos_directory(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    created_dirs: list[Path] = []

    def fake_artifact_dir(part_number: str, os_name: str, category: str) -> str:
        calls.append((part_number, os_name, category))
        return str(tmp_path / part_number / os_name / category)

    monkeypatch.setattr(
        macos_performance,
        "artifact_dir",
        fake_artifact_dir,
    )
    monkeypatch.setattr(macos_performance, "localize_windows_path", lambda path: path)
    monkeypatch.setattr(macos_performance, "mk_dir", lambda path: created_dirs.append(path))
    monkeypatch.setattr("drive_qual.platforms.macos.performance.time.strftime", lambda _fmt: "20260408_093000")

    screenshot_path, json_path, csv_path = macos_performance._blackmagic_artifact_paths("69-420", "Padlock DT")
    expected_dir = tmp_path / "69-420" / "macOS" / "Blackmagic Disk Speed Test"

    assert calls == [("69-420", "macOS", "Blackmagic Disk Speed Test")]
    assert created_dirs == [expected_dir]
    assert screenshot_path == expected_dir / "Padlock DT_20260408_093000.png"
    assert json_path == expected_dir / "Padlock DT_20260408_093000.json"
    assert csv_path == expected_dir / "Padlock DT_20260408_093000.csv"


def test_linux_disks_artifact_paths_use_linux_directory(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    created_dirs: list[Path] = []

    def fake_artifact_dir(part_number: str, os_name: str, category: str) -> str:
        calls.append((part_number, os_name, category))
        return str(tmp_path / part_number / os_name / category)

    monkeypatch.setattr(
        linux_performance,
        "artifact_dir",
        fake_artifact_dir,
    )
    monkeypatch.setattr(linux_performance, "localize_windows_path", lambda path: path)
    monkeypatch.setattr(linux_performance, "mk_dir", lambda path: created_dirs.append(path))
    monkeypatch.setattr("drive_qual.platforms.linux.performance.time.strftime", lambda _fmt: "20260408_093000")

    json_path, csv_path = linux_performance._linux_disks_artifact_paths("69-420", "Padlock DT")
    expected_dir = tmp_path / "69-420" / "Linux" / "Disks"

    assert calls == [("69-420", "Linux", "Disks")]
    assert created_dirs == [expected_dir]
    assert json_path == expected_dir / "Padlock DT_20260408_093000.json"
    assert csv_path == expected_dir / "Padlock DT_20260408_093000.csv"


def test_capture_window_saves_png_in_windows_artifact_dir(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    created_dirs: list[Path] = []
    grab_calls: list[tuple[tuple[int, int, int, int], bool]] = []
    saved_paths: list[str] = []

    class FakeImage:
        def save(self, path: str) -> None:
            saved_paths.append(path)

    def fake_grab(*, bbox: tuple[int, int, int, int], all_screens: bool) -> FakeImage:
        grab_calls.append((bbox, all_screens))
        return FakeImage()

    fake_image_grab_module = ModuleType("PIL.ImageGrab")
    fake_image_grab_module.grab = fake_grab  # type: ignore[attr-defined]
    fake_pil_module = ModuleType("PIL")
    fake_pil_module.ImageGrab = fake_image_grab_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PIL", fake_pil_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", fake_image_grab_module)

    monkeypatch.setattr(
        windows_performance,
        "artifact_dir",
        lambda part_number, os_name, tool_name: str(Path(f"Z:/{part_number}/{os_name}/{tool_name}")),
    )
    monkeypatch.setattr(
        windows_performance,
        "localize_windows_path",
        lambda path: tmp_path / "69-420" / "Windows" / path.name,
    )
    monkeypatch.setattr(windows_performance, "mk_dir", lambda path: created_dirs.append(path))
    monkeypatch.setattr(windows_performance, "_get_tight_rect", lambda _hwnd: (10, 20, 300, 400))
    monkeypatch.setattr("drive_qual.platforms.windows.performance.time.strftime", lambda _fmt: "20260408_093000")

    main_window = type("FakeWindow", (), {"handle": 1234})()
    windows_performance._capture_window(main_window, "69-420", "Padlock DT", "ATTO")

    expected_dir = tmp_path / "69-420" / "Windows" / "ATTO"
    expected_png = expected_dir / "Padlock DT_20260408_093000.png"

    assert created_dirs == [expected_dir]
    assert grab_calls == [((10, 20, 300, 400), True)]
    assert saved_paths == [str(expected_png)]


def test_windows_performance_syncs_report_without_running_automation(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    payload = _report_payload()
    payload["equipment"]["windows_host"]["software"] = [
        {"name": "CrystalDiskInfo", "version": "9.4"},
        {"name": "CrystalDiskMark", "version": "8.0"},
        {"name": "ATTO", "version": "4.1"},
    ]
    payload["performance"] = {}
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(windows_performance, "resolve_folder_name", lambda part_number=None: "69-420")
    monkeypatch.setattr(windows_performance, "load_part_number_and_report", lambda folder_name: ("69-420", report_path))
    monkeypatch.setattr(windows_performance, "_get_software_flags", lambda equipment: (False, False, False))
    no_wait_error = "device wait should not run when no automation is enabled"
    monkeypatch.setattr(
        windows_performance,
        "wait_for_device_present",
        lambda prompt: (_ for _ in ()).throw(AssertionError(no_wait_error)),
    )

    performance_dispatch.run_software_step(part_number="69-420")

    data = json.loads(report_path.read_text(encoding="utf-8"))
    dut_perf = data["performance"]["Padlock DT"]
    assert dut_perf["Windows"]["CrystalDiskInfo"] == {"screenshot": None}
    assert dut_perf["Windows"]["CrystalDiskMark"] == {"read": None, "write": None}
    assert dut_perf["Windows"]["ATTO"] == {"read": None, "write": None}
    assert dut_perf["Linux"]["Disks (native)"] == {"read": None, "write": None}
    assert dut_perf["macOS"]["Blackmagic Disk Speed Test"] == {"read": None, "write": None}


def test_write_linux_disks_csv_writes_metric_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "benchmark.csv"

    linux_performance._write_linux_disks_csv(
        csv_path,
        {
            "minimum_read_rate": "111.1 MB/s",
            "average_read_rate": "123.4 MB/s",
            "maximum_read_rate": "130.0 MB/s",
            "minimum_write_rate": "210.0 MB/s",
            "average_write_rate": "234.5 MB/s",
            "maximum_write_rate": "240.0 MB/s",
            "average_access_time": "0.12 ms",
            "last_benchmark": "just now",
        },
    )

    rows = list(csv.reader(csv_path.open(encoding="utf-8", newline="")))
    assert rows[0] == ["Metric", "Value"]
    assert ["Average Read Rate", "123.4 MB/s"] in rows
    assert ["Average Write Rate", "234.5 MB/s"] in rows
    assert ["Average Access Time", "0.12 ms"] in rows


def test_linux_disks_metrics_from_payload_maps_gui_average_values() -> None:
    payload = {
        "timestamp_usec": 123456789,
        "gui_average": {"read_MB_s": 321.5, "write_MB_s": 210.25, "access_msec": 0.42},
        "summary": {
            "read_mib_per_sec": {"min": 100.0, "avg": 200.0, "max": 300.0},
            "write_mib_per_sec": {"min": 50.0, "avg": 60.0, "max": 70.0},
        },
    }

    metrics = linux_performance._linux_disks_metrics_from_payload(payload)

    assert metrics["average_read_rate"] == "321.50 MB/s"
    assert metrics["average_write_rate"] == "210.25 MB/s"
    assert metrics["average_access_time"] == "0.42 ms"
    assert metrics["minimum_read_rate"].endswith(" MB/s")
    assert metrics["maximum_write_rate"].endswith(" MB/s")
    assert metrics["last_benchmark"] == "123456789"


def test_run_linux_disks_benchmark_invokes_wrapper_script(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    json_path = tmp_path / "result.json"
    csv_path = tmp_path / "result.csv"
    wrapper_path = tmp_path / "disks-benchmark-like.py"
    wrapper_path.write_text("#!/bin/sh\n", encoding="utf-8")

    json_path.write_text(
        json.dumps(
            {
                "timestamp_usec": 1,
                "gui_average": {"read_MB_s": 100.0, "write_MB_s": 200.0, "access_msec": 0.1},
                "summary": {},
            }
        ),
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        linux_performance,
        "_linux_disks_artifact_paths",
        lambda part_number, dut_name: (json_path, csv_path),
    )
    monkeypatch.setattr(linux_performance, "_linux_disks_wrapper_script_path", lambda: wrapper_path)
    monkeypatch.setattr("drive_qual.platforms.linux.performance.subprocess.run", fake_run)
    monkeypatch.setattr("drive_qual.platforms.linux.performance.os.geteuid", lambda: 1000)

    metrics, returned_json_path, returned_csv_path = linux_performance._run_linux_disks_benchmark(
        ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123", blockDevice="/dev/sdb"),
        "69-420",
    )

    assert calls
    assert len(calls) == EXPECTED_SUDO_AUTH_AND_RUN_CALL_COUNT
    assert calls[0] == ["sudo", "-v"]
    assert calls[1][0] == "sudo"
    assert calls[1][1] == "-n"
    assert calls[1][2] == sys.executable
    assert calls[1][3] == str(wrapper_path)
    assert "--device" in calls[1]
    assert "--json-out" in calls[1]
    assert returned_json_path == json_path
    assert returned_csv_path == csv_path
    assert metrics["average_read_rate"] == "100.00 MB/s"
    assert metrics["average_write_rate"] == "200.00 MB/s"
    assert csv_path.exists()


def test_run_linux_disks_benchmark_requires_sudo_authentication(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    json_path = tmp_path / "result.json"
    csv_path = tmp_path / "result.csv"
    wrapper_path = tmp_path / "disks-benchmark-like.py"
    wrapper_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        calls.append(command)
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "sudo auth failed"})()

    monkeypatch.setattr(
        linux_performance,
        "_linux_disks_artifact_paths",
        lambda part_number, dut_name: (json_path, csv_path),
    )
    monkeypatch.setattr(linux_performance, "_linux_disks_wrapper_script_path", lambda: wrapper_path)
    monkeypatch.setattr("drive_qual.platforms.linux.performance.subprocess.run", fake_run)
    monkeypatch.setattr("drive_qual.platforms.linux.performance.os.geteuid", lambda: 1000)

    with pytest.raises(RuntimeError, match="requires sudo authentication"):
        linux_performance._run_linux_disks_benchmark(
            ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123", blockDevice="/dev/sdb"),
            "69-420",
        )

    assert calls
    assert calls[0] == ["sudo", "-v"]
