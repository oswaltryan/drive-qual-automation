import os
from typing import Any

from . import benchmark, tektronix
from .usb_tool import find_apricorn_device

dut: Any | None = None
part_number = input("Enter the Apricorn Part Number: ")
device_configuration: int | None = None
device_type: str | None = None
print("")

acceptable_input = [1, 2]
device_type_map = [None, "Portables", "Secure Key"]
print("Available device types:")
print("                         1) Portables")
print("                         2) Secure Key")
print("")
while True:
    try:
        device_configuration = int(input("Choose a device type: "))
    except ValueError:
        continue

    if device_configuration not in acceptable_input:
        continue

    device_type = device_type_map[device_configuration]
    print(f"Chosen device type: {device_type}")
    break


async def in_rush() -> None:
    try:
        dut = find_apricorn_device()
        if dut is not None:
            print("Remove Apricorn device..")
        while dut is not None:
            dut = find_apricorn_device()

        tektronix.recall_setup(setup_type="InRush", device_type=device_type or "Portable")  # Initialize Tektronix equipment
        tektronix.mk_dir(
            os.path.join("C:\\", part_number, "Windows", "In Rush Current")
        )  # Create directory for In Rush Current results

        if dut is None:
            print("Unlock Apricorn device..")
        while dut is None:
            dut = find_apricorn_device()

    except Exception as e:
        print(f"Critical error: {e}")

    finally:
        if dut is None:
            raise RuntimeError("Device not detected for In Rush results.")
        tektronix.stop_run()  # Ensure Tektronix equipment stops
        tektronix.save_measurements(f"E:\\{part_number}\\Windows\\In Rush Current\\{dut.iProduct}.csv")
        tektronix.backup_session(f"E:\\{part_number}\\Windows\\In Rush Current\\{dut.iProduct}.png")


async def max_io() -> None:

    dut = find_apricorn_device()
    if dut is None:
        print("Unlock Apricorn device..")
    while dut is None:
        dut = find_apricorn_device()

    tektronix.recall_setup(setup_type="Max IO", device_type=device_type or "Portable")

    try:
        # Run read and write benchmarks
        if dut.driveLetter is None:
            raise RuntimeError("Drive letter not available for device.")
        write_ret = await benchmark.run_fio(dut.driveLetter, "write", 10, 100)
        read_ret = await benchmark.run_fio(dut.driveLetter, "read", 10, 100)

        # Cleanup test file
        test_file = os.path.join(dut.driveLetter, "benchmark_file.dat")
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

    except Exception as e:
        print(f"Critical error: {e}")

    finally:
        if dut is None:
            raise RuntimeError("Device not detected for Max IO results.")
        tektronix.stop_run()  # Ensure Tektronix equipment stops
        tektronix.save_measurements(f"E:\\{part_number}\\Windows\\Max IO\\{dut.iProduct}.csv")
        tektronix.backup_session(f"E:\\{part_number}\\Windows\\Max IO\\{dut.iProduct}.png")
        dut = find_apricorn_device()
        if dut is not None:
            print("Remove Apricorn device..")
        while dut is not None:
            dut = find_apricorn_device()
        print("")
    

def main() -> None:
    # in_rush()
    # max_io()
    return None


if __name__ == "__main__":
    main()
    
