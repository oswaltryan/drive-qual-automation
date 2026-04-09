from __future__ import annotations

import asyncio

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.benchmarks.fio import run_fio


class _FakeProcess:
    def __init__(self, returncode: int | None = 0) -> None:
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


def test_run_fio_omits_ioengine_on_macos(monkeypatch: MonkeyPatch) -> None:
    captured: list[object] = []

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.extend(args)
        return _FakeProcess(0)

    monkeypatch.setattr("drive_qual.benchmarks.fio._require_fio", lambda: "fio")
    monkeypatch.setattr("drive_qual.benchmarks.fio.benchmark_directory", lambda target_dir: target_dir)
    monkeypatch.setattr(
        "drive_qual.benchmarks.fio.benchmark_file_path",
        lambda target_dir, filename: f"{target_dir}/{filename}",
    )
    monkeypatch.setattr("drive_qual.benchmarks.fio.sys.platform", "darwin")
    monkeypatch.setattr("drive_qual.benchmarks.fio.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    rc = asyncio.run(run_fio("/Volumes/DUT", "write", 10, 1))

    assert rc == 0
    assert "--ioengine" not in captured


def test_run_fio_sets_linux_ioengine(monkeypatch: MonkeyPatch) -> None:
    captured: list[object] = []

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.extend(args)
        return _FakeProcess(0)

    monkeypatch.setattr("drive_qual.benchmarks.fio._require_fio", lambda: "fio")
    monkeypatch.setattr("drive_qual.benchmarks.fio.benchmark_directory", lambda target_dir: target_dir)
    monkeypatch.setattr(
        "drive_qual.benchmarks.fio.benchmark_file_path",
        lambda target_dir, filename: f"{target_dir}/{filename}",
    )
    monkeypatch.setattr("drive_qual.benchmarks.fio.sys.platform", "linux")
    monkeypatch.setattr("drive_qual.benchmarks.fio.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    rc = asyncio.run(run_fio("/mnt/dut", "read", 10, 1))

    assert rc == 0
    assert "--ioengine" in captured
    idx = captured.index("--ioengine")
    assert captured[idx + 1] == "libaio"
