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

# Verify fio is available on PATH (Windows version)
FIO_TOOL = shutil.which("fio.exe") or shutil.which("tools/fio.exe")
if FIO_TOOL is None:
    raise FileNotFoundError("fio not found in PATH. Download from https://bsdio.com/fio/ and add to system PATH")
FIO_TOOL_STR = FIO_TOOL


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


async def run_fio_benchmark(target_dir: str, test_type: str, size_mb: int, loops: int) -> int:
    """Run fio benchmark with Windows-specific parameters"""
    test_file = os.path.join(target_dir, "benchmark_file.dat")
    cmd = [
        FIO_TOOL_STR,
        "--name",
        f"{test_type}_test",
        "--filename",
        test_file,
        "--size",
        f"{size_mb}m",
        "--rw",
        test_type,
        "--ioengine",
        "windowsaio",  # Windows-specific I/O engine
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
    write_ret = await run_fio_benchmark(target_directory, "write", 10, 100)
    # Run read benchmark
    read_ret = await run_fio_benchmark(target_directory, "read", 10, 100)

    # Cleanup test file
    test_file = os.path.join(target_directory, "benchmark_file.dat")
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
