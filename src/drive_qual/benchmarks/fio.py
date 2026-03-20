from __future__ import annotations

import asyncio
import sys

from drive_qual.benchmarks.common import _require_fio, benchmark_directory, benchmark_file_path


async def run_fio(target_dir: str, test_type: str, size_mb: int, loops: int) -> int:
    """Run fio benchmark with specific parameters."""
    fio_tool = _require_fio()
    work_dir = benchmark_directory(target_dir)
    test_file = (
        "benchmark_file.dat" if sys.platform == "win32" else benchmark_file_path(target_dir, "benchmark_file.dat")
    )
    engine: str
    if sys.platform == "darwin":
        engine = ""
    elif sys.platform == "linux":
        engine = "libaio"
    elif sys.platform == "win32":
        engine = "windowsaio"
    else:
        raise RuntimeError(f"Unsupported platform for fio: {sys.platform}")
    cmd = [
        fio_tool,
        "--name",
        f"{test_type}_test",
        "--filename",
        test_file,
        "--size",
        f"{size_mb}M",
        "--rw",
        test_type,
        "--ioengine",
        engine,
        "--buffered",
        "0",
        "--bs",
        "4k",
        "--numjobs",
        "1",
        "--loops",
        str(loops),
        "--output-format",
        "normal",
    ]

    print(f"\nStarting {test_type} benchmark ({loops} passes, {size_mb}MB file)")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir if sys.platform == "win32" else None,
    )

    stdout, stderr = await process.communicate()

    if stdout:
        print(stdout.decode().strip())
    if stderr:
        print(stderr.decode().strip())

    if process.returncode is None:
        raise RuntimeError("fio process exited without a return code.")
    return process.returncode
