from __future__ import annotations

import asyncio
import math
import sys
from contextlib import suppress

from drive_qual.benchmarks.common import _require_fio, benchmark_directory, benchmark_file_path

DEFAULT_RUNTIME_SECONDS = 300
RAMP_TIME_SECONDS = 3
IODEPTH = 32
RANDOM_GENERATOR = "tausworthe64"
WORKLOAD_SIZE = "1g"
PHASE_COUNT = 4
PROCESS_EXIT_GRACE_SECONDS = 60


def _ioengine_for_platform() -> str:
    if sys.platform == "darwin":
        return "posixaio"
    if sys.platform == "linux":
        return "posixaio"
    if sys.platform == "win32":
        return "windowsaio"
    raise RuntimeError(f"Unsupported platform for fio: {sys.platform}")


def _target_filename(target_dir: str) -> str:
    if sys.platform == "win32":
        return "benchmark_file.dat"
    return benchmark_file_path(target_dir, "benchmark_file.dat")


def _fio_command(target_dir: str, *, runtime_seconds: int) -> tuple[list[str], str | None]:
    fio_tool = _require_fio()
    work_dir = benchmark_directory(target_dir)
    filename = _target_filename(target_dir)

    cmd = [
        fio_tool,
        f"--ioengine={_ioengine_for_platform()}",
        "--direct=1",
        f"--random_generator={RANDOM_GENERATOR}",
        f"--filename={filename}",
        f"--size={WORKLOAD_SIZE}",
        f"--runtime={runtime_seconds}",
        "--time_based=1",
        f"--ramp_time={RAMP_TIME_SECONDS}",
        f"--iodepth={IODEPTH}",
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

    cwd = work_dir if sys.platform == "win32" else None
    return cmd, cwd


def _runtime_plan(runtime_seconds: int) -> tuple[int, int]:
    if runtime_seconds < PHASE_COUNT:
        raise ValueError(f"fio runtime must be at least {PHASE_COUNT} seconds.")
    phase_runtime_seconds = math.ceil(runtime_seconds / PHASE_COUNT)
    expected_runtime_seconds = phase_runtime_seconds * PHASE_COUNT + RAMP_TIME_SECONDS * PHASE_COUNT
    return phase_runtime_seconds, expected_runtime_seconds + PROCESS_EXIT_GRACE_SECONDS


def _kill_process(process: asyncio.subprocess.Process) -> None:
    with suppress(ProcessLookupError):
        process.kill()


async def _communicate_with_deadline(process: asyncio.subprocess.Process, timeout_seconds: int) -> tuple[bytes, bytes]:
    communication = asyncio.create_task(process.communicate())
    try:
        return await asyncio.wait_for(asyncio.shield(communication), timeout=timeout_seconds)
    except TimeoutError as exc:
        _kill_process(process)
        await communication
        raise RuntimeError(f"fio exceeded its {timeout_seconds}s process deadline and was terminated.") from exc
    except BaseException:
        if process.returncode is None:
            _kill_process(process)
        await communication
        raise


async def run_fio(target_dir: str, *, runtime_seconds: int = DEFAULT_RUNTIME_SECONDS) -> int:
    """Run the fio parity suite for approximately ``runtime_seconds`` total."""
    phase_runtime_seconds, timeout_seconds = _runtime_plan(runtime_seconds)
    cmd, cwd = _fio_command(target_dir, runtime_seconds=phase_runtime_seconds)

    print(f"\nStarting fio parity suite (~{runtime_seconds}s total, {phase_runtime_seconds}s per phase plus ramp time)")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    stdout, stderr = await _communicate_with_deadline(process, timeout_seconds)

    if stdout:
        print(stdout.decode().strip())
    if stderr:
        print(stderr.decode().strip())

    if process.returncode is None:
        raise RuntimeError("fio process exited without a return code.")
    return process.returncode
