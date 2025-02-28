import asyncio
import shutil
import time
from tektronix import scpi_command, recall_setup

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

def stop_run_and_capture_pdf(pdf_filename):
    """
    Attempts to stop the Tektronix instrument run and capture its screen as a PDF.
    
    The commands below are examples:
      - 'ACQUIRE:STATE STOP' is used to freeze acquisition.
      - 'HARDCOPY:FORMAT PDF' sets the capture format.
      - 'HARDCOPY:DESTINATION INTERNAL' directs the file to be stored locally.
      - 'HARDCOPY:START' initiates the capture.
    
    Adjust these commands as per your instrument's SCPI reference.
    """
    # Stop the instrument's acquisition (alternative to RSTOP)
    scpi_command("ACQUIRE:STATE STOP")
    print("Acquisition stopped.")
    
    # Configure hardcopy capture to PDF and local destination.
    scpi_command("HARDCOPY:FORMAT PDF")
    scpi_command("HARDCOPY:DESTINATION INTERNAL")
    
    # Initiate the capture.
    scpi_command("HARDCOPY:START")
    print("Hardcopy capture initiated.")
    
    # Allow time for the capture to complete.
    time.sleep(5)
    
    print(f"Report captured and saved locally as {pdf_filename}")

async def main():
    target_volume = "DISK"  # Replace with your actual target volume
    # Recall setup on Tektronix (prompts for "Max IO" or "InRush")
    recall_setup()
    
    retcode = await run_disktester_sequential_suite(target_volume)
    if retcode == 0:
        print("Disktester sequential suite test completed successfully.")
    else:
        print(f"Disktester sequential suite test exited with code {retcode}.")
    
    # Stop the run and capture the report as a PDF.
    stop_run_and_capture_pdf("tek_report.pdf")

if __name__ == "__main__":
    asyncio.run(main())

