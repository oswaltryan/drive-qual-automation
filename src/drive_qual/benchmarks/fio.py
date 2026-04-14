from __future__ import annotations

import asyncio
import sys

from drive_qual.benchmarks.common import _require_fio, benchmark_directory, benchmark_file_path

DEFAULT_RUNTIME_SECONDS = 300
RAMP_TIME_SECONDS = 3
IODEPTH = 32
RANDOM_GENERATOR = "tausworthe64"


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


async def run_fio(target_dir: str, *, runtime_seconds: int = DEFAULT_RUNTIME_SECONDS) -> int:
    """Run the cross-platform fio parity suite (seq/rand write+read) as a single command."""
    cmd, cwd = _fio_command(target_dir, runtime_seconds=runtime_seconds)

    print(f"\nStarting fio parity suite ({runtime_seconds}s runtime per phase)")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    stdout, stderr = await process.communicate()

    if stdout:
        print(stdout.decode().strip())
    if stderr:
        print(stderr.decode().strip())

    if process.returncode is None:
        raise RuntimeError("fio process exited without a return code.")
    return process.returncode
