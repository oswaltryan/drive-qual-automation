from __future__ import annotations

import asyncio

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.benchmarks.fio import (
    PHASE_COUNT,
    PROCESS_EXIT_GRACE_SECONDS,
    RAMP_TIME_SECONDS,
    _ioengine_for_platform,
    run_fio,
)


class _FakeProcess:
    def __init__(self, returncode: int | None = 0) -> None:
        self.returncode = returncode
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -1


def _expected_parity_args(filename: str, ioengine: str, runtime_seconds: int) -> list[str]:
    return [
        "fio",
        f"--ioengine={ioengine}",
        "--direct=1",
        "--random_generator=tausworthe64",
        f"--filename={filename}",
        "--size=1g",
        f"--runtime={runtime_seconds}",
        "--time_based=1",
        "--ramp_time=3",
        "--iodepth=32",
        "--group_reporting",
        "--name=W-SEQ-1M-Q32",
        "--rw=write",
        "--bs=1m",
        "--stonewall",
        "--name=R-SEQ-1M-Q32",
        "--rw=read",
        "--bs=1m",
        "--stonewall",
        "--name=W-RAND-4K-Q32",
        "--rw=randwrite",
        "--bs=4k",
        "--stonewall",
        "--name=R-RAND-4K-Q32",
        "--rw=randread",
        "--bs=4k",
    ]


@pytest.mark.parametrize(
    ("platform", "target_dir", "expected_filename", "expected_ioengine", "expected_cwd"),
    [
        ("darwin", "/Volumes/DUT", "/Volumes/DUT/benchmark_file.dat", "posixaio", None),
        ("linux", "/mnt/dut", "/mnt/dut/benchmark_file.dat", "posixaio", None),
        ("win32", "D:", "benchmark_file.dat", "windowsaio", "D:\\"),
    ],
)
def test_run_fio_command_parity_by_platform(
    monkeypatch: MonkeyPatch,
    platform: str,
    target_dir: str,
    expected_filename: str,
    expected_ioengine: str,
    expected_cwd: str | None,
) -> None:
    captured_args: list[object] = []
    captured_kwargs: dict[str, object] = {}

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured_args.extend(args)
        captured_kwargs.update(kwargs)
        return _FakeProcess(0)

    monkeypatch.setattr("drive_qual.benchmarks.fio._require_fio", lambda: "fio")
    monkeypatch.setattr(
        "drive_qual.benchmarks.fio.benchmark_directory",
        lambda path: "D:\\" if path in {"D", "D:"} else path,
    )
    monkeypatch.setattr(
        "drive_qual.benchmarks.fio.benchmark_file_path",
        lambda path, filename: f"{path}/{filename}",
    )
    monkeypatch.setattr("drive_qual.benchmarks.fio.sys.platform", platform)
    monkeypatch.setattr("drive_qual.benchmarks.fio.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    rc = asyncio.run(run_fio(target_dir))

    assert rc == 0
    assert captured_args == _expected_parity_args(expected_filename, expected_ioengine, 75)
    assert captured_kwargs.get("cwd") == expected_cwd


def test_run_fio_honors_runtime_override(monkeypatch: MonkeyPatch) -> None:
    captured_args: list[object] = []

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured_args.extend(args)
        return _FakeProcess(0)

    monkeypatch.setattr("drive_qual.benchmarks.fio._require_fio", lambda: "fio")
    monkeypatch.setattr("drive_qual.benchmarks.fio.benchmark_directory", lambda path: path)
    monkeypatch.setattr(
        "drive_qual.benchmarks.fio.benchmark_file_path",
        lambda path, filename: f"{path}/{filename}",
    )
    monkeypatch.setattr("drive_qual.benchmarks.fio.sys.platform", "linux")
    monkeypatch.setattr("drive_qual.benchmarks.fio.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    rc = asyncio.run(run_fio("/mnt/dut", runtime_seconds=30))

    assert rc == 0
    assert "--runtime=8" in captured_args


def test_run_fio_terminates_process_after_deadline(monkeypatch: MonkeyPatch) -> None:
    process = _FakeProcess(None)
    killed_event = asyncio.Event()
    communication_cancelled = False

    async def blocked_communicate() -> tuple[bytes, bytes]:
        nonlocal communication_cancelled
        try:
            await killed_event.wait()
        except asyncio.CancelledError:
            communication_cancelled = True
            raise
        return b"", b""

    def kill_process() -> None:
        process.killed = True
        process.returncode = -1
        killed_event.set()

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        process.communicate = blocked_communicate  # type: ignore[method-assign]
        process.kill = kill_process  # type: ignore[method-assign]
        return process

    async def immediate_timeout(awaitable: object, *, timeout: float) -> object:
        expected_timeout = PHASE_COUNT + RAMP_TIME_SECONDS * PHASE_COUNT + PROCESS_EXIT_GRACE_SECONDS
        assert timeout == expected_timeout
        raise TimeoutError

    monkeypatch.setattr("drive_qual.benchmarks.fio._require_fio", lambda: "fio")
    monkeypatch.setattr("drive_qual.benchmarks.fio.benchmark_directory", lambda path: path)
    monkeypatch.setattr(
        "drive_qual.benchmarks.fio.benchmark_file_path",
        lambda path, filename: f"{path}/{filename}",
    )
    monkeypatch.setattr("drive_qual.benchmarks.fio.sys.platform", "linux")
    monkeypatch.setattr("drive_qual.benchmarks.fio.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("drive_qual.benchmarks.fio.asyncio.wait_for", immediate_timeout)

    with pytest.raises(RuntimeError, match="process deadline"):
        asyncio.run(run_fio("/mnt/dut", runtime_seconds=4))

    assert (process.killed, communication_cancelled) == (True, False)


def test_run_fio_rejects_runtime_shorter_than_phase_count() -> None:
    with pytest.raises(ValueError, match="at least 4 seconds"):
        asyncio.run(run_fio("/mnt/dut", runtime_seconds=3))


def test_run_fio_terminates_process_when_cancelled(monkeypatch: MonkeyPatch) -> None:
    process = _FakeProcess(None)
    killed_event = asyncio.Event()

    async def blocked_communicate() -> tuple[bytes, bytes]:
        await killed_event.wait()
        return b"", b""

    def kill_process() -> None:
        process.killed = True
        process.returncode = -1
        killed_event.set()

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        process.communicate = blocked_communicate  # type: ignore[method-assign]
        process.kill = kill_process  # type: ignore[method-assign]
        return process

    async def run_and_cancel() -> None:
        task = asyncio.create_task(run_fio("/mnt/dut", runtime_seconds=4))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    monkeypatch.setattr("drive_qual.benchmarks.fio._require_fio", lambda: "fio")
    monkeypatch.setattr("drive_qual.benchmarks.fio.benchmark_directory", lambda path: path)
    monkeypatch.setattr(
        "drive_qual.benchmarks.fio.benchmark_file_path",
        lambda path, filename: f"{path}/{filename}",
    )
    monkeypatch.setattr("drive_qual.benchmarks.fio.sys.platform", "linux")
    monkeypatch.setattr("drive_qual.benchmarks.fio.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    asyncio.run(run_and_cancel())

    assert process.killed is True


def test_ioengine_for_platform_raises_on_unsupported_platform(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("drive_qual.benchmarks.fio.sys.platform", "freebsd")

    with pytest.raises(RuntimeError, match="Unsupported platform for fio"):
        _ioengine_for_platform()
