from __future__ import annotations

import os

from drive_qual import benchmarks as benchmark
from drive_qual.core.io_utils import mk_dir
from drive_qual.core.storage_paths import artifact_dir, artifact_file
from drive_qual.integrations.apricorn.usb_cli import ApricornDevice, find_apricorn_device
from drive_qual.integrations.instruments import tektronix

DEVICE_TYPE_OPTIONS = {
    1: "Portables",
    2: "Secure Key",
}


def _prompt_part_number() -> str:
    return input("Enter the Apricorn Part Number: ")


def _device_type_for_scope_name(product_name: str | None) -> str:
    product = (product_name or "").strip().lower()
    if "dt" in product:
        return "DT"
    return "generic"


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


def _report_benchmark_results(return_code: int) -> None:
    if return_code == 0:
        print("\nBenchmark completed successfully")
    else:
        print(f"\nBenchmark failed - Return code: {return_code}")


async def _run_benchmarks(dut: ApricornDevice) -> None:
    if dut.driveLetter is None:
        raise RuntimeError("Drive letter not available for device.")
    benchmark_ret = await benchmark.run_fio(dut.driveLetter, runtime_seconds=300)

    test_file = benchmark.benchmark_file_path(dut.driveLetter, "benchmark_file.dat")
    _cleanup_test_file(test_file)
    _report_benchmark_results(benchmark_ret)


async def in_rush() -> None:
    part_number = _prompt_part_number()
    device_type = _select_device_type()
    dut: ApricornDevice | None = None
    try:
        _wait_for_device_removed("Remove Apricorn device..")

        tektronix.recall_setup(setup_type="InRush", device_type=_device_type_for_scope_name(device_type))
        mk_dir(artifact_dir(part_number, "Windows", "In Rush Current"))

        dut = _wait_for_device_present("Unlock Apricorn device..")

    except Exception as e:
        print(f"Critical error: {e}")

    finally:
        if dut is None:
            raise RuntimeError("Device not detected for In Rush results.")
        tektronix.stop_run()
        tektronix.save_measurements(artifact_file(part_number, "Windows", "In Rush Current", f"{dut.iProduct}.csv"))
        tektronix.backup_session(artifact_file(part_number, "Windows", "In Rush Current", f"{dut.iProduct}.png"))


async def max_io() -> None:
    part_number = _prompt_part_number()
    device_type = _select_device_type()
    dut = _wait_for_device_present("Unlock Apricorn device..")

    tektronix.recall_setup(setup_type="Max IO", device_type=_device_type_for_scope_name(device_type))

    try:
        await _run_benchmarks(dut)

    except Exception as e:
        print(f"Critical error: {e}")

    finally:
        tektronix.stop_run()
        tektronix.save_measurements(artifact_file(part_number, "Windows", "Max IO", f"{dut.iProduct}.csv"))
        tektronix.backup_session(artifact_file(part_number, "Windows", "Max IO", f"{dut.iProduct}.png"))
        _wait_for_device_removed("Remove Apricorn device..")
        print("")


def main() -> None:
    return None


if __name__ == "__main__":
    main()
