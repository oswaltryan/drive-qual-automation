import asyncio
import shutil
import os
from tektronix import *
from windows_usb import *
import time
from pprint import pprint

part_number = input("Enter the Apricorn P/N for this drive: ")
device = None
dut_type = None

# Verify fio is available on PATH (Windows version)
FIO_TOOL = shutil.which("fio.exe")
if FIO_TOOL is None:
    raise FileNotFoundError(
        "fio not found in PATH. Download from https://bsdio.com/fio/ "
        "and add to system PATH"
    )

async def run_fio_benchmark(target_dir, test_type, size_mb, loops):
    """Run fio benchmark with Windows-specific parameters"""
    test_file = os.path.join(target_dir, "benchmark_file.dat")
    cmd = [
        FIO_TOOL,
        "--name", f"{test_type}_test",
        "--filename", test_file,
        "--size", f"{size_mb}m",
        "--rw", test_type,
        "--ioengine", "windowsaio",  # Windows-specific I/O engine
        "--buffered", "0",  # Use non-buffered I/O
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

async def in_rush_current():
    global device, dut_type
    target_directory = "E"  # Update with your test directory
    recall_setup(setup_type="InRush", device_type=dut_type)  # Initialize Tektronix equipment
    mk_dir(os.path.join(f"E:\\", part_number, "Windows", "In Rush Current")) # Create directory for In Rush Current results
    
    # Create test directory if it doesn't exist
    os.makedirs(target_directory, exist_ok=True)

    print("Unlock Apricorn device..")
    while device == None:
        device = find_apricorn_device()

    if device.iProduct == "Secure Key 3.0":
        dut_type = "Secure Key"
    else:
        dut_type = "Portable"

    time.sleep(3)

async def max_IO():
    target_directory = "E"  # Update with your test directory
    recall_setup(setup_type="Max IO")  # Initialize Tektronix equipment
    mk_dir(os.path.join(f"E:\\", part_number, "Windows", "Max IO")) # Create path for Max IO results
    
    # Create test directory if it doesn't exist
    os.makedirs(target_directory, exist_ok=True)
    
    # Run write benchmark
    write_ret = await run_fio_benchmark(target_directory, "write", 10, 10)
    # Run read benchmark
    read_ret = await run_fio_benchmark(target_directory, "read", 10, 10)
    
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
    print("Unlock Apricorn device..")
    get_device = None
    while get_device == None:
        get_device = find_apricorn_device()

    if get_device.iProduct == "Secure Key 3.0":
        dut_type = "Secure Key"
    else:
        dut_type = "Portable"
    print(f"Found device: {get_device.iProduct}")
    
    device_under_test = find_apricorn_device()
    if device_under_test != None:
        print("Remove Apricorn device to start In-Rush test..")
    while device_under_test != None:
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
    if completed_device_under_test != None:
        print(f"Remove Apricorn device to complete testing on {device.iProduct} ..")
    while completed_device_under_test != None:
        completed_device_under_test = find_apricorn_device()

