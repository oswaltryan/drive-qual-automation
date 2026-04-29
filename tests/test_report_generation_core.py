from __future__ import annotations

import builtins
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from _pytest.monkeypatch import MonkeyPatch


def test_report_generation_import_does_not_import_docx(monkeypatch: MonkeyPatch) -> None:
    sys.modules.pop("drive_qual.reports.generate", None)

    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "docx" or name.startswith("docx."):
            raise AssertionError("report generation imported python-docx eagerly")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("drive_qual.reports.generate")

    assert module.DEFAULT_OUTPUT_NAME == "drive_qualification_report.docx"


def test_generate_report_uses_source_root_for_input_and_default_output(monkeypatch: MonkeyPatch) -> None:
    module = importlib.import_module("drive_qual.reports.generate")
    source_root = Path("tests/.tmp/test_report_generation")
    part_dir = source_root / "69-420"
    part_dir.mkdir(parents=True, exist_ok=True)
    report_path = part_dir / "drive_qualification_report_atomic_tests.json"
    report_path.write_text(json.dumps({"drive_info": {"apricorn_part_number": "69-420"}}), encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_write_docx_report(
        data: dict[str, Any], evaluated: Any, source_report_path: Path, output_path: Path
    ) -> None:
        captured["data"] = data
        captured["source_report_path"] = source_report_path
        captured["output_path"] = output_path

    monkeypatch.setattr(module, "write_docx_report", fake_write_docx_report)

    output_path = module.generate_report_docx(part_number="69-420", source_root=source_root)

    assert output_path == part_dir / "drive_qualification_report.docx"
    assert captured["source_report_path"] == report_path
    assert captured["output_path"] == output_path
    assert captured["data"]["drive_info"]["apricorn_part_number"] == "69-420"
