from __future__ import annotations

from typing import Any

from drive_qual.core.dut_selection import normalize_dut_bindings
from drive_qual.core.report_session import load_report, report_path_for, resolve_folder_name, save_report
from drive_qual.platforms.performance_common import BLACKMAGIC_DISK_SPEED_TEST_TOOL_NAME

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
        "hardware": "ASUS PRIME Z270-K, i5-7400K",
        "os_version": "Windows 10 Pro 22H2, 19045.6646",
        "software": [
            {"name": "CrystalDiskInfo", "version": "8.8.9"},
            {"name": "CrystalDiskMark", "version": "7.0.0"},
            {"name": "ATTO", "version": "4.0.0f1"},
        ],
    },
    "usb_if_host": {
        "hardware": "ASROCK Z790 Pro RS, i7-12700K",
        "os_version": "Windows 11 Pro 24H2, 26100.4652",
        "software": [
            {"name": "USB-IF CV Suite", "version": "3.1.2.0"},
        ],
    },
    "linux_host": {
        "hardware": "NUC8i3BEK1",
        "os_version": "Ubuntu 18.04.6 LTS, 5.0.4-150-generic",
        "software": [
            {"name": "Disks (native)", "version": None},
        ],
    },
    "macos_host": {
        "hardware": "Mac Mini M2",
        "os_version": "OS 15 Sequoia",
        "software": [
            {"name": BLACKMAGIC_DISK_SPEED_TEST_TOOL_NAME, "version": "4.2"},
        ],
    },
}

PROFILE_SECTIONS: dict[str, tuple[str, ...]] = {
    "scope": ("model", "version", "serial_number"),
    "probe_current": ("model", "channel", "serial_number"),
    "probe_voltage": ("model", "channel", "serial_number"),
}


def _prompt(label: str, current: str) -> str:
    if current:
        entry = input(f"{label} [{current}]: ").strip()
        return entry or current
    return input(f"{label}: ").strip()


def _dut_from_form_factor(data: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    drive_info = data.get("drive_info")
    form_factor = ""
    if isinstance(drive_info, dict):
        value = drive_info.get("form_factor")
        if isinstance(value, str):
            form_factor = value.strip().lower()

    if form_factor not in FORM_FACTOR_PRODUCTS:
        raise ValueError(f"Unknown form factor: {form_factor or '<missing>'}")

    return {dut_name: {"serial_number": None} for dut_name in FORM_FACTOR_PRODUCTS[form_factor]}


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


def _has_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _has_scope_profile_data(equipment: dict[str, Any]) -> bool:
    for section_name, fields in PROFILE_SECTIONS.items():
        section = equipment.get(section_name)
        if not isinstance(section, dict):
            return False
        if not all(_has_value(section.get(field_name)) for field_name in fields):
            return False
    return True


def _temperature_template() -> dict[str, Any]:
    temps = ["-40c", "-35c", "-30c", "-20c", "-10c", "0c", "10c", "20c", "30c", "40c", "50c", "60c", "70c", "80c"]
    return {"performance": {temp: {"read_mb_s": None, "write_mb_s": None} for temp in temps}}


def _ensure_dut_sections(data: dict[str, Any], duts: list[str]) -> None:
    equipment = data.get("equipment", {})
    power = data.setdefault("power", {})
    if not isinstance(power, dict):
        raise ValueError("Invalid 'power' section; expected object.")

    performance = data.setdefault("performance", {})
    if not isinstance(performance, dict):
        raise ValueError("Invalid 'performance' section; expected object.")

    temperature = data.setdefault("temperature", {})
    if not isinstance(temperature, dict):
        raise ValueError("Invalid 'temperature' section; expected object.")

    host_map = {
        "windows_host": "Windows",
        "linux_host": "Linux",
        "macos_host": "macOS",
    }

    for dut in duts:
        power.setdefault(
            dut,
            {
                "max_inrush_current": {"linux": None, "macos": None, "windows": None},
                "max_read_write_current": {"linux": None, "macos": None, "windows": None},
                "rms_read_write_current": {"linux": None, "macos": None, "windows": None},
            },
        )
        perf_dut = performance.setdefault(
            dut,
            {
                "Windows": {},
                "Linux": {},
                "macOS": {},
            },
        )
        for host_key, os_key in host_map.items():
            host_data = equipment.get(host_key, {})
            software_list = host_data.get("software", [])
            if isinstance(software_list, list):
                os_perf = perf_dut.setdefault(os_key, {})
                for sw in software_list:
                    if isinstance(sw, dict):
                        sw_name = sw.get("name")
                        if sw_name:
                            os_perf.setdefault(sw_name, {"read": None, "write": None})

        temperature.setdefault(dut, _temperature_template())


def run_equipment_prompt(part_number: str | None = None, scope_profile: str | None = None) -> None:
    folder_name = resolve_folder_name(part_number)
    report_path = report_path_for(folder_name)
    data = load_report(report_path)
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        raise ValueError("Missing or invalid 'equipment' section in report.")

    resolved_scope_profile = scope_profile
    if resolved_scope_profile:
        apply_scope_profile(equipment, resolved_scope_profile)
    elif not _has_scope_profile_data(equipment):
        resolved_scope_profile = _prompt("Scope profile (tektronix/rigol)", "")
        if resolved_scope_profile:
            apply_scope_profile(equipment, resolved_scope_profile)

    _ensure_hosts(equipment)

    expected_dut_bindings = _dut_from_form_factor(data)
    existing_dut_bindings = normalize_dut_bindings(equipment.get("dut"))
    for dut_name, binding in expected_dut_bindings.items():
        existing_binding = existing_dut_bindings.get(dut_name)
        if isinstance(existing_binding, dict):
            serial_number = existing_binding.get("serial_number")
            if isinstance(serial_number, str) and serial_number.strip():
                binding["serial_number"] = serial_number.strip()
    equipment["dut"] = expected_dut_bindings
    _ensure_dut_sections(data, list(expected_dut_bindings))

    save_report(report_path, data)
    print(f"Updated equipment in {report_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fill equipment section in report JSON.")
    parser.add_argument("--part-number", help="Apricorn part number for selecting the report folder.")
    parser.add_argument("--scope-profile", help="Apply a scope/probe profile (e.g., tektronix, rigol).")
    args = parser.parse_args()
    run_equipment_prompt(part_number=args.part_number, scope_profile=args.scope_profile)
