import asyncio
import os
import shutil
import sys

# Verify fio is available on PATH (Windows version)
FIO_TOOL = shutil.which("fio.exe") or shutil.which("tools/fio.exe")
if FIO_TOOL is None:
    raise FileNotFoundError("fio not found in PATH. Download from https://bsdio.com/fio/ and add to system PATH")
FIO_TOOL_STR = FIO_TOOL

# Verify diskspd is available on PATH (Windows version)
DISKSPD_TOOL = shutil.which("diskspd.exe") or shutil.which("tools/diskspd.exe")
if DISKSPD_TOOL is None:
    raise FileNotFoundError("diskspd not found in PATH. Download it and add to system PATH")
DISKSPD_TOOL_STR = DISKSPD_TOOL


async def run_fio(target_dir: str, test_type: str, size_mb: int, loops: int) -> int:
    """Run fio benchmark with specific parameters"""
    test_file = os.path.join(target_dir, "benchmark_file.dat")
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
        FIO_TOOL_STR,
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
        "0",  # Use non-buffered I/O
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
    )

    stdout, stderr = await process.communicate()

    if stdout:
        print(stdout.decode().strip())
    if stderr:
        print(stderr.decode().strip())

    if process.returncode is None:
        raise RuntimeError("fio process exited without a return code.")
    return process.returncode


async def run_diskspd(target_dir: str, test_type: str) -> int:
    """
    Run diskspd benchmark.
    For a write test, uses -w100.
    For a read test, uses -w0.
    Executes diskspd.exe with fixed parameters:
      - 1GB file, 1M block size, 1 thread, 8 outstanding I/Os, 5s duration.
    """
    test_file = os.path.join(target_dir, "testfile.dat")
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

    cmd = [DISKSPD_TOOL_STR, "-c1g", "-b1M", "-t1", "-o8", w_flag, "-d5", "-Su", test_file]

    print(f"\nStarting {test_type} benchmark (1GB file, 5s duration)")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
