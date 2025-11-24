import asyncio
import shutil
import os
import time
import sys
from pathlib import Path

import setup_directories
from tektronix import *
from usb_tool import find_apricorn_device

# --- Configuration ---
# Verify fio is available on PATH
FIO_TOOL = shutil.which("fio.exe")

# Global Hardware State
current_device = None
dut_type = None

def dut_enumeration(unlock_dut=True):
    global current_device, dut_type
    if unlock_dut:
        print("Waiting for Apricorn device...")
        while current_device is None:
            current_device = find_apricorn_device()
            time.sleep(1)
        
        if hasattr(current_device, 'iProduct') and current_device.iProduct == "Secure Key 3.0":
            dut_type = "Secure Key"
        else:
            dut_type = "Portable"
        print(f"Device Initialized: {getattr(current_device, 'iProduct', 'Unknown')}")
    else:
        current_device = find_apricorn_device()
        if current_device is not None:
            print("Please Remove/Lock Apricorn device...")
        while current_device is not None:
            current_device = find_apricorn_device()
            time.sleep(1)
        print("Device removed/locked.")

async def run_fio_benchmark(target_dir_path, test_type, size_mb, loops):
    if FIO_TOOL is None:
        raise FileNotFoundError("fio.exe not found in PATH.")

    test_file = target_dir_path / "benchmark_file.dat"
    
    cmd = [
        FIO_TOOL,
        "--name", f"{test_type}_test",
        "--filename", str(test_file),
        "--size", f"{size_mb}m",
        "--rw", test_type,
        "--ioengine", "windowsaio",
        "--buffered", "0",
        "--bs", "4k",
        "--numjobs", "1",
        "--loops", str(loops),
        "--output-format", "normal"
    ]
    
    print(f"\nStarting {test_type} benchmark ({loops} passes)...")
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if stdout: print(stdout.decode().strip())
    if stderr: print(stderr.decode().strip())
    
    return process.returncode

async def main_test_sequence():
    # =========================================
    # STEP 1: UTILIZE SETUP SCRIPT
    # =========================================
    # This handles OS check, Drive detection, and Project Folder selection
    try:
        drive_root, project_path = setup_directories.data_drive_setup()
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return

    # =========================================
    # STEP 2: HARDWARE ENUMERATION
    # =========================================
    dut_enumeration(unlock_dut=True)

    # =========================================
    # STEP 3: RUN MAX I/O
    # =========================================
    try:
        print("\n--- Starting Max IO Test ---")
        # Use paths from Step 1
        result_dir = project_path / "Windows" / "Max IO"
        recall_setup(setup_type="Max IO")
        
        # Run FIO on the drive root
        w_ret = await run_fio_benchmark(drive_root, "write", 10, 100)
        r_ret = await run_fio_benchmark(drive_root, "read", 10, 100)
        
        # Cleanup
        (drive_root / "benchmark_file.dat").unlink(missing_ok=True)
        
        # Save Tektronix Data
        dev_name = getattr(current_device, 'iProduct', 'Unknown_Device')
        stop_run()
        save_measurements(str(result_dir / f"{dev_name}.csv"))
        backup_session(str(result_dir / f"{dev_name}.png"))
        
        # Update Tracker using setup_directories library
        if w_ret == 0 and r_ret == 0:
            setup_directories.update_progress(project_path, "Windows", "Max I/O PDF", True)
            
    except Exception as e:
        print(f"Critical Error in Max IO: {e}")

    # =========================================
    # STEP 4: RUN IN-RUSH CURRENT
    # =========================================
    print("\nResetting device for In-Rush test...")
    dut_enumeration(unlock_dut=False) # Force user to remove/lock
    
    try:
        print("\n--- Starting In-Rush Current Test ---")
        result_dir = project_path / "Windows" / "In Rush Current"
        
        recall_setup(setup_type="InRush", device_type=dut_type)
        time.sleep(3)
        
        # Trigger measurement by unlocking
        dut_enumeration(unlock_dut=True)
        
        # Save Data
        dev_name = getattr(current_device, 'iProduct', 'Unknown_Device')
        stop_run()
        save_measurements(str(result_dir / f"{dev_name}.csv"))
        backup_session(str(result_dir / f"{dev_name}.png"))
        
        setup_directories.update_progress(project_path, "Windows", "In-Rush PDF", True)
        
    except Exception as e:
        print(f"Critical Error in In-Rush: {e}")
    
    print("\nTest Suite Completed.")

if __name__ == "__main__":
    try:
        asyncio.run(main_test_sequence())
    except KeyboardInterrupt:
        stop_run()
        print("\nAborted by user.")