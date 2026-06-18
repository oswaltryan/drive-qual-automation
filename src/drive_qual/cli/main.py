from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

STEP_ALIASES: dict[str, str] = {
    "info": "drive_info",
    "drive-info": "drive_info",
    "drive_info": "drive_info",
    "equipment": "equipment",
    "equip": "equipment",
    "power": "power_measurements",
    "power-measurements": "power_measurements",
    "power_measurements": "power_measurements",
    "perf": "performance",
    "performance": "performance",
    "usbif": "usb_if",
    "usb-if": "usb_if",
    "usb_if": "usb_if",
    "temp": "temperature",
    "temperature": "temperature",
    "reliability": "reliability",
    "reliable": "reliability",
    "disk-tester": "reliability",
    "disk_tester": "reliability",
}

MAN_PAGE = """Drive Qualification Automation

Usage:
  drive-qual
  drive-qual <command> [options]

Technician workflow:
  drive-qual start --part-number 69-420
  drive-qual step equipment --part-number 69-420
  drive-qual step power --part-number 69-420
  drive-qual step performance --part-number 69-420
  drive-qual step temperature --part-number 69-420
  drive-qual step reliability --part-number 69-420
  drive-qual report --part-number 69-420

Commands:
  start             Start a new report session by collecting drive info.
  run               Run the maintained workflow steps in order.
  resume            Resume a profiled workflow run.
  step <name>       Run one workflow step.
  report            Generate the Word report from the current report JSON.
  temperature       Post-process temperature CSV/chart artifacts.
  status            Show the active session and report path.
  list-steps        Show workflow step names and friendly aliases.
  list-profiles     Show orchestrated workflow profiles.
  legacy            Run the old Windows-focused legacy entrypoint.

Step names and options:
  info              drive_info
                    --part-number PN
  equipment         equipment
                    --part-number PN, --scope-profile NAME
  power             power_measurements
                    --part-number PN
  performance       performance
                    --part-number PN
  usbif            usb_if
                    --part-number PN
  temperature       temperature
                    --part-number PN
                    For non-interactive temperature inputs, use:
                    drive-qual temperature --part-number PN --dut NAME --csv PATH [--chart PATH] [--title TEXT]
  reliability       reliability
                    --part-number PN
                    Runs disk_tester.exe on Windows until at least 3 passes are recorded.
                    Existing Z:\\PN\\Windows\\Reliability\\PN_reliability.log summaries are reused.
                    If no report-folder log exists, local disk_test.log candidates are offered.

Common options:
  --part-number PN  Select the report/artifact folder.
  --profile NAME    Select an orchestrated workflow profile.

Examples:
  uv run drive-qual
  uv run drive-qual start --part-number 69-420
  uv run drive-qual run --part-number 69-420
  uv run drive-qual resume --profile core_perf_temp_v1 --part-number 69-420
  uv run drive-qual step power --part-number 69-420
  uv run drive-qual step usbif --part-number 69-420
  uv run drive-qual step reliability --part-number 69-420
  uv run drive-qual report --part-number 69-420
  uv run drive-qual temperature --part-number 69-420 --dut "Padlock DT" --csv matched.csv
"""


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or any(arg in {"-h", "--help"} for arg in args):
        print(MAN_PAGE)
        return

    command = args.pop(0).casefold()
    commands: dict[str, Callable[[list[str]], None]] = {
        "start": _run_start,
        "run": lambda command_args: _run_workflow(command_args, resume=False),
        "resume": lambda command_args: _run_workflow(command_args, resume=True),
        "step": _run_step,
        "report": _run_report,
        "temperature": _run_temperature,
        "temp": _run_temperature,
        "status": _run_status,
        "list-steps": lambda _command_args: _run_list_steps(),
        "list-profiles": lambda _command_args: _run_list_profiles(),
        "legacy": lambda _command_args: _run_legacy(),
    }
    runner = commands.get(command)
    if runner is None:
        _die(f"Unknown command: {command}")
    runner(args)


def _run_start(args: list[str]) -> None:
    parser = _parser("drive-qual start")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parsed = parser.parse_args(args)

    from drive_qual.workflows.report import run_report_workflow

    run_report_workflow(["drive_info"], part_number=parsed.part_number)


