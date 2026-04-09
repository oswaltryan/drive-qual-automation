from __future__ import annotations

import argparse
from collections.abc import Callable

from drive_qual.workflows.orchestrator import (
    WORKFLOW_PROFILES,
    execute_orchestrated_workflow,
    resolve_selected_steps,
)

STEP_ORDER: tuple[str, ...] = ("drive_info", "equipment", "power_measurements", "performance")
StepRunner = Callable[[], None]


def _default_steps() -> tuple[str, ...]:
    return STEP_ORDER


def _run_drive_info_step() -> None:
    from drive_qual.workflows.drive_info import run_drive_info_prompt

    run_drive_info_prompt()


def _run_equipment_step(part_number: str | None = None, scope_profile: str | None = None) -> None:
    from drive_qual.workflows.equipment import run_equipment_prompt

    run_equipment_prompt(part_number=part_number, scope_profile=scope_profile)


def _run_power_measurements_step() -> None:
    from drive_qual.platforms.power_measurements import run_power_measurements_step

    run_power_measurements_step()


def _run_performance_step(part_number: str | None = None) -> None:
    from drive_qual.platforms.performance import run_software_step

    run_software_step(part_number=part_number)


def run_report_workflow(
    steps: list[str] | None = None,
    *,
    part_number: str | None = None,
    scope_profile: str | None = None,
    profile: str | None = None,
    resume: bool = False,
) -> None:
    selected = resolve_selected_steps(
        explicit_steps=steps,
        default_steps=_default_steps(),
        profile=profile,
    )
    step_runners: dict[str, StepRunner] = {
        "drive_info": _run_drive_info_step,
        "equipment": lambda: _run_equipment_step(part_number=part_number, scope_profile=scope_profile),
        "power_measurements": _run_power_measurements_step,
        "performance": lambda: _run_performance_step(part_number=part_number),
    }
    for step in selected:
        if step not in step_runners:
            raise ValueError(f"Unknown workflow step: {step}")
    execute_orchestrated_workflow(
        selected_steps=selected,
        step_runners=step_runners,
        profile=profile,
        part_number=part_number,
        resume=resume,
    )


def _parse_steps(raw: str) -> list[str]:
    steps = [item.strip() for item in raw.split(",") if item.strip()]
    if not steps:
        raise ValueError("At least one workflow step is required.")
    return steps


def run_report_workflow_cli() -> None:
    parser = argparse.ArgumentParser(description="Run drive qualification report workflow steps.")
    parser.add_argument(
        "--steps",
        help="Comma-separated list of steps to run (default: drive_info,equipment,power_measurements,performance).",
    )
    parser.add_argument(
        "--list-steps",
        action="store_true",
        help="List available steps and exit.",
    )
    parser.add_argument(
        "--profile",
        help="Run a named workflow profile (for example: core_perf_v1).",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available workflow profiles and exit.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a prior profiled run from workflow_run_manifest.json.",
    )
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--scope-profile", help="Apply a scope/probe profile (e.g., tektronix, rigol).")
    args = parser.parse_args()

    if args.list_steps:
        print("Available steps:")
        for step in STEP_ORDER:
            print(f"  - {step}")
        return

    if args.list_profiles:
        print("Available profiles:")
        for profile_name in sorted(WORKFLOW_PROFILES):
            print(f"  - {profile_name}")
        return

    steps = _parse_steps(args.steps) if args.steps else None
    run_report_workflow(
        steps,
        part_number=args.part_number,
        scope_profile=args.scope_profile,
        profile=args.profile,
        resume=args.resume,
    )


if __name__ == "__main__":
    run_report_workflow_cli()
