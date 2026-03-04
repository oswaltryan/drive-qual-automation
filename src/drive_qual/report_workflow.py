from __future__ import annotations

import argparse

from drive_qual.drive_info_prompt import run_drive_info_prompt
from drive_qual.equipment_prompt import run_equipment_prompt

STEP_ORDER: tuple[str, ...] = ("drive_info", "equipment")
STEPS = {
    "drive_info": run_drive_info_prompt,
    "equipment": run_equipment_prompt,
}


def run_report_workflow(steps: list[str] | None = None) -> None:
    selected = steps or list(STEP_ORDER)
    for step in selected:
        runner = STEPS.get(step)
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
        help="Comma-separated list of steps to run (default: drive_info,equipment).",
    )
    parser.add_argument(
        "--list-steps",
        action="store_true",
        help="List available steps and exit.",
    )
    args = parser.parse_args()

    if args.list_steps:
        print("Available steps:")
        for step in STEP_ORDER:
            print(f"  - {step}")
        return

    steps = _parse_steps(args.steps) if args.steps else list(STEP_ORDER)
    run_report_workflow(steps)


if __name__ == "__main__":
    run_report_workflow_cli()