def _run_workflow(args: list[str], *, resume: bool) -> None:
    parser = _parser("drive-qual resume" if resume else "drive-qual run")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--profile", default="default", help="Workflow profile to run.")
    parser.add_argument("--scope-profile", help="Apply a scope/probe profile during equipment setup.")
    parsed = parser.parse_args(args)

    from drive_qual.workflows.report import run_report_workflow

    run_report_workflow(
        part_number=parsed.part_number,
        profile=parsed.profile,
        resume=resume,
        scope_profile=parsed.scope_profile,
    )


def _run_step(args: list[str]) -> None:
    parser = _parser("drive-qual step")
    parser.add_argument("name", help="Step name or alias.")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--scope-profile", help="Apply a scope/probe profile during equipment setup.")
    parsed = parser.parse_args(args)

    step_name = STEP_ALIASES.get(parsed.name.casefold())
    if step_name is None:
        _die(f"Unknown step: {parsed.name}")

    from drive_qual.workflows.report import run_report_workflow

    run_report_workflow(
        [step_name],
        part_number=parsed.part_number,
        scope_profile=parsed.scope_profile,
    )


def _run_report(args: list[str]) -> None:
    parser = _parser("drive-qual report")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--source-root", type=Path, help="Root containing the per-part-number report folder.")
    parser.add_argument("--output", type=Path, help="Output .docx path.")
    parsed = parser.parse_args(args)

    from drive_qual.reports.generate import generate_report_docx

    output_path = generate_report_docx(
        part_number=parsed.part_number,
        source_root=parsed.source_root,
        output=parsed.output,
    )
    print(f"Generated Word report at {output_path}")


def _run_temperature(args: list[str]) -> None:
    parser = _parser("drive-qual temperature")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--dut", help="Report DUT name to update.")
    parser.add_argument("--csv", type=Path, help="CSV containing matched temperature/performance rows.")
    parser.add_argument("--chart", type=Path, help="Custom temperature chart PNG to copy into the artifact folder.")
    parser.add_argument("--title", default="Temperature vs Speed", help="Title for the generated temperature chart.")
    parsed = parser.parse_args(args)
    if parsed.csv is None and parsed.chart is None:
        parser.error("At least one of --csv or --chart is required.")

    from drive_qual.workflows.temperature import post_process_temperature_data

    post_process_temperature_data(
        part_number=parsed.part_number,
        dut_name=parsed.dut,
        performance_csv=parsed.csv,
        chart=parsed.chart,
        chart_title=parsed.title,
    )


def _run_status(args: list[str]) -> None:
    parser = _parser("drive-qual status")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parsed = parser.parse_args(args)

    from drive_qual.core.report_session import current_session_folder_name, report_path_for, resolve_folder_name
    from drive_qual.core.storage_paths import localize_windows_path

    folder_name = resolve_folder_name(parsed.part_number) if parsed.part_number else current_session_folder_name()
    if folder_name is None:
        print("No active session marker. Pass --part-number to inspect a report folder.")
        return

    report_path = report_path_for(folder_name)
    local_path = localize_windows_path(report_path)
    print(f"Session folder: {folder_name}")
    print(f"Report path: {report_path}")
    print(f"Local path: {local_path}")
    print(f"Report exists: {'yes' if local_path.exists() else 'no'}")


def _run_list_steps() -> None:
    from drive_qual.workflows.report import STEP_ORDER

    print("Workflow steps:")
    for step in STEP_ORDER:
        aliases = sorted(alias for alias, target in STEP_ALIASES.items() if target == step and alias != step)
        suffix = f" ({', '.join(aliases)})" if aliases else ""
        print(f"  - {step}{suffix}")


def _run_list_profiles() -> None:
    from drive_qual.workflows.orchestrator import WORKFLOW_PROFILES

    print("Workflow profiles:")
    for profile_name, steps in sorted(WORKFLOW_PROFILES.items()):
        print(f"  - {profile_name}: {', '.join(steps)}")


def _run_legacy() -> None:
    from drive_qual.cli.legacy import main as legacy_main

    legacy_main()


def _parser(prog: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=prog, add_help=False)


def _die(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    print("Run `drive-qual` for usage.", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
