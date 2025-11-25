import os
import sys
import time
from pathlib import Path

# --- Import your updated library ---
try:
    from tektronix import save_measurements, stop_run
except ImportError:
    print("Error: Could not find 'tektronix.py'. Ensure it is in this directory.")
    sys.exit(1)

def test_tcp_copy():
    print("--- Testing Tektronix TCP File Transfer ---")

    # 1. Define a local path on the HOST machine
    # We use the current directory so you can see it immediately
    current_dir = Path.cwd()
    filename = "tcp_transfer_test.csv"
    destination_path = current_dir / filename

    print(f"Destination Path: {destination_path}")

    # 2. Clean up previous test runs
    if destination_path.exists():
        try:
            destination_path.unlink()
            print(" -> Deleted old test file from previous run.")
        except PermissionError:
            print(" -> Error: Could not delete old file. Check permissions.")
            return

    # 3. Execute the Transfer
    try:
        print(" -> Sending STOP command to Scope...")
        stop_run() # Usually required before saving data
        
        print(" -> Requesting file transfer (save_measurements)...")
        start_time = time.time()
        
        # Pass the full string path to the host machine
        save_measurements(str(destination_path))
        
        duration = time.time() - start_time
        print(f" -> Command execution took {duration:.2f} seconds.")

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Hardware communication failed: {e}")
        return

    # 4. Verify the file arrived
    if destination_path.exists():
        size_bytes = destination_path.stat().st_size
        size_kb = size_bytes / 1024
        
        if size_bytes > 0:
            print(f"\n[SUCCESS] File transferred successfully!")
            print(f" - Location: {destination_path}")
            print(f" - Size: {size_kb:.2f} KB")
        else:
            print(f"\n[WARNING] File created but is empty (0 bytes).")
    else:
        print(f"\n[FAILURE] File was NOT found at: {destination_path}")
        print("Possible causes:")
        print("1. Network timeout/Socket error")
        print("2. Path string formatting issues")
        print("3. Oscilloscope side error")

if __name__ == "__main__":
    test_tcp_copy()