import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drive_qual import watlow  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Watlow Modbus RTU smoke test.")
    parser.add_argument("--port", default=watlow.PORT)
    parser.add_argument("--baudrate", type=int, default=watlow.BAUDRATE)
    parser.add_argument("--bytesize", type=int, default=watlow.BYTESIZE)
    parser.add_argument("--parity", default=watlow.PARITY, choices=["N", "E", "O"])
    parser.add_argument("--stopbits", type=int, default=watlow.STOPBITS, choices=[1, 2])
    parser.add_argument("--unit-id", type=int, default=watlow.UNIT_ID)
    parser.add_argument("--timeout", type=float, default=watlow.TIMEOUT_S)
    parser.add_argument("--retries", type=int, default=watlow.RETRIES)
    parser.add_argument("--address-offset", type=int, default=0)
    parser.add_argument("--word-order", default=watlow.WORD_ORDER, choices=["low-high", "high-low"])
    args = parser.parse_args()

    settings = watlow.SerialSettings(
        baudrate=args.baudrate,
        bytesize=args.bytesize,
        parity=args.parity,
        stopbits=args.stopbits,
        timeout_s=args.timeout,
        retries=args.retries,
    )
    with watlow.watlow_client(port=args.port, settings=settings) as client:
        values = watlow.read_default_assembly_by_name(
            client,
            unit_id=args.unit_id,
            address_offset=args.address_offset,
        )

    for key in (
        "Set Point",
        "Analog Input 1",
        "Heat Power",
        "Cool Power",
        "Control Mode Active",
    ):
        value = values.get(key)
        if value is None:
            print(f"{key}: <missing>")
            continue
        print(
            f"{key}: raw={value.word1},{value.word2} "
            f"u32={value.as_u32(word_order=args.word_order)} "
            f"f32={value.as_f32(word_order=args.word_order)}"
        )


if __name__ == "__main__":
    main()
