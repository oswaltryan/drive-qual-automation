from __future__ import annotations

import json
import sys
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.integrations.apricorn.usb_cli import ApricornDevice
from drive_qual.platforms.windows import performance

EXPECTED_LINUX_READ = 123.4
EXPECTED_LINUX_WRITE = 234.5


def test_run_software_step_records_linux_manual_results(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "drive_qualification_report_atomic_tests.json"
    report_path.write_text(
        json.dumps(
            {
                "drive_info": {"apricorn_part_number": "69-420"},
                "equipment": {
                    "windows_host": {"software": []},
                    "linux_host": {"software": [{"name": "Disks (native)", "version": None}]},
                    "macos_host": {"software": []},
                    "dut": ["Padlock DT"],
                },
                "performance": {"Padlock DT": {"Windows": {}, "Linux": {}, "macOS": {}}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(performance, "resolve_folder_name", lambda part_number=None: "69-420")
    monkeypatch.setattr(performance, "report_path_for", lambda folder_name: report_path)
    monkeypatch.setattr(
        performance,
        "_wait_for_device_present",
        lambda prompt: ApricornDevice(iProduct="Secure Key DT", iSerial="ABC123"),
    )

    responses = iter([str(EXPECTED_LINUX_READ), str(EXPECTED_LINUX_WRITE)])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    performance.run_software_step(part_number="69-420")

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["performance"]["Padlock DT"]["Linux"]["Disks (native)"]["read"] == EXPECTED_LINUX_READ
    assert data["performance"]["Padlock DT"]["Linux"]["Disks (native)"]["write"] == EXPECTED_LINUX_WRITE
    assert data["performance"]["Padlock DT"]["Windows"] == {}
