from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def _write_temperature_csv(tmp_path: Path, lines: list[str]) -> Path:
    csv_path = tmp_path / "temperature_rows.csv"
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path
