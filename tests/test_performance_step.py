from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.integrations.apricorn.usb_cli import ApricornDevice
from drive_qual.platforms import performance as performance_dispatch
from drive_qual.platforms.linux import performance as linux_performance

EXPECTED_LINUX_READ = 123.4
EXPECTED_LINUX_WRITE = 234.5
EXPECTED_SUDO_AUTH_AND_RUN_CALL_COUNT = 2


def _report_payload() -> dict[str, Any]:
    return {
        "drive_info": {"apricorn_part_number": "69-420"},
        "equipment": {
            "windows_host": {"software": []},
            "linux_host": {"software": [{"name": "Disks (native)", "version": None}]},
            "macos_host": {"software": []},
            "dut": ["Padlock DT"],
        },
        "performance": {"Padlock DT": {"Windows": {}, "Linux": {}, "macOS": {}}},
    }


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
