from __future__ import annotations

import argparse
from collections.abc import Callable

STEP_ORDER: tuple[str, ...] = ("drive_info", "equipment", "power_measurements", "performance")
StepRunner = Callable[[], None]


def _run_drive_info_step() -> None:
    from drive_qual.workflows.drive_info import run_drive_info_prompt

    run_drive_info_prompt()


def _run_equipment_step(part_number: str | None = None, scope_profile: str | None = None) -> None:
    from drive_qual.workflows.equipment import run_equipment_prompt

    run_equipment_prompt(part_number=part_number, scope_profile=scope_profile)


def _run_power_measurements_step() -> None:
    from drive_qual.platforms.windows.power_measurements import run_power_measurements_step

    run_power_measurements_step()


def _run_performance_step(part_number: str | None = None) -> None:
    from drive_qual.platforms.windows.performance import run_software_step

    run_software_step(part_number=part_number)


def run_report_workflow(
    steps: list[str] | None = None,
    *,
    part_number: str | None = None,
    scope_profile: str | None = None,
) -> None:
    selected = steps or list(STEP_ORDER)
    step_runners: dict[str, StepRunner] = {
        "drive_info": _run_drive_info_step,
        "equipment": lambda: _run_equipment_step(part_number=part_number, scope_profile=scope_profile),
        "power_measurements": _run_power_measurements_step,
        "performance": lambda: _run_performance_step(part_number=part_number),
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
