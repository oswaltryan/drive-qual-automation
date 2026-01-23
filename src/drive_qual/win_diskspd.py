import asyncio
import os
import shutil
import time
from typing import Any

from .tektronix import (
    backup_session,
    mk_dir,
    recall_setup,
    save_measurements,
    stop_run,
)
from .usb_tool import find_apricorn_device

part_number = input("Enter the Apricorn P/N for this drive: ")
device: Any | None = None
dut_type: str | None = None

# Verify diskspd is available on PATH (Windows version)
DISKSPD_TOOL = shutil.which("diskspd.exe") or shutil.which("tools/diskspd.exe")
if DISKSPD_TOOL is None:
    raise FileNotFoundError("diskspd not found in PATH. Download it and add to system PATH")
DISKSPD_TOOL_STR = DISKSPD_TOOL

MIN_DISKSPD_PARTS = 4


def dut_enumeration(unlock_dut: bool = True) -> None:
    global device, dut_type
    if unlock_dut:
        print("Unlock Apricorn device..")
        while device is None:
            device = find_apricorn_device()
        assert device is not None
        dut_type = "Secure Key" if device.iProduct == "Secure Key 3.0" else "Portable"
        print(f"Found device: {device.iProduct}")
    else:
        # device = None
        device = find_apricorn_device()
        if device is not None:
            print("Remove Apricorn device..")
        while device is not None:
            device = find_apricorn_device()


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


async def run_diskspd_benchmark(target_dir: str, test_type: str) -> int:
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


async def in_rush_current() -> None:
    global device, dut_type
    recall_setup(setup_type="InRush", device_type=dut_type or "Portable")  # Initialize Tektronix equipment
    mk_dir(
        os.path.join("E:\\", part_number, "Windows", "In Rush Current")
    )  # Create directory for In Rush Current results

    time.sleep(3)
    dut_enumeration(unlock_dut=True)


async def max_IO() -> None:
    target_directory = "E"  # Update with your test directory
    recall_setup(setup_type="Max IO")  # Initialize Tektronix equipment
    mk_dir(os.path.join("E:\\", part_number, "Windows", "Max IO"))  # Create directory for Max IO results

    # Run write benchmark
    write_ret = await run_diskspd_benchmark(target_directory, "write")
    # Run read benchmark
    read_ret = await run_diskspd_benchmark(target_directory, "read")

    # Cleanup test file
    test_file = os.path.join(target_directory, "testfile.dat")
    try:
        os.remove(test_file)
        print(f"\nCleaned up test file: {test_file}")
    except Exception as e:
        print(f"\nError cleaning up test file: {e}")

    # Check results
    if write_ret == 0 and read_ret == 0:
        print("\nBenchmark completed successfully")
    else:
        print(f"\nBenchmark failed - Write: {write_ret}, Read: {read_ret}")


if __name__ == "__main__":
    dut_enumeration(unlock_dut=True)

    try:
        asyncio.run(max_IO())
    except Exception as e:
        print(f"Critical error: {e}")
    finally:
        if device is None:
            raise RuntimeError("Device not detected for Max IO results.")
        stop_run()  # Ensure Tektronix equipment stops
        save_measurements(f"E:\\{part_number}\\Windows\\Max IO\\{device.iProduct}.csv")
        backup_session(f"E:\\{part_number}\\Windows\\Max IO\\{device.iProduct}.png")
        dut_enumeration(unlock_dut=False)
        print("")

    try:
        asyncio.run(in_rush_current())
    except Exception as e:
        print(f"Critical error: {e}")
    finally:
        if device is None:
            raise RuntimeError("Device not detected for In Rush results.")
        stop_run()  # Ensure Tektronix equipment stops
        save_measurements(f"E:\\{part_number}\\Windows\\In Rush Current\\{device.iProduct}.csv")
        backup_session(f"E:\\{part_number}\\Windows\\In Rush Current\\{device.iProduct}.png")
