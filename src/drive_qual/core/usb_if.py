from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT

MSC_RESULT_RE = re.compile(r"Tests\s+run\s*\((?P<runs>\d+)\),\s*Failures\s*\((?P<failures>\d+)\)", re.I)


@dataclass(frozen=True)
class UsbIfIterationResult:
    tests_run: int
    failures: int

    @property
    def passed(self) -> bool:
        return self.failures == 0


@dataclass(frozen=True)
class UsbIfMscResult:
    iterations: int
    iteration_results: tuple[UsbIfIterationResult, ...]
    artifact_dir: Path

    @property
    def passed(self) -> bool:
        return len(self.iteration_results) == self.iterations and all(
            result.passed for result in self.iteration_results
        )


def usb_if_artifact_dir(part_number: str) -> Path:
    return Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, "Windows", "USB-IF")))


def parse_msc_result_line(log_text: str) -> UsbIfIterationResult | None:
    for line in reversed(log_text.splitlines()):
        match = MSC_RESULT_RE.search(line)
        if match is None:
            continue
        return UsbIfIterationResult(
            tests_run=int(match.group("runs")),
            failures=int(match.group("failures")),
        )
    return None


def update_usb_if_compliance(data: dict[str, Any], result: UsbIfMscResult) -> None:
    compliance = data.setdefault("compliance", {})
    if not isinstance(compliance, dict):
        raise ValueError("Invalid 'compliance' section; expected object.")
    compliance["usb_if_msc_iterations"] = result.iterations
    compliance["usb_if_msc_result"] = result.passed
