from __future__ import annotations

import argparse
from collections.abc import Callable

from drive_qual.drive_info_prompt import run_drive_info_prompt
from drive_qual.equipment_prompt import run_equipment_prompt
from drive_qual.power_measurements_step import run_power_measurements_step


STEP_ORDER: tuple[str, ...] = ("drive_info", "equipment", "power_measurements")
StepRunner = Callable[[], None]


def run_report_workflow(
    steps: list[str] | None = None,
    *,
    part_number: str | None = None,
    scope_profile: str | None = None,
) -> None:
    selected = steps or list(STEP_ORDER)
    step_runners: dict[str, StepRunner] = {
        "drive_info": run_drive_info_prompt,
        "equipment": lambda: run_equipment_prompt(part_number=part_number, scope_profile=scope_profile),
        "power_measurements": run_power_measurements_step,
    }
    for step in selected:
        runner = step_runners.get(step)
        if runner is None:
            raise ValueError(f"Unknown workflow step: {step}")
        runner()


def _parse_steps(raw: str) -> list[str]:
    steps = [item.strip() for item in raw.split(",") if item.strip()]
    if not steps:
        raise ValueError("At least one workflow step is required.")
    return steps


def run_report_workflow_cli() -> None:
    parser = argparse.ArgumentParser(description="Run drive qualification report workflow steps.")
    parser.add_argument(
        "--steps",
        help="Comma-separated list of steps to run (default: drive_info,equipment,power_measurements).",
    )
    parser.add_argument(
        "--list-steps",
        action="store_true",
        help="List available steps and exit.",
    )
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--scope-profile", help="Apply a scope/probe profile (e.g., tektronix, rigol).")
    args = parser.parse_args()

    if args.list_steps:
        print("Available steps:")
        for step in STEP_ORDER:
            print(f"  - {step}")
        return

    steps = _parse_steps(args.steps) if args.steps else list(STEP_ORDER)
    run_report_workflow(steps, part_number=args.part_number, scope_profile=args.scope_profile)


if __name__ == "__main__":
    run_report_workflow_cli()
