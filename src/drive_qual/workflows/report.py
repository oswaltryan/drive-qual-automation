from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from drive_qual.core.report_session import (
    clear_current_session,
    current_session_folder_name,
    load_report,
    report_path_for,
    sanitize_dir_name,
)
from drive_qual.workflows.orchestrator import (
    WORKFLOW_PROFILES,
    execute_orchestrated_workflow,
    resolve_selected_steps,
)

STEP_ORDER: tuple[str, ...] = ("drive_info", "equipment", "power_measurements", "performance")
StepRunner = Callable[[], None]
POWER_OS_KEYS: tuple[str, ...] = ("windows", "linux", "macos")
PERFORMANCE_HOSTS: tuple[tuple[str, str], ...] = (
    ("windows_host", "Windows"),
    ("linux_host", "Linux"),
    ("macos_host", "macOS"),
)
DT_FIPS_DUT_NAME = "padlock dt fips"


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


def _has_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _all_os_power_slots_filled(values: Any) -> bool:
    if not isinstance(values, dict):
        return False
    return all(_has_value(values.get(os_key)) for os_key in POWER_OS_KEYS)


def _required_power_fields_for_dut(dut_name: str) -> tuple[str, ...]:
    normalized = " ".join(dut_name.strip().casefold().split())
    if normalized == DT_FIPS_DUT_NAME:
        return (
            "max_inrush_current_5v",
            "max_inrush_current_12v",
            "max_read_write_current_5v",
            "rms_read_write_current_5v",
            "max_read_write_current_12v",
            "rms_read_write_current_12v",
        )
    return (
        "max_inrush_current",
        "max_read_write_current",
        "rms_read_write_current",
    )


def _find_matching_section_key(section: dict[str, Any], requested_name: str) -> str | None:
    requested_cf = requested_name.casefold()
    for key in section:
        key_cf = key.casefold()
        if requested_cf == key_cf:
            return key
        if requested_cf in key_cf or key_cf in requested_cf:
            return key
    if len(section) == 1:
        return next(iter(section))
    return None


def _is_power_complete(data: dict[str, Any]) -> bool:
    power = data.get("power")
    if not isinstance(power, dict) or not power:
        return False

    for dut_name, fields in power.items():
        if not isinstance(fields, dict):
            return False
        for field_name in _required_power_fields_for_dut(str(dut_name)):
            if not _all_os_power_slots_filled(fields.get(field_name)):
                return False
    return True


def _software_entries_for_host(equipment: dict[str, Any], host_key: str) -> list[dict[str, Any]]:
    host_data = equipment.get(host_key)
    if not isinstance(host_data, dict):
        return []
    software = host_data.get("software")
    if not isinstance(software, list):
        return []
    return [entry for entry in software if isinstance(entry, dict)]


def _is_performance_measurement_complete(tool_name: str, value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if tool_name == "CrystalDiskInfo":
        return _has_value(value.get("screenshot"))
    return _has_value(value.get("read")) and _has_value(value.get("write"))


def _is_performance_complete(data: dict[str, Any]) -> bool:
    equipment = data.get("equipment")
    performance = data.get("performance")
    if not isinstance(equipment, dict) or not isinstance(performance, dict):
        return False

    dut_bindings = equipment.get("dut")
    if not isinstance(dut_bindings, dict) or not dut_bindings:
        return False

    for dut_name in dut_bindings:
        perf_key = _find_matching_section_key(performance, str(dut_name))
        if perf_key is None:
            return False
        perf_entry = performance.get(perf_key)
        if not isinstance(perf_entry, dict):
            return False

        for host_key, os_key in PERFORMANCE_HOSTS:
            os_perf = perf_entry.get(os_key)
            if not isinstance(os_perf, dict):
                return False
            for software in _software_entries_for_host(equipment, host_key):
                tool_name = software.get("name")
                if not isinstance(tool_name, str) or not tool_name.strip():
                    continue
                if not _is_performance_measurement_complete(tool_name.strip(), os_perf.get(tool_name.strip())):
                    return False
    return True


def _resolve_session_folder_name(part_number: str | None) -> str | None:
    if part_number:
        folder_name = sanitize_dir_name(part_number)
        return folder_name or None
    return current_session_folder_name()


def _clear_current_session_if_workflow_complete(part_number: str | None) -> None:
    folder_name = _resolve_session_folder_name(part_number)
    if not folder_name:
        return
    report_path = report_path_for(folder_name)
    try:
        data = load_report(report_path)
    except Exception:
        return
    if _is_power_complete(data) and _is_performance_complete(data):
        clear_current_session()
        print(f"Cleared current session marker after completing workflow for {folder_name}.")


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
    _clear_current_session_if_workflow_complete(part_number)


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
