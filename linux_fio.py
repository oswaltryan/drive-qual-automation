import asyncio
import shutil
import os
from tektronix import scpi_command, recall_setup, stop_run_and_capture_pdf, stop_run

# Verify fio is available on PATH
FIO_TOOL = shutil.which("fio")
if FIO_TOOL is None:
    raise FileNotFoundError("fio not found in PATH. Please install using 'sudo apt install fio'")

async def run_fio_benchmark(target_dir, test_type, size_mb, loops):
    """Run fio benchmark with specified parameters"""
    test_file = os.path.join(target_dir, "benchmark_file")
    cmd = [
        FIO_TOOL,
        "--name", f"{test_type}_test",
        "--filename", test_file,
        "--size", f"{size_mb}M",
        "--rw", test_type,
        "--direct", "1",
        "--ioengine", "libaio",
        "--bs", "4k",
        "--numjobs", "1",
        "--loops", str(loops),
        "--output-format", "normal"
    ]
    
    if test_type == "write":
        print(f"\nStarting write benchmark ({loops} passes, {size_mb}MB file)")
    else:
        print(f"\nStarting read benchmark ({loops} passes, {size_mb}MB file)")
    
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
    target_directory = "/mnt/benchmark"  # Update with your test directory
    recall_setup()  # Initialize Tektronix equipment
    
    # Run write benchmark
    write_ret = await run_fio_benchmark(target_directory, "write", 1000, 1000)
    # Run read benchmark
    read_ret = await run_fio_benchmark(target_directory, "read", 1000, 1000)
    
    # Cleanup test file
    test_file = os.path.join(target_directory, "benchmark_file")
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
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Critical error: {e}")
    finally:
        stop_run()  # Ensure Tektronix equipment stops