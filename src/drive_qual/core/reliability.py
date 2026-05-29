from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT

PASSES_REQUIRED = 3
RELIABILITY_ARTIFACT_CATEGORY = "Reliability"

SUMMARY_MARKER = "--- Full Test Summary ---"
WRITE_ERRORS_RE = re.compile(r"Write Errors:\s*(?P<value>\d+)", re.I)
READ_ERRORS_RE = re.compile(r"Read Errors:\s*(?P<value>\d+)", re.I)
MISMATCHES_RE = re.compile(r"Mismatches:\s*(?P<value>\d+)", re.I)
NON_FATAL_RE = re.compile(r"Total Non-Fatal Errors Reported:\s*(?P<value>\d+)", re.I)


@dataclass(frozen=True)
class ReliabilitySummary:
    write_errors: int
    read_errors: int
    mismatches: int
    total_non_fatal_errors: int

    @property
    def passed(self) -> bool:
        return (
            self.write_errors == 0
            and self.read_errors == 0
            and self.mismatches == 0
            and self.total_non_fatal_errors == 0
        )


@dataclass(frozen=True)
class ReliabilityResult:
    passes_required: int
    passes_completed: int
    passes_requested_this_run: int
    write_errors: int | None
    read_errors: int | None
    mismatches: int | None
    total_non_fatal_errors: int | None
    return_code: int | None

    @property
    def passed(self) -> bool:
        return (
            self.passes_completed >= self.passes_required
            and self.write_errors == 0
            and self.read_errors == 0
            and self.mismatches == 0
            and self.total_non_fatal_errors == 0
            and (self.return_code is None or self.return_code == 0)
        )

    @property
    def status(self) -> str:
        if self.passes_completed < self.passes_required:
            return "incomplete"
        return "pass" if self.passed else "fail"


def reliability_artifact_dir(part_number: str) -> Path:
    return Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, "Windows", RELIABILITY_ARTIFACT_CATEGORY)))


def reliability_artifact_log_path(part_number: str) -> Path:
    return reliability_artifact_dir(part_number) / f"{part_number}_reliability.log"


def default_reliability_section() -> dict[str, Any]:
    return {
        "windows": {
            "passes_required": PASSES_REQUIRED,
            "passes_completed": 0,
            "passes_requested_this_run": 0,
            "status": "pending",
            "write_errors": None,
            "read_errors": None,
            "mismatches": None,
            "total_non_fatal_errors": None,
            "return_code": None,
        }
    }


def ensure_reliability_section(data: dict[str, Any]) -> dict[str, Any]:
    reliability = data.setdefault("reliability", {})
    if not isinstance(reliability, dict):
        raise ValueError("Invalid 'reliability' section; expected object.")
    windows = reliability.setdefault("windows", {})
    if not isinstance(windows, dict):
        raise ValueError("Invalid 'reliability.windows' section; expected object.")
    for key, value in default_reliability_section()["windows"].items():
        windows.setdefault(key, value)
    return windows


def parse_reliability_log_text(text: str) -> tuple[ReliabilitySummary, ...]:
    summaries: list[ReliabilitySummary] = []
    lines = text.splitlines()
    marker_indexes = [index for index, line in enumerate(lines) if SUMMARY_MARKER in line]
    for marker_index in marker_indexes:
        block = "\n".join(lines[marker_index : marker_index + 8])
        summary = _parse_summary_block(block)
        if summary is not None:
            summaries.append(summary)
    return tuple(summaries)


def aggregate_reliability_summaries(
    summaries: tuple[ReliabilitySummary, ...],
    *,
    passes_requested_this_run: int,
    return_code: int | None,
    passes_required: int = PASSES_REQUIRED,
) -> ReliabilityResult:
    if not summaries:
        return ReliabilityResult(
            passes_required=passes_required,
            passes_completed=0,
            passes_requested_this_run=passes_requested_this_run,
            write_errors=None,
            read_errors=None,
            mismatches=None,
            total_non_fatal_errors=None,
            return_code=return_code,
        )
    return ReliabilityResult(
        passes_required=passes_required,
        passes_completed=len(summaries),
        passes_requested_this_run=passes_requested_this_run,
        write_errors=sum(summary.write_errors for summary in summaries),
        read_errors=sum(summary.read_errors for summary in summaries),
        mismatches=sum(summary.mismatches for summary in summaries),
        total_non_fatal_errors=sum(summary.total_non_fatal_errors for summary in summaries),
        return_code=return_code,
    )


def parse_reliability_log(
    log_path: Path,
    *,
    passes_requested_this_run: int = 0,
    return_code: int | None = None,
) -> ReliabilityResult:
    if not log_path.exists():
        return aggregate_reliability_summaries(
            (),
            passes_requested_this_run=passes_requested_this_run,
            return_code=return_code,
        )
    summaries = parse_reliability_log_text(log_path.read_text(encoding="utf-8", errors="replace"))
    return aggregate_reliability_summaries(
        summaries,
        passes_requested_this_run=passes_requested_this_run,
        return_code=return_code,
    )


def update_reliability_report(data: dict[str, Any], result: ReliabilityResult) -> None:
    windows = ensure_reliability_section(data)
    windows.update(
        {
            "passes_required": result.passes_required,
            "passes_completed": result.passes_completed,
            "passes_requested_this_run": result.passes_requested_this_run,
            "status": result.status,
            "write_errors": result.write_errors,
            "read_errors": result.read_errors,
            "mismatches": result.mismatches,
            "total_non_fatal_errors": result.total_non_fatal_errors,
            "return_code": result.return_code,
        }
    )


def _parse_summary_block(block: str) -> ReliabilitySummary | None:
    write_errors = _extract_int(WRITE_ERRORS_RE, block)
    read_errors = _extract_int(READ_ERRORS_RE, block)
    mismatches = _extract_int(MISMATCHES_RE, block)
    total_non_fatal_errors = _extract_int(NON_FATAL_RE, block)
    if write_errors is None or read_errors is None or mismatches is None or total_non_fatal_errors is None:
        return None
    return ReliabilitySummary(
        write_errors=write_errors,
        read_errors=read_errors,
        mismatches=mismatches,
        total_non_fatal_errors=total_non_fatal_errors,
    )


def _extract_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    if match is None:
        return None
    return int(match.group("value"))
