#digi.py 

import asyncio import shutil import time from tektronix import scpi_command, recall_setup, stop_run_and_capture_pdf, stop_run

# Ensure disktester is available on PATH.
DISKTESTER_TOOL = shutil.which("disktester")
if DISKTESTER_TOOL is None:
    raise FileNotFoundError("disktester not found in PATH. Please verify installation.")

async def run_disktester_sequential_suite(target_volume):
    """
    Runs the 'run-sequential-suite' command on the target volume.
    Command: disktester run-sequential-suite --iterations 3 --test-size 4G DISK
    """
    cmd = [
        DISKTESTER_TOOL,
        "run-sequential-suite",
        "--iterations", "3",
        "--test-size", "4G",
        target_volume
    ]
    print("Starting disktester run-sequential-suite test...")
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


async def main():
    target_volume = "DISK"  # Replace with your actual target volume
    # Recall setup on Tektronix (prompts for "Max IO" or "InRush")
    recall_setup()
    
    retcode = await run_disktester_sequential_suite(target_volume)
    if retcode == 0:
        print("Disktester sequential suite test completed successfully.")
    else:
        print(f"Disktester sequential suite test exited with code {retcode}.")
    

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error encountered: {e}")
    finally:
        stop_run() 
