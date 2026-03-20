import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from drive_qual.integrations.apricorn import usb_cli as apricorn_usb_cli


def main() -> int:
    payload = apricorn_usb_cli.get_usb_payload()
    if payload is None:
        print("usb --json did not return parseable JSON.")
        return 1

    device = apricorn_usb_cli.find_apricorn_device()
    if device is None:
        print("Apricorn device not detected by wrapper.")
        return 0

    print(json.dumps(asdict(device), indent=2))
    print("\nDevice snapshot:")
    print(f"  iProduct: {device.iProduct}")
    print(f"  iSerial: {device.iSerial}")
    print(f"  bcdDevice: {device.bcdDevice}")
    print(f"  scbPartNumber: {device.scbPartNumber}")
    print(f"  mcuFW: {device.mcuFW}")
    print(f"  driveLetter: {device.driveLetter}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
