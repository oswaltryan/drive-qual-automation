import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    from drive_qual.integrations.instruments.watlow import F4TController

    parser = argparse.ArgumentParser(description="Send simple SCPI commands to a Watlow F4T controller.")
    parser.add_argument("--ip", default=F4TController().ip)
    parser.add_argument("--timeout", type=float, default=F4TController().timeout_s)
    parser.add_argument("--write-hold-seconds", type=float, default=F4TController().write_hold_seconds)
    parser.add_argument("--query", help="Send a raw SCPI query and print the response.")
    parser.add_argument("--command", help="Send a raw SCPI command without reading a response.")
    parser.add_argument("--read-temp", action="store_true", help="Read process temperature.")
    parser.add_argument("--read-setpoint", action="store_true", help="Read loop 1 setpoint.")
    parser.add_argument("--read-snapshot", action="store_true", help="Read temperature and setpoint together.")
    parser.add_argument("--setpoint", type=float, help="Write loop 1 setpoint in Celsius.")
    args = parser.parse_args()

    controller = F4TController(
        ip=args.ip,
        timeout_s=args.timeout,
        write_hold_seconds=args.write_hold_seconds,
    )

    if args.query:
        print(controller.query(args.query))
        return
    if args.command:
        controller.command(args.command)
        print(f"Sent: {args.command}")
        return
    if args.read_temp:
        reading = controller.read_temperature()
        print(f"{reading.temperature_c:.3f} C / {reading.temperature_f:.3f} F")
        return
    if args.read_setpoint:
        print(f"{controller.read_setpoint_c():.3f} C")
        return
    if args.read_snapshot:
        snapshot = controller.read_snapshot()
        print(f"{snapshot.timestamp},{snapshot.temperature_c:.3f},{snapshot.temperature_f:.3f}")
        return
    if args.setpoint is not None:
        controller.write_setpoint_c(args.setpoint)
        print(f"Setpoint command sent: {args.setpoint:.3f} C")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
