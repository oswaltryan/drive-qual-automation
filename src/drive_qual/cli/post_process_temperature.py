from __future__ import annotations

import argparse
from pathlib import Path

from drive_qual.cli.interrupts import run_cli_with_interrupt_handling
from drive_qual.workflows.temperature import post_process_temperature_data


def run_temperature_post_process_cli() -> int:
    return run_cli_with_interrupt_handling(_run_temperature_post_process_cli)


def _run_temperature_post_process_cli() -> None:
    parser = argparse.ArgumentParser(description="Update report JSON and artifacts with temperature test data.")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--dut", help="Report DUT name to update. If omitted, the report DUT selector is used.")
    parser.add_argument(
        "--csv",
        type=Path,
        help="CSV containing matched temperature/performance rows.",
    )
    parser.add_argument(
        "--chart",
        type=Path,
        help="Custom temperature chart PNG to copy into the report artifact folder.",
    )
    parser.add_argument("--title", default="Temperature vs Speed", help="Title for the generated temperature chart.")
    args = parser.parse_args()

    if args.csv is None and args.chart is None:
        parser.error("At least one of --csv or --chart is required.")

    post_process_temperature_data(
        part_number=args.part_number,
        dut_name=args.dut,
        performance_csv=args.csv,
        chart=args.chart,
        chart_title=args.title,
    )


if __name__ == "__main__":
    raise SystemExit(run_temperature_post_process_cli())
