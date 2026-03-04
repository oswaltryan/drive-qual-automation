from __future__ import annotations

import argparse
from typing import Any

from drive_qual.report_session import load_report, report_path_for, resolve_folder_name, save_report

FORM_FACTOR_PRODUCTS: dict[str, list[str]] = {
    "2.5": ["Fortress", "Fortress L3", "Padlock 3.0"],
    "3.5": ["Padlock DT", "Padlock DT FIPS"],
    "sata (custom)": ["ASK3"],
    "msata": ["Padlock SSD"],
    "emmc": ["ASK3-NX"],
    "nvme": ["Padlock NVX"],
}

HOST_DEFAULTS: dict[str, dict[str, Any]] = {
    "windows_host": {
        "hardware": "",
        "os_version": "",
        "software": [],
    },
    "usb_if_host": {
        "hardware": "",
        "os_version": "",
        "software": [],
    },
    "linux_host": {
        "hardware": "",
        "os_version": "",
        "software": [],
    },
    "macos_host": {
        "hardware": "",
        "os_version": "",
        "software": [],
    },
}


def _prompt(label: str, current: str) -> str:
    if current:
        entry = input(f"{label} [{current}]: ").strip()
        return entry or current
    return input(f"{label}: ").strip()


def _dut_from_form_factor(data: dict[str, Any]) -> list[str]:
    drive_info = data.get("drive_info")
    form_factor = ""
    if isinstance(drive_info, dict):
        value = drive_info.get("form_factor")
        if isinstance(value, str):
            form_factor = value.strip().lower()

    if form_factor not in FORM_FACTOR_PRODUCTS:
        raise ValueError(f"Unknown form factor: {form_factor or '<missing>'}")

    return FORM_FACTOR_PRODUCTS[form_factor]


def apply_scope_profile(equipment: dict[str, Any], scope: str) -> None:
    """
    Fill scope/probe fields based on a named scope profile.

    TODO: Populate with your lab's exact values.
    """
    scope_key = scope.strip().lower()
    if scope_key in {"tektronix", "tek"}:
        equipment["scope"] = {"model": "Tektronix MSO54", "version": "2.0.3", "serial_number": "B013976"}
        equipment["probe_current"] = {"model": "TCP202A", "channel": "4", "serial_number": "C004510"}
        equipment["probe_voltage"] = {"model": "TPP0500B", "channel": "2", "serial_number": "C166742"}
        return
    if scope_key in {"rigol"}:
        equipment["scope"] = {"model": "Rigol", "version": "", "serial_number": ""}
        equipment["probe_current"] = {"model": "Rigol Current Probe", "channel": "", "serial_number": ""}
        equipment["probe_voltage"] = {"model": "Rigol Voltage Probe", "channel": "", "serial_number": ""}
        return
    raise ValueError(f"Unknown scope profile: {scope}")


def _ensure_hosts(equipment: dict[str, Any]) -> None:
    for key, defaults in HOST_DEFAULTS.items():
        current = equipment.get(key)
        if not isinstance(current, dict):
            equipment[key] = defaults
            continue
        for field_key, field_value in defaults.items():
            if field_key not in current or current[field_key] is None:
                current[field_key] = field_value


def _temperature_template() -> dict[str, Any]:
    temps = ["-40c", "-35c", "-30c", "-20c", "-10c", "0c", "10c", "20c", "30c", "40c", "50c", "60c", "70c", "80c"]
    return {"performance": {temp: {"read_mb_s": None, "write_mb_s": None} for temp in temps}}


def _ensure_dut_sections(data: dict[str, Any], duts: list[str]) -> None:
    power = data.setdefault("power", {})
    if not isinstance(power, dict):
        raise ValueError("Invalid 'power' section; expected object.")
    if not isinstance(power, dict):
        raise ValueError("Invalid 'power' section; expected object.")

    performance = data.setdefault("performance", {})
    if not isinstance(performance, dict):
        raise ValueError("Invalid 'performance' section; expected object.")

    temperature = data.setdefault("temperature", {})
    if not isinstance(temperature, dict):
        raise ValueError("Invalid 'temperature' section; expected object.")

    for dut in duts:
        power.setdefault(
            dut,
            {
                "max_inrush_current": {"linux": None, "macos": None, "windows": None},
                "max_read_write_current": {"linux": None, "macos": None, "windows": None},
                "rms_read_write_current": {"linux": None, "macos": None, "windows": None},
            },
        )
        performance.setdefault(
            dut,
            {
                "disks_read": {"linux": None, "macos": None, "windows": None},
                "disks_write": {"linux": None, "macos": None, "windows": None},
                "blackmagic_read": None,
                "blackmagic_write": None,
                "cdm_read": None,
                "cdm_write": None,
            },
        )
        temperature.setdefault(dut, _temperature_template())


def run_equipment_prompt() -> None:
    parser = argparse.ArgumentParser(description="Fill equipment section in report JSON.")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the logs folder.")
    parser.add_argument("--scope-profile", help="Apply a scope/probe profile (e.g., tektronix, rigol).")
    args = parser.parse_args()

    folder_name = resolve_folder_name(args.part_number)
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section in report.")

    scope_profile = args.scope_profile or _prompt("Scope profile (tektronix/rigol)", "")
    if scope_profile:
        apply_scope_profile(equipment, scope_profile)

    _ensure_hosts(equipment)

    equipment["dut"] = _dut_from_form_factor(data)
    _ensure_dut_sections(data, equipment["dut"])

    save_report(report_path, data)
    print(f"Updated equipment in {report_path}")


if __name__ == "__main__":
    run_equipment_prompt()
