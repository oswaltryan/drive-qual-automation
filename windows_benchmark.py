import asyncio
import shutil
import os

# Make sure these tools are on your PATH so that shutil.which() can find them
DISKSPD_TOOL = shutil.which("diskspd.exe")
FIO_TOOL = shutil.which("fio.exe")

if DISKSPD_TOOL is None:
    raise FileNotFoundError(
        "diskspd not found in PATH. Download it and add to system PATH."
    )

if FIO_TOOL is None:
    raise FileNotFoundError(
        "fio not found in PATH. Download from https://bsdio.com/fio/ "
        "and add to system PATH."
    )

def parse_diskspd_output(output: str) -> dict:
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
            if len(parts) >= 4:
                metrics["bytes"] = parts[0].split("total:")[-1].strip()
                metrics["I/Os"] = parts[1].strip()
                metrics["MiB/s"] = parts[2].strip()
                metrics["I/O per s"] = parts[3].strip()
            break
    return metrics

async def run_diskspd_benchmark(target_dir, test_type):
    """
    Run diskspd benchmark.
    For a write test, uses -w100.
    For a read test, uses -w0.
    Executes diskspd.exe with fixed parameters:
      - 1GB file, 1M block size, 1 thread, 8 outstanding I/Os, 5s duration.
    """
    test_file = os.path.join(target_dir, "testfile.dat")
    if test_type.lower() == "write":
        w_flag = "-w100"
    elif test_type.lower() == "read":
        w_flag = "-w0"
    else:
        raise ValueError("Invalid test_type. Expected 'read' or 'write'.")

    cmd = [
        DISKSPD_TOOL,
        "-c1g",
        "-b1M",
        "-t1",
        "-o8",
        w_flag,
        "-d5",
        "-Su",
        test_file
    ]
    
    print(f"\nStarting {test_type} benchmark (1GB file, 5s duration)")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
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
    
    return process.returncode

async def run_fio_benchmark(target_dir, test_type, size_mb, loops):
    """
    Run fio benchmark with Windows-specific parameters:
      - 'test_type' must be something fio recognizes (e.g. 'read', 'write', 'randread', etc.)
      - 'size_mb' is the size of the file to test, in MB
      - 'loops' is how many times to run the I/O operations
    """
    test_file = os.path.join(target_dir, "benchmark_file.dat")
    cmd = [
        FIO_TOOL,
        "--name", f"{test_type}_test",
        "--filename", test_file,
        "--size", f"{size_mb}m",
        "--rw", test_type,
        "--ioengine", "windowsaio",  # Windows-specific I/O engine
        "--buffered", "0",           # Use non-buffered I/O
        "--bs", "4k",
        "--numjobs", "1",
        "--loops", str(loops),
        "--output-format", "normal"
    ]
    
    print(f"\nStarting {test_type} benchmark ({loops} passes, {size_mb}MB file)")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    if stdout:
        print(stdout.decode().strip())
    if stderr:
        print(stderr.decode().strip())
    
    return process.returncode

# ---------------------------------------------------------------------------
# Example usage (will only run if this file is executed directly, e.g.:
# python windows_benchmark.py
# ---------------------------------------------------------------------------
# if __name__ == "__main__":
#     # Example: run a "write" benchmark on drive "D:" using diskspd
#     print("\n--- Example DiskSpd Benchmark on Drive D: ---\n")
#     asyncio.run(run_diskspd_benchmark("D:", "write"))
