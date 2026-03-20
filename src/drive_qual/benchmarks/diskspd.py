from __future__ import annotations

import asyncio
import sys

from drive_qual.benchmarks.common import _require_diskspd, benchmark_directory, benchmark_file_path

MIN_DISKSPD_PARTS = 4


def parse_diskspd_output(output: str) -> dict[str, str]:
    """
    Parse diskspd output to extract key metrics.
    Looks for a line starting with 'total:' and extracts:
      - bytes
      - I/Os
      - MiB/s
      - I/O per s
    """
    metrics = {}
    for line in output.splitlines():
        if line.lower().startswith("total:"):
            parts = line.split("|")
            if len(parts) >= MIN_DISKSPD_PARTS:
                metrics["bytes"] = parts[0].split("total:")[-1].strip()
                metrics["I/Os"] = parts[1].strip()
                metrics["MiB/s"] = parts[2].strip()
                metrics["I/O per s"] = parts[3].strip()
            break
    return metrics


async def run_diskspd(target_dir: str, test_type: str) -> int:
    """
    Run diskspd benchmark.
    For a write test, uses -w100.
    For a read test, uses -w0.
    Executes diskspd.exe with fixed parameters:
      - 1GB file, 1M block size, 1 thread, 8 outstanding I/Os, 5s duration.
    """
    diskspd_tool = _require_diskspd()
    work_dir = benchmark_directory(target_dir)
    test_file = "testfile.dat" if sys.platform == "win32" else benchmark_file_path(target_dir, "testfile.dat")
    if sys.platform in ("darwin", "linux"):
        raise RuntimeError("diskspd is only supported on Windows.")
    if sys.platform != "win32":
        raise RuntimeError(f"Unsupported platform for diskspd: {sys.platform}")

    if test_type.lower() == "write":
        w_flag = "-w100"
    elif test_type.lower() == "read":
        w_flag = "-w0"
    else:
        raise ValueError("Invalid test_type. Expected 'read' or 'write'.")

    cmd = [diskspd_tool, "-c1g", "-b1M", "-t1", "-o8", w_flag, "-d5", "-Su", test_file]

    print(f"\nStarting {test_type} benchmark (1GB file, 5s duration)")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir if sys.platform == "win32" else None,
    )

    stdout, stderr = await process.communicate()
    output = stdout.decode().strip()
    err_output = stderr.decode().strip()

    if output:
        print(output)
    if err_output:
        print(err_output)

    metrics = parse_diskspd_output(output)
    if metrics:
        print(f"Parsed Metrics: {metrics}")

    if process.returncode is None:
        raise RuntimeError("diskspd process exited without a return code.")
    return process.returncode
