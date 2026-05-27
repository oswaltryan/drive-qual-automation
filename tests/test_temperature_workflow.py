from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core.temperature import load_temperature_performance_csv, update_temperature_performance


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
