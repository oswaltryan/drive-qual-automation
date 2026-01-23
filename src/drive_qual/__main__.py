import os

from . import benchmark, tektronix
from .usb_tool import ApricornDevice, find_apricorn_device

DEVICE_TYPE_OPTIONS = {
    1: "Portables",
    2: "Secure Key",
}

part_number = input("Enter the Apricorn Part Number: ")
print("")


def _select_device_type() -> str:
    print("Available device types:")
    print("                         1) Portables")
    print("                         2) Secure Key")
    print("")
    while True:
        try:
            selection = int(input("Choose a device type: "))
        except ValueError:
            continue

        device_type = DEVICE_TYPE_OPTIONS.get(selection)
        if device_type is None:
            continue

        print(f"Chosen device type: {device_type}")
        return device_type


def _wait_for_device_present(prompt: str) -> ApricornDevice:
    dut = find_apricorn_device()
    if dut is None:
        print(prompt)
    while dut is None:
        dut = find_apricorn_device()
    return dut


def _wait_for_device_removed(prompt: str) -> None:
    dut = find_apricorn_device()
    if dut is not None:
        print(prompt)
    while dut is not None:
        dut = find_apricorn_device()


def _cleanup_test_file(path: str) -> None:
    try:
        os.remove(path)
        print(f"\nCleaned up test file: {path}")
    except Exception as e:
        print(f"\nError cleaning up test file: {e}")


def _report_benchmark_results(write_ret: int, read_ret: int) -> None:
    if write_ret == 0 and read_ret == 0:
        print("\nBenchmark completed successfully")
    else:
        print(f"\nBenchmark failed - Write: {write_ret}, Read: {read_ret}")


async def _run_benchmarks(dut: ApricornDevice) -> None:
    if dut.driveLetter is None:
        raise RuntimeError("Drive letter not available for device.")
    write_ret = await benchmark.run_fio(dut.driveLetter, "write", 10, 100)
    read_ret = await benchmark.run_fio(dut.driveLetter, "read", 10, 100)

    test_file = os.path.join(dut.driveLetter, "benchmark_file.dat")
    _cleanup_test_file(test_file)
    _report_benchmark_results(write_ret, read_ret)


device_type = _select_device_type()


async def in_rush() -> None:
    dut: ApricornDevice | None = None
    try:
        _wait_for_device_removed("Remove Apricorn device..")

        tektronix.recall_setup(
            setup_type="InRush", device_type=device_type or "Portable"
        )  # Initialize Tektronix equipment
        tektronix.mk_dir(
            os.path.join("C:\\", part_number, "Windows", "In Rush Current")
        )  # Create directory for In Rush Current results

        dut = _wait_for_device_present("Unlock Apricorn device..")

    except Exception as e:
        print(f"Critical error: {e}")

    finally:
        if dut is None:
            raise RuntimeError("Device not detected for In Rush results.")
        tektronix.stop_run()  # Ensure Tektronix equipment stops
        tektronix.save_measurements(f"E:\\{part_number}\\Windows\\In Rush Current\\{dut.iProduct}.csv")
        tektronix.backup_session(f"E:\\{part_number}\\Windows\\In Rush Current\\{dut.iProduct}.png")


async def max_io() -> None:
    dut = _wait_for_device_present("Unlock Apricorn device..")

    tektronix.recall_setup(setup_type="Max IO", device_type=device_type or "Portable")

    try:
        await _run_benchmarks(dut)

    except Exception as e:
        print(f"Critical error: {e}")

    finally:
        if dut is None:
            raise RuntimeError("Device not detected for Max IO results.")
        tektronix.stop_run()  # Ensure Tektronix equipment stops
        tektronix.save_measurements(f"E:\\{part_number}\\Windows\\Max IO\\{dut.iProduct}.csv")
        tektronix.backup_session(f"E:\\{part_number}\\Windows\\Max IO\\{dut.iProduct}.png")
        _wait_for_device_removed("Remove Apricorn device..")
        print("")


def main() -> None:
    # in_rush()
    # max_io()
    return None


if __name__ == "__main__":
    main()
