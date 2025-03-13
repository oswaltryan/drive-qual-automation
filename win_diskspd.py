import asyncio
import shutil
import os
import time
from tektronix import *
from windows_usb import *
from pprint import pprint

part_number = input("Enter the Apricorn P/N for this drive: ")
device = None
dut_type = None

# Verify diskspd is available on PATH (Windows version)
DISKSPD_TOOL = shutil.which("diskspd.exe")
if DISKSPD_TOOL is None:
    raise FileNotFoundError(
        "diskspd not found in PATH. Download it and add to system PATH"
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

async def in_rush_current():
    global device, dut_type
    target_directory = "E"  # Update with your test directory
    recall_setup(setup_type="InRush", device_type=dut_type)  # Initialize Tektronix equipment
    mk_dir(os.path.join("E:\\", part_number, "Windows", "In Rush Current"))  # Create directory for In Rush Current results
    
    os.makedirs(target_directory, exist_ok=True)
    
    print("Unlock Apricorn device..")
    while device is None:
        device = find_apricorn_device()
    
    if device.iProduct == "Secure Key 3.0":
        dut_type = "Secure Key"
    else:
        dut_type = "Portable"
    
    time.sleep(3)

async def max_IO():
    target_directory = "E"  # Update with your test directory
    recall_setup(setup_type="Max IO")  # Initialize Tektronix equipment
    mk_dir(os.path.join("E:\\", part_number, "Windows", "Max IO"))  # Create directory for Max IO results
    
    os.makedirs(target_directory, exist_ok=True)
    
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
    
    if write_ret == 0 and read_ret == 0:
        print("\nBenchmark completed successfully")
    else:
        print(f"\nBenchmark failed - Write: {write_ret}, Read: {read_ret}")

if __name__ == "__main__":
    print("Unlock Apricorn device..")
    get_device = None
    while get_device is None:
        get_device = find_apricorn_device()
    
    if get_device.iProduct == "Secure Key 3.0":
        dut_type = "Secure Key"
    else:
        dut_type = "Portable"
    print(f"Found device: {get_device.iProduct}")
    
    device_under_test = find_apricorn_device()
    if device_under_test is not None:
        print("Remove Apricorn device to start In-Rush test..")
    while device_under_test is not None:
        device_under_test = find_apricorn_device()
    
    try:
        asyncio.run(in_rush_current())
    except Exception as e:
        print(f"Critical error: {e}")
    finally:
        stop_run()  # Ensure Tektronix equipment stops
        save_measurements(f"E:\\{part_number}\\Windows\\In Rush Current\\{device.iProduct}.csv")
        backup_session(f"E:\\{part_number}\\Windows\\In Rush Current\\{device.iProduct}.png")
        print("")
        time.sleep(3)
    
    try:
        asyncio.run(max_IO())
    except Exception as e:
        print(f"Critical error: {e}")
    finally:
        stop_run()  # Ensure Tektronix equipment stops
        save_measurements(f"E:\\{part_number}\\Windows\\Max IO\\{device.iProduct}.csv")
        backup_session(f"E:\\{part_number}\\Windows\\Max IO\\{device.iProduct}.png")
    
    completed_device_under_test = find_apricorn_device()
    if completed_device_under_test is not None:
        print(f"Remove Apricorn device to complete testing on {device.iProduct} ..")
    while completed_device_under_test is not None:
        completed_device_under_test = find_apricorn_device()
