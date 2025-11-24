import asyncio
import shutil
import os
import time
from pathlib import Path

# --- Import Custom Libraries ---
import setup_directories
import tektronix
from usb_tool import find_apricorn_device

# --- Global State ---
current_device = None
dut_type = None

# Verify fio is available on PATH (Windows version)
FIO_TOOL = shutil.which("fio.exe")
if FIO_TOOL is None:
    raise FileNotFoundError(
        "fio not found in PATH. Download from https://bsdio.com/fio/ and add to system PATH"
    )

def dut_enumeration(unlock_dut=True):
    global current_device, dut_type
    if unlock_dut:
        print("Waiting for Apricorn device...")
        while current_device == None:
            current_device = find_apricorn_device()
            time.sleep(1)
            
        if hasattr(current_device, 'iProduct') and current_device.iProduct == "Secure Key 3.0":
            dut_type = "Secure Key"
        else:
            dut_type = "Portable"
        print(f"Found device: {getattr(current_device, 'iProduct', 'Unknown Device')}")
    else:
        current_device = find_apricorn_device()
        if current_device != None:
            print("Please Remove/Lock Apricorn device...")
            
        while current_device != None:
            current_device = find_apricorn_device()
            time.sleep(1)
        print("Device removed/locked.")

async def run_fio_benchmark(target_dir, test_type, size_mb, loops):
    """Run fio benchmark with Windows-specific parameters"""
    test_file = target_dir / "benchmark_file.dat"
    
    # Convert path to string for arguments
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

async def main_test_sequence():
    global current_device, dut_type
    
    # ---------------------------------------------------------
    # STEP 1: HOST SETUP (Runs on PC)
    # ---------------------------------------------------------
    # This sets up the JSON and folders on the Apricorn Drive attached to the PC
    try:
        host_drive_root, host_project_path, project_name = setup_directories.data_drive_setup()
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return

    print(f"\nActive Project: {project_name}")
    print(f"Host Path: {host_project_path}")

    # ---------------------------------------------------------
    # STEP 2: SCOPE SETUP (Runs on Tektronix via Network)
    # ---------------------------------------------------------
    # This finds the USB drive attached to the SCOPE and creates matching folders
    print("\n--- Configuring Tektronix Scope ---")
    try:
        scope_drive_letter = tektronix.detect_scope_drive()
        
        # Create folder structure on Scope: Drive:/ProjectName/Windows
        scope_project_base = tektronix.ensure_scope_directory_structure(
            scope_drive_letter, 
            project_name, 
            ["Windows"]
        )
        print(f"Scope Target Path: {scope_project_base}")
        
    except Exception as e:
        print(f"CRITICAL ERROR: Could not configure Scope storage: {e}")
        return

    # ---------------------------------------------------------
    # STEP 3: EXECUTE TESTS
    # ---------------------------------------------------------
    
    # Ensure device is connected to Host
    dut_enumeration(unlock_dut=True)

    # --- TEST 1: MAX IO ---
    try:
        print("\n=== Starting Max IO Test ===")
        
        # 1. Setup Hardware
        tektronix.recall_setup(setup_type="Max IO")
        
        # 2. Run Traffic on HOST (The Apricorn Drive)
        write_ret = await run_fio_benchmark(host_drive_root, "write", 10, 100)
        read_ret = await run_fio_benchmark(host_drive_root, "read", 10, 100)
        
        # 3. Cleanup Host File
        test_file = host_drive_root / "benchmark_file.dat"
        try:
            if test_file.exists():
                test_file.unlink()
                print(f"Cleaned up test file.")
        except Exception as e:
            print(f"Error cleaning up test file: {e}")
        
        # 4. Save Scope Data to SCOPE Storage
        device_name = getattr(current_device, 'iProduct', 'Unknown_Device')
        
        # Note: We construct string paths for the Scope
        scope_save_dir = f"{scope_project_base}/Windows/Max IO"
        csv_path = f"{scope_save_dir}/{device_name}.csv"
        png_path = f"{scope_save_dir}/{device_name}.png"
        
        tektronix.stop_run()
        tektronix.save_measurements(csv_path)
        tektronix.backup_session(png_path)
        
        # 5. Update Tracker on HOST
        if write_ret == 0 and read_ret == 0:
            print("\nMax IO Benchmark successfully recorded.")
            setup_directories.update_progress(host_project_path, "Windows", "Max I/O PDF", True)
        else:
            print(f"\nBenchmark failed - Write: {write_ret}, Read: {read_ret}")
            
    except Exception as e:
        print(f"Critical error in Max IO: {e}")

    # --- TEST 2: IN RUSH CURRENT ---
    try:
        print("\n=== Starting In-Rush Current Test ===")
        
        # 1. Reset Device (Lock/Remove)
        print("Resetting device for In-Rush test...")
        dut_enumeration(unlock_dut=False)

        # 2. Setup Hardware
        tektronix.recall_setup(setup_type="InRush", device_type=dut_type)
        print("Scope armed. Waiting 3 seconds...")
        time.sleep(3)
        
        # 3. Trigger Scope (Unlock Device)
        dut_enumeration(unlock_dut=True)
        
        # 4. Save Scope Data to SCOPE Storage
        device_name = getattr(current_device, 'iProduct', 'Unknown_Device')
        scope_save_dir = f"{scope_project_base}/Windows/In Rush Current"
        csv_path = f"{scope_save_dir}/{device_name}.csv"
        png_path = f"{scope_save_dir}/{device_name}.png"
        
        tektronix.stop_run()
        tektronix.save_measurements(csv_path)
        tektronix.backup_session(png_path)
        
        # 5. Update Tracker on HOST
        setup_directories.update_progress(host_project_path, "Windows", "In-Rush PDF", True)
        print("In-Rush test complete.")

    except Exception as e:
        print(f"Critical error in In-Rush: {e}")

    print("\n--- All Tests Finished ---")
    # Final cleanup / Lock
    dut_enumeration(unlock_dut=False)

if __name__ == "__main__":
    try:
        asyncio.run(main_test_sequence())
    except KeyboardInterrupt:
        tektronix.stop_run()
        print("\nAborted by user.")
        sys.exit(0)