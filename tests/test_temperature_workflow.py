from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

EXPECTED_PROFILE_READ_MB_S = 107.59


def test_temperature_csv_rows_update_report_contract(tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text(
        "\n".join(
            [
                "TempRounded,Operation,SpeedMiB,Mode",
                "-40,read,107.59,SEQUENTIAL",
                "-40,write,109.31,SEQUENTIAL",
                "20,read,0,RANDOM",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    data: dict[str, Any] = {
        "temperature": {
            "Padlock DT": {
                "performance": {
                    "-40c": {"read_mb_s": None, "write_mb_s": None},
                    "20c": {"read_mb_s": None, "write_mb_s": None},
                }
            }
        }
    }

    temperature._update_temperature_report_from_profile(data, "Padlock DT", csv_path)

    assert data["temperature"]["Padlock DT"]["performance"]["-40c"] == {
        "read_mb_s": 107.59,
        "write_mb_s": 109.31,
    }
    assert data["temperature"]["Padlock DT"]["performance"]["20c"] == {
        "read_mb_s": None,
        "write_mb_s": None,
    }


def test_temperature_profile_rows_ignore_random_mode_for_report_contract(tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text(
        "\n".join(
            [
                "TempRounded,Operation,SpeedMiB,Mode",
                "-10,read,185.4,SEQUENTIAL",
                "-10,write,187.2,SEQUENTIAL",
                "-10,read,999.0,RANDOM",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    data: dict[str, Any] = {
        "temperature": {"Padlock DT": {"performance": {"-10c": {"read_mb_s": None, "write_mb_s": None}}}}
    }

    temperature._update_temperature_report_from_profile(data, "Padlock DT", csv_path)

    assert data["temperature"]["Padlock DT"]["performance"]["-10c"] == {
        "read_mb_s": 185.4,
        "write_mb_s": 187.2,
    }


def test_temperature_profile_rows_do_not_add_report_contract_keys(tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text(
        "TempRounded,Operation,SpeedMiB,Mode\n21,read,107.59,SEQUENTIAL\n",
        encoding="utf-8",
    )
    data: dict[str, Any] = {
        "temperature": {"Padlock DT": {"performance": {"20c": {"read_mb_s": None, "write_mb_s": None}}}}
    }

    temperature._update_temperature_report_from_profile(data, "Padlock DT", csv_path)

    assert data["temperature"]["Padlock DT"]["performance"] == {"20c": {"read_mb_s": None, "write_mb_s": None}}


def test_temperature_profile_uses_requested_temperature_for_report_contract(tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text(
        "RequestedTemp,TempRounded,Operation,SpeedMiB,Mode\n30,29,read,107.59,SEQUENTIAL\n",
        encoding="utf-8",
    )
    data: dict[str, Any] = {
        "temperature": {
            "Padlock DT": {
                "performance": {
                    "29c": {"read_mb_s": None, "write_mb_s": None},
                    "30c": {"read_mb_s": None, "write_mb_s": None},
                }
            }
        }
    }

    temperature._update_temperature_report_from_profile(data, "Padlock DT", csv_path)

    assert data["temperature"]["Padlock DT"]["performance"]["29c"]["read_mb_s"] is None
    assert data["temperature"]["Padlock DT"]["performance"]["30c"]["read_mb_s"] == EXPECTED_PROFILE_READ_MB_S


def test_temperature_template_matches_supported_report_points() -> None:
    from drive_qual.workflows import equipment

    assert list(equipment._temperature_template()["performance"]) == [
        "-40c",
        "-35c",
        "-30c",
        "-20c",
        "-10c",
        "0c",
        "10c",
        "20c",
        "30c",
        "40c",
        "50c",
        "60c",
        "70c",
    ]


def test_temperature_contract_removes_legacy_80c_and_preserves_values() -> None:
    from drive_qual.workflows import equipment

    data: dict[str, Any] = {
        "equipment": {},
        "temperature": {
            "Padlock DT": {
                "performance": {
                    "-40c": {"read_mb_s": EXPECTED_PROFILE_READ_MB_S, "write_mb_s": None},
                    "80c": {"read_mb_s": 1.0, "write_mb_s": 2.0},
                }
            }
        },
    }

    equipment._ensure_dut_sections(data, ["Padlock DT"])

    performance = data["temperature"]["Padlock DT"]["performance"]
    assert "80c" not in performance
    assert performance["-40c"]["read_mb_s"] == EXPECTED_PROFILE_READ_MB_S
    assert "70c" in performance


def test_post_process_temperature_data_saves_report_and_chart(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    report_path = tmp_path / "69-420" / "drive_qualification_report_atomic_tests.json"
    report_path.parent.mkdir(parents=True)
    source_csv = tmp_path / "matched.csv"
    source_csv.write_text(
        "TempRounded,Operation,SpeedMiB,Mode\n30,read,250.5,SEQUENTIAL\n30,write,240.25,SEQUENTIAL\n",
        encoding="utf-8",
    )
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    copied_chart = tmp_path / "copied.png"
    saved: dict[str, object] = {}

    monkeypatch.setattr(temperature, "resolve_folder_name", lambda part_number: part_number or "69-420")
    monkeypatch.setattr(temperature, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(
        temperature,
        "load_report",
        lambda _path: {
            "drive_info": {"apricorn_part_number": "69-420"},
            "equipment": {"dut": {"Padlock DT": {"serial_number": "ABC123"}}},
            "temperature": {"Padlock DT": {"performance": {"30c": {"read_mb_s": None, "write_mb_s": None}}}},
        },
    )
    monkeypatch.setattr(
        temperature,
        "save_report",
        lambda path, data: saved.update({"path": path, "data": json.loads(json.dumps(data))}),
    )
    monkeypatch.setattr(temperature, "_temperature_chart_path", lambda part_number, dut_name: copied_chart)

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
    assert copied_chart.read_bytes() == b"png"


def test_temperature_chart_is_generated_from_profile_csv(tmp_path: Path) -> None:
    from drive_qual.core import temperature as temperature_plotter

    profile_csv = _write_temperature_csv(
        tmp_path,
        [
            "TempRounded,Operation,SpeedMiB,Mode",
            "-40,read,107.59,SEQUENTIAL",
            "-40,write,109.31,SEQUENTIAL",
            "20,read,250.5,RANDOM",
            "20,write,240.25,RANDOM",
        ],
    )
    out_path = tmp_path / "chart.png"

    generated = temperature_plotter.plot_profile_csv(profile_csv, out_path)

    assert generated == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_post_process_temperature_data_generates_chart_from_csv(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    report_path = tmp_path / "69-420" / "drive_qualification_report_atomic_tests.json"
    source_csv = _write_temperature_csv(
        tmp_path,
        [
            "TempRounded,Operation,SpeedMiB,Mode",
            "30,read,250.5,SEQUENTIAL",
            "30,write,240.25,SEQUENTIAL",
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
            "temperature": {"Padlock DT": {"performance": {"30c": {"read_mb_s": None, "write_mb_s": None}}}},
        },
    )
    monkeypatch.setattr(
        temperature,
        "save_report",
        lambda path, data: saved.update({"path": path, "data": json.loads(json.dumps(data))}),
    )
    monkeypatch.setattr(
        temperature,
        "_temperature_chart_path",
        lambda part_number, dut_name: generated_chart,
    )
    monkeypatch.setattr(
        temperature.temperature_plotter,
        "plot_profile_csv",
        lambda profile_csv, out_path, *, title: saved.update(
            {"profile_csv": profile_csv, "chart_path": out_path, "chart_title": title}
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
    assert saved["profile_csv"] == source_csv


def test_temperature_resolve_drive_target_uses_bound_apricorn_drive_letter(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.workflows import temperature

    monkeypatch.setattr(temperature, "resolve_report_dut_name", lambda report_path: "Padlock DT")
    monkeypatch.setattr(
        temperature,
        "_resolve_temperature_device_by_product",
        lambda *args, **kwargs: SimpleNamespace(driveLetter="d:\\"),
    )

    assert temperature._resolve_drive_target(Path("report.json")) == "D:"


def test_temperature_resolve_drive_target_ignores_contract_serial_when_product_matches(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    from drive_qual.workflows import temperature

    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps({"equipment": {"dut": {"Padlock DT": {"serial_number": "OLD-SERIAL"}}}}),
        encoding="utf-8",
    )
    payload = {
        "devices": [
            {
                "usb0": {
                    "bcdUSB": 3.2,
                    "iManufacturer": "Apricorn",
                    "iProduct": "Padlock DT",
                    "iSerial": "CURRENT-SERIAL",
                    "physicalDriveNum": 2,
                    "driveLetter": "E:",
                }
            }
        ]
    }
    saved: list[dict[str, Any]] = []

    monkeypatch.setattr(temperature, "resolve_report_dut_name", lambda _report_path: "Padlock DT")
    monkeypatch.setattr(temperature, "get_usb_payload", lambda: payload)
    monkeypatch.setattr(temperature, "save_report", lambda _path, data: saved.append(data))

    assert temperature._resolve_drive_target(report_path) == "E:"
    assert saved == []


def test_temperature_resolve_drive_target_falls_back_when_usb_toolkit_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    from drive_qual.workflows import temperature

    monkeypatch.setattr(temperature, "resolve_report_dut_name", lambda report_path: "Padlock DT")

    def fail_resolve(*args: object, **kwargs: object) -> object:
        raise RuntimeError("Unable to read Apricorn USB inventory from `usb --json`.")

    monkeypatch.setattr(temperature, "_resolve_temperature_device_by_product", fail_resolve)

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
    devices = iter([initial, refreshed])
    monkeypatch.setattr(temperature, "_resolve_temperature_device_by_product", lambda *args, **kwargs: next(devices))

    def fake_partition_and_format_drive(dut: ApricornDevice) -> bool:
        formatted.append(dut)
        return True

    monkeypatch.setattr(power_measurements, "partition_and_format_drive", fake_partition_and_format_drive)

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
            SimpleNamespace(
                timestamp="2026-06-18T12:01:02-07:00",
                setpoint_c=30.0,
                temperature_c=30.0,
                temperature_f=86.0,
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
    monotonic_values = iter([0.0, 0.0, temperature.SETPOINT_SOAK_SECONDS])
    sleeps: list[float] = []
    original_monotonic = temperature.time.monotonic
    original_sleep = temperature.time.sleep
    temperature.time.monotonic = lambda: next(monotonic_values)
    temperature.time.sleep = lambda seconds: sleeps.append(seconds)

    try:
        temperature._run_snapshot_phase(
            controller=FakeController(),
            writer=writer,
            csv_handle=output,
            disk_tester=FakeDiskTester(),
            setpoint_c=30.0,
        )
    finally:
        temperature.time.monotonic = original_monotonic
        temperature.time.sleep = original_sleep

    assert output.getvalue().splitlines()[0] == "timestamp,temperature_c,temperature_f"
    rows = list(csv.DictReader(StringIO(output.getvalue())))
    assert [row["temperature_c"] for row in rows] == ["27.500", "29.950", "30.000"]
    assert sleeps == [temperature.SNAPSHOT_INTERVAL_SECONDS, temperature.SNAPSHOT_INTERVAL_SECONDS]


def test_temperature_snapshot_phase_prints_each_snapshot(capsys: pytest.CaptureFixture[str]) -> None:
    from drive_qual.workflows import temperature

    class FakeController:
        snapshots = [
            SimpleNamespace(
                timestamp="2026-06-18T12:00:00-07:00",
                setpoint_c=30.0,
                temperature_c=30.0,
                temperature_f=86.0,
            ),
            SimpleNamespace(
                timestamp="2026-06-18T12:01:00-07:00",
                setpoint_c=30.0,
                temperature_c=30.0,
                temperature_f=86.0,
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
    monotonic_values = iter([0.0, temperature.SETPOINT_SOAK_SECONDS])
    original_monotonic = temperature.time.monotonic
    original_sleep = temperature.time.sleep
    temperature.time.monotonic = lambda: next(monotonic_values)
    temperature.time.sleep = lambda _seconds: None

    try:
        temperature._run_snapshot_phase(
            controller=FakeController(),
            writer=writer,
            csv_handle=output,
            disk_tester=FakeDiskTester(),
            setpoint_c=30.0,
        )
    finally:
        temperature.time.monotonic = original_monotonic
        temperature.time.sleep = original_sleep

    assert "Temperature snapshot: 2026-06-18T12:00:00-07:00, 30.000 C, 86.000 F" in capsys.readouterr().out


def test_temperature_snapshot_phase_restarts_soak_when_temperature_drifts() -> None:
    from drive_qual.workflows import temperature

    class FakeController:
        snapshots = [
            SimpleNamespace(timestamp="2026-06-18T12:00:00-07:00", temperature_c=30.0, temperature_f=86.0),
            SimpleNamespace(timestamp="2026-06-18T12:00:02-07:00", temperature_c=29.5, temperature_f=85.1),
            SimpleNamespace(timestamp="2026-06-18T12:00:04-07:00", temperature_c=30.0, temperature_f=86.0),
            SimpleNamespace(timestamp="2026-06-18T12:01:04-07:00", temperature_c=30.0, temperature_f=86.0),
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
    monotonic_values = iter([0.0, 10.0, 20.0, 20.0 + temperature.SETPOINT_SOAK_SECONDS])
    sleeps: list[float] = []
    original_monotonic = temperature.time.monotonic
    original_sleep = temperature.time.sleep
    temperature.time.monotonic = lambda: next(monotonic_values)
    temperature.time.sleep = lambda seconds: sleeps.append(seconds)

    try:
        temperature._run_snapshot_phase(
            controller=FakeController(),
            writer=writer,
            csv_handle=output,
            disk_tester=FakeDiskTester(),
            setpoint_c=30.0,
        )
    finally:
        temperature.time.monotonic = original_monotonic
        temperature.time.sleep = original_sleep

    rows = list(csv.DictReader(StringIO(output.getvalue())))
    assert [row["temperature_c"] for row in rows] == ["30.000", "29.500", "30.000", "30.000"]
    assert sleeps == [
        temperature.SNAPSHOT_INTERVAL_SECONDS,
        temperature.SNAPSHOT_INTERVAL_SECONDS,
        temperature.SNAPSHOT_INTERVAL_SECONDS,
    ]


def test_temperature_performance_csv_is_derived_from_snapshots_and_disk_log(tmp_path: Path) -> None:
    from drive_qual.core import temperature as temperature_plotter

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
    chart = tmp_path / "temperature_chart.png"

    temperature_plotter.write_snapshot_log_chart_outputs(
        snapshot_csv=snapshots,
        log_path=disk_log,
        profile_csv=output,
        chart_png=chart,
    )

    rows = list(csv.DictReader(StringIO(output.read_text(encoding="utf-8"))))
    assert {row["Operation"] for row in rows} == {"write", "read"}
    assert {row["Mode"] for row in rows} == {"SEQUENTIAL"}
    assert {int(float(row["RequestedTemp"])) for row in rows} == {
        -40,
        -35,
        -30,
        -20,
        -10,
        0,
        10,
        20,
        30,
        40,
        50,
        60,
        70,
    }
    assert chart.exists()


def test_temperature_chamber_returns_to_ambient_without_csv_logging(
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from drive_qual.workflows import temperature

    class FakeController:
        def __init__(self) -> None:
            self.setpoints: list[float] = []

        def write_setpoint_c(self, setpoint_c: float) -> None:
            self.setpoints.append(setpoint_c)

        def read_snapshot(self) -> object:
            raise AssertionError("ambient reset should not wait for snapshots")

    controller = FakeController()
    sleep_calls: list[float] = []
    monkeypatch.setattr(temperature.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    temperature._return_chamber_to_ambient(controller)

    assert controller.setpoints == [25.0]
    assert sleep_calls == []
    assert "Returning chamber setpoint to ambient (25 C)." in capsys.readouterr().out


def test_temperature_finalize_generates_chart_from_collected_logs(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    artifacts = temperature.TemperatureRunArtifacts(
        snapshot_csv=tmp_path / "temperature_snapshots.csv",
        performance_csv=tmp_path / "temperature_performance.csv",
        disk_tester_log=tmp_path / "disk_tester_temperature.log",
        disk_tester_stdout=tmp_path / "stdout.log",
        disk_tester_stderr=tmp_path / "stderr.log",
    )
    report_path = tmp_path / "69-420" / "drive_qualification_report_atomic_tests.json"
    report_path.parent.mkdir(parents=True)
    chart_path = tmp_path / "chart.png"
    saved: dict[str, object] = {}

    artifacts.performance_csv.write_text(
        "TempRounded,TempActual,SpeedMiB,Timestamp,TempDeltaSec,Mode,Operation\n"
        "20,20.0,107.59,2026-06-18 12:00:00,0,SEQUENTIAL,read\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(temperature, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(temperature, "_temperature_chart_path", lambda part_number, dut_name: chart_path)
    monkeypatch.setattr(
        temperature,
        "load_report",
        lambda _path: {
            "drive_info": {"apricorn_part_number": "69-420"},
            "equipment": {"dut": {"Padlock DT": {"serial_number": "ABC123"}}},
            "temperature": {"Padlock DT": {"performance": {"20c": {"read_mb_s": None, "write_mb_s": None}}}},
        },
    )
    monkeypatch.setattr(
        temperature,
        "save_report",
        lambda path, data: saved.update({"path": path, "data": json.loads(json.dumps(data))}),
    )
    monkeypatch.setattr(
        temperature.temperature_plotter,
        "write_snapshot_log_chart_outputs",
        lambda **kwargs: SimpleNamespace(empty=False),
    )

    temperature._finalize_temperature_results(folder_name="69-420", dut_name="Padlock DT", artifacts=artifacts)

    assert saved["path"] == report_path
    data = saved["data"]
    assert isinstance(data, dict)
    assert data["temperature"]["Padlock DT"]["performance"]["20c"]["read_mb_s"] == EXPECTED_PROFILE_READ_MB_S


def test_temperature_disk_tester_command_uses_temp_subcommand_and_log_path(tmp_path: Path) -> None:
    from drive_qual.workflows import temperature

    log_path = tmp_path / "disk_tester_temperature.log"

    command = temperature._disk_tester_command("D:", log_path)

    assert command[1:5] == ["-m", "drive_qual.benchmarks.disk_tester", "temp", "--path"]
    assert command[5:] == ["D:", "--log", str(log_path)]


def _write_temperature_csv(tmp_path: Path, lines: list[str]) -> Path:
    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path
