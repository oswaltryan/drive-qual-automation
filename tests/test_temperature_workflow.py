from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core.temperature import (
    load_temperature_performance_csv,
    plot_temperature_chart,
    update_temperature_performance,
)

EXPECTED_GENERATED_CHART_ROWS = 2


def test_temperature_csv_rows_update_report_contract(tmp_path: Path) -> None:
    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text(
        "\n".join(
            [
                "TempRoundedC,Operation,SpeedMiB",
                "-40,read,107.59",
                "-40,write,109.31",
                "20,read,0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    data: dict[str, Any] = {"temperature": {"Padlock DT": {"performance": {}}}}

    rows = load_temperature_performance_csv(csv_path)
    update_temperature_performance(data, "Padlock DT", rows)

    assert data["temperature"]["Padlock DT"]["performance"]["-40c"] == {
        "read_mb_s": 107.59,
        "write_mb_s": 109.31,
    }
    assert data["temperature"]["Padlock DT"]["performance"]["20c"]["read_mb_s"] == 0.0


def test_sectioned_temperature_csv_rows_update_report_contract(tmp_path: Path) -> None:
    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text(
        "\n".join(
            [
                "READ - Constant drive activity of the full range",
                "Temp C,Seagate 8TB HDD",
                "-10 C,185.4",
                "0 C,186.4",
                "",
                "WRITE - Constant drive activity of the full range",
                "Temp C,Seagate 8TB HDD",
                "-10 C,187.2",
                "0 C,187.5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    data: dict[str, Any] = {"temperature": {"Padlock DT": {"performance": {}}}}

    rows = load_temperature_performance_csv(csv_path)
    update_temperature_performance(data, "Padlock DT", rows)

    assert data["temperature"]["Padlock DT"]["performance"]["-10c"] == {
        "read_mb_s": 185.4,
        "write_mb_s": 187.2,
    }
    assert data["temperature"]["Padlock DT"]["performance"]["0c"] == {
        "read_mb_s": 186.4,
        "write_mb_s": 187.5,
    }


def test_post_process_temperature_data_saves_report_and_chart(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    report_path = tmp_path / "69-420" / "drive_qualification_report_atomic_tests.json"
    report_path.parent.mkdir(parents=True)
    source_csv = tmp_path / "matched.csv"
    source_csv.write_text("TemperatureC,Operation,SpeedMiB\n30,read,250.5\n30,write,240.25\n", encoding="utf-8")
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    saved: dict[str, object] = {}

    monkeypatch.setattr(temperature, "resolve_folder_name", lambda part_number: part_number or "69-420")
    monkeypatch.setattr(temperature, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(
        temperature,
        "load_report",
        lambda _path: {
            "drive_info": {"apricorn_part_number": "69-420"},
            "equipment": {"dut": {"Padlock DT": {"serial_number": "ABC123"}}},
            "temperature": {"Padlock DT": {"performance": {}}},
        },
    )
    monkeypatch.setattr(
        temperature,
        "save_report",
        lambda path, data: saved.update({"path": path, "data": json.loads(json.dumps(data))}),
    )
    monkeypatch.setattr(
        temperature,
        "copy_temperature_chart",
        lambda source, *, part_number, dut_name: saved.update(
            {"chart_source": source, "chart_part": part_number, "chart_dut": dut_name}
        )
        or tmp_path / "copied.png",
    )

    temperature.post_process_temperature_data(
        part_number="69-420",
        dut_name="Padlock DT",
        performance_csv=source_csv,
        chart=chart,
    )

    assert saved["path"] == report_path
    data = saved["data"]
    assert isinstance(data, dict)
    assert data["temperature"]["Padlock DT"]["performance"]["30c"] == {
        "read_mb_s": 250.5,
        "write_mb_s": 240.25,
    }
    assert saved["chart_source"] == chart
    assert saved["chart_part"] == "69-420"
    assert saved["chart_dut"] == "Padlock DT"


def test_temperature_chart_is_generated_from_csv_rows(tmp_path: Path) -> None:
    rows = load_temperature_performance_csv(
        _write_temperature_csv(
            tmp_path,
            [
                "TempRoundedC,Operation,SpeedMiB",
                "-40,read,107.59",
                "-40,write,109.31",
                "20,read,250.5",
                "20,write,240.25",
            ],
        )
    )
    out_path = tmp_path / "chart.png"

    generated = plot_temperature_chart(rows, out_path)

    assert generated == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_post_process_temperature_data_generates_chart_from_csv(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    report_path = tmp_path / "69-420" / "drive_qualification_report_atomic_tests.json"
    source_csv = _write_temperature_csv(
        tmp_path,
        [
            "TemperatureC,Operation,SpeedMiB",
            "30,read,250.5",
            "30,write,240.25",
        ],
    )
    generated_chart = tmp_path / "generated.png"
    saved: dict[str, object] = {}

    monkeypatch.setattr(temperature, "resolve_folder_name", lambda part_number: part_number or "69-420")
    monkeypatch.setattr(temperature, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(
        temperature,
        "load_report",
        lambda _path: {
            "drive_info": {"apricorn_part_number": "69-420"},
            "equipment": {"dut": {"Padlock DT": {"serial_number": "ABC123"}}},
            "temperature": {"Padlock DT": {"performance": {}}},
        },
    )
    monkeypatch.setattr(
        temperature,
        "save_report",
        lambda path, data: saved.update({"path": path, "data": json.loads(json.dumps(data))}),
    )
    monkeypatch.setattr(
        temperature,
        "temperature_chart_path",
        lambda part_number, dut_name: generated_chart,
    )
    monkeypatch.setattr(
        temperature,
        "plot_temperature_chart",
        lambda rows, out_path, *, title: saved.update(
            {"chart_rows": list(rows), "chart_path": out_path, "chart_title": title}
        )
        or out_path,
    )

    temperature.post_process_temperature_data(
        part_number="69-420",
        dut_name="Padlock DT",
        performance_csv=source_csv,
        chart_title="Padlock DT Temperature vs Speed",
    )

    assert saved["chart_path"] == generated_chart
    assert saved["chart_title"] == "Padlock DT Temperature vs Speed"
    chart_rows = saved["chart_rows"]
    assert isinstance(chart_rows, list)
    assert len(chart_rows) == EXPECTED_GENERATED_CHART_ROWS


def test_temperature_resolve_drive_target_uses_bound_apricorn_drive_letter(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.workflows import temperature

    monkeypatch.setattr(temperature, "resolve_report_dut_name", lambda report_path: "Padlock DT")
    monkeypatch.setattr(
        temperature,
        "resolve_or_bind_dut_device",
        lambda *args, **kwargs: SimpleNamespace(driveLetter="d:\\"),
    )

    assert temperature._resolve_drive_target(Path("report.json")) == "D:"


def test_temperature_resolve_drive_target_falls_back_when_usb_toolkit_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    from drive_qual.workflows import temperature

    monkeypatch.setattr(temperature, "resolve_report_dut_name", lambda report_path: "Padlock DT")

    def fail_resolve(*args: object, **kwargs: object) -> object:
        raise RuntimeError("Unable to read Apricorn USB inventory from `usb --json`.")

    monkeypatch.setattr(temperature, "resolve_or_bind_dut_device", fail_resolve)

    with pytest.raises(RuntimeError, match="Unable to read Apricorn USB inventory"):
        temperature._resolve_drive_target(Path("report.json"))


def test_temperature_resolve_drive_target_formats_when_drive_letter_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    from drive_qual.integrations.apricorn.usb_cli import ApricornDevice
    from drive_qual.platforms.windows import power_measurements
    from drive_qual.workflows import temperature

    initial = ApricornDevice(iProduct="Padlock DT", iSerial="ABC123", physicalDriveNum=2)
    refreshed = ApricornDevice(iProduct="Padlock DT", iSerial="ABC123", physicalDriveNum=2, driveLetter="E:")
    formatted: list[ApricornDevice] = []

    monkeypatch.setattr(temperature.sys, "platform", "win32")
    monkeypatch.setattr(temperature, "resolve_report_dut_name", lambda report_path: "Padlock DT")
    monkeypatch.setattr(temperature, "resolve_or_bind_dut_device", lambda *args, **kwargs: initial)
    monkeypatch.setattr(temperature, "refresh_dut_device", lambda *args, **kwargs: refreshed)
    monkeypatch.setattr(power_measurements, "partition_and_format_drive", lambda dut: formatted.append(dut) or True)

    assert temperature._resolve_drive_target(Path("report.json")) == "E:"
    assert formatted == [initial]


def test_temperature_snapshot_phase_stops_when_setpoint_is_reached() -> None:
    from drive_qual.workflows import temperature

    class FakeController:
        snapshots = [
            SimpleNamespace(
                timestamp="2026-06-18T12:00:00-07:00",
                setpoint_c=30.0,
                temperature_c=27.5,
                temperature_f=81.5,
            ),
            SimpleNamespace(
                timestamp="2026-06-18T12:00:02-07:00",
                setpoint_c=30.0,
                temperature_c=29.95,
                temperature_f=85.91,
            ),
        ]

        def write_setpoint_c(self, setpoint_c: float) -> None:
            self.setpoint_c = setpoint_c

        def read_snapshot(self) -> object:
            return self.snapshots.pop(0)

    class FakeDiskTester:
        returncode = None

        def poll(self) -> None:
            return None

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=temperature.SNAPSHOT_CSV_FIELDS)
    writer.writeheader()

    temperature._run_snapshot_phase(
        controller=FakeController(),
        writer=writer,
        csv_handle=output,
        disk_tester=FakeDiskTester(),
        setpoint_c=30.0,
    )

    assert output.getvalue().splitlines()[0] == "timestamp,temperature_c,temperature_f"
    rows = list(csv.DictReader(StringIO(output.getvalue())))
    assert [row["temperature_c"] for row in rows] == ["27.500", "29.950"]


def test_temperature_snapshot_phase_prints_each_snapshot(capsys: pytest.CaptureFixture[str]) -> None:
    from drive_qual.workflows import temperature

    class FakeController:
        def write_setpoint_c(self, setpoint_c: float) -> None:
            self.setpoint_c = setpoint_c

        def read_snapshot(self) -> object:
            return SimpleNamespace(
                timestamp="2026-06-18T12:00:00-07:00",
                setpoint_c=30.0,
                temperature_c=30.0,
                temperature_f=86.0,
            )

    class FakeDiskTester:
        returncode = None

        def poll(self) -> None:
            return None

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=temperature.SNAPSHOT_CSV_FIELDS)
    writer.writeheader()

    temperature._run_snapshot_phase(
        controller=FakeController(),
        writer=writer,
        csv_handle=output,
        disk_tester=FakeDiskTester(),
        setpoint_c=30.0,
    )

    assert "Temperature snapshot: 2026-06-18T12:00:00-07:00, 30.000 C, 86.000 F" in capsys.readouterr().out


def test_temperature_performance_csv_is_derived_from_snapshots_and_disk_log(tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    snapshots = tmp_path / "temperature_snapshots.csv"
    snapshots.write_text(
        "\n".join(
            [
                "timestamp,temperature_c,temperature_f",
                "2026-06-18T12:00:00-07:00,20.0,68.0",
                "2026-06-18T12:00:05-07:00,21.0,69.8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    disk_log = tmp_path / "disk_tester_temperature.log"
    disk_log.write_text(
        "\n".join(
            [
                "[2026-06-18 12:00:04] SEQUENTIAL write: 109.31 MiB/s, 120 IOPS",
                "[2026-06-18 12:00:06] SEQUENTIAL read: 107.59 MiB/s, 118 IOPS",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "temperature_performance.csv"

    temperature._write_temperature_performance_csv(
        snapshots_csv=snapshots,
        disk_tester_log=disk_log,
        output_csv=output,
    )

    rows = list(csv.DictReader(StringIO(output.read_text(encoding="utf-8"))))
    assert rows == [
        {"TemperatureC": "21.000", "Operation": "write", "SpeedMiB": "109.31"},
        {"TemperatureC": "21.000", "Operation": "read", "SpeedMiB": "107.59"},
    ]


def test_temperature_chamber_returns_to_ambient_without_csv_logging(
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from drive_qual.workflows import temperature

    class FakeController:
        def __init__(self) -> None:
            self.setpoints: list[float] = []
            self.snapshots = [
                SimpleNamespace(
                    timestamp="2026-06-18T12:01:00-07:00",
                    temperature_c=26.0,
                    temperature_f=78.8,
                ),
                SimpleNamespace(
                    timestamp="2026-06-18T12:01:05-07:00",
                    temperature_c=25.05,
                    temperature_f=77.09,
                ),
            ]

        def write_setpoint_c(self, setpoint_c: float) -> None:
            self.setpoints.append(setpoint_c)

        def read_snapshot(self) -> object:
            return self.snapshots.pop(0)

    controller = FakeController()
    sleep_calls: list[float] = []
    monkeypatch.setattr(temperature.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    temperature._return_chamber_to_ambient(controller)

    assert controller.setpoints == [25.0]
    assert sleep_calls == [temperature.SNAPSHOT_INTERVAL_SECONDS]
    assert "Chamber reached ambient within" in capsys.readouterr().out


def test_temperature_finalize_generates_chart_from_collected_logs(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    snapshots = tmp_path / "temperature_snapshots.csv"
    snapshots.write_text(
        "timestamp,temperature_c,temperature_f\n2026-06-18T12:00:00-07:00,20.0,68.0\n",
        encoding="utf-8",
    )
    disk_log = tmp_path / "disk_tester_temperature.log"
    disk_log.write_text("[2026-06-18 12:00:00] SEQUENTIAL read: 107.59 MiB/s, 118 IOPS\n", encoding="utf-8")
    artifacts = temperature.TemperatureRunArtifacts(
        snapshot_csv=snapshots,
        performance_csv=tmp_path / "temperature_performance.csv",
        disk_tester_log=disk_log,
        disk_tester_stdout=tmp_path / "stdout.log",
        disk_tester_stderr=tmp_path / "stderr.log",
    )
    calls: list[dict[str, object]] = []

    def fake_post_process_temperature_data(**kwargs: object) -> Path:
        calls.append(kwargs)
        return tmp_path / "report.json"

    monkeypatch.setattr(temperature, "post_process_temperature_data", fake_post_process_temperature_data)

    temperature._finalize_temperature_results(folder_name="69-420", dut_name="Padlock DT", artifacts=artifacts)

    assert calls == [
        {
            "part_number": "69-420",
            "dut_name": "Padlock DT",
            "performance_csv": artifacts.performance_csv,
        }
    ]


def test_temperature_disk_tester_command_uses_temp_subcommand_and_log_path(tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    log_path = tmp_path / "disk_tester_temperature.log"

    command = temperature._disk_tester_command("D:", log_path)

    assert command[1:5] == ["-m", "drive_qual.benchmarks.disk_tester", "temp", "--path"]
    assert command[5:] == ["D:", "--interval", "60", "--log", str(log_path)]


def _write_temperature_csv(tmp_path: Path, lines: list[str]) -> Path:
    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path
