from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from types import SimpleNamespace

from _pytest.monkeypatch import MonkeyPatch

EXPECTED_TOTAL_ATTEMPTS = 3
BurstResult = tuple[dict[str, object] | None, dict[str, object] | None]


def test_temperature_operation_retries_without_prompt(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.benchmarks import disk_tester

    results: Iterator[BurstResult] = iter(
        [
            (None, {"returncode": 1, "stderr": "windows error 121"}),
            (None, {"returncode": 1, "stderr": "windows error 121"}),
            ({"jobs": []}, None),
        ]
    )
    sleeps: list[float] = []
    monkeypatch.setattr(disk_tester, "_run_temp_burst", lambda *_args: next(results))
    monkeypatch.setattr("drive_qual.benchmarks.disk_tester.time.sleep", sleeps.append)
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args: (_ for _ in ()).throw(AssertionError("automated retry must not prompt")),
    )
    args = SimpleNamespace(failure_action="retry", max_retries=3, retry_delay=2.0)

    succeeded = disk_tester._run_temp_operation(
        ("Sequential Write", "SEQUENTIAL", "write", "1M"),
        [],
        StringIO(),
        args,
    )

    assert succeeded is True
    assert sleeps == [2.0, 2.0]


def test_temperature_operation_stops_after_retry_limit(monkeypatch: MonkeyPatch) -> None:
    from drive_qual.benchmarks import disk_tester

    attempts: list[int] = []

    def fail_burst(*_args: object) -> tuple[None, dict[str, object]]:
        attempts.append(1)
        return None, {"returncode": 1, "stderr": "Input/output error"}

    monkeypatch.setattr(disk_tester, "_run_temp_burst", fail_burst)
    monkeypatch.setattr("drive_qual.benchmarks.disk_tester.time.sleep", lambda _seconds: None)
    args = SimpleNamespace(failure_action="retry", max_retries=2, retry_delay=0.0)

    succeeded = disk_tester._run_temp_operation(
        ("Sequential Write", "SEQUENTIAL", "write", "1M"),
        [],
        StringIO(),
        args,
    )

    assert succeeded is False
    assert len(attempts) == EXPECTED_TOTAL_ATTEMPTS
