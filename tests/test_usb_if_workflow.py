from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch


def test_usb_if_workflow_skips_non_windows_before_windows_import(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    sys.modules.pop("drive_qual.workflows.usb_if", None)
    module = importlib.import_module("drive_qual.workflows.usb_if")
    monkeypatch.setattr(sys, "platform", "darwin")

    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "drive_qual.platforms.windows.usb_if":
            raise AssertionError("usb_if workflow imported Windows automation on a non-Windows host")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module.run_usb_if_step(part_number="69-420")

    assert capsys.readouterr().out == "Skipping USB-IF MSC workflow: usb_if is Windows-only.\n"


def test_windows_usb_if_runner_rejects_non_windows(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.platforms.windows.usb_if import run_usb_if_msc

    monkeypatch.setattr(sys, "platform", "darwin")

    with pytest.raises(RuntimeError, match="USB-IF MSC automation is Windows-only"):
        run_usb_if_msc(part_number="69-420", artifact_dir=Path("reports"))
