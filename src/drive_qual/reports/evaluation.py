from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from drive_qual.core.product_profiles import case_material_for_product_name
from drive_qual.reports.cdi import CDI_APPENDIX_FIELDS


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class EvaluatedValue:
    label: str
    value: Any
    status: Status
    reason: str


@dataclass(frozen=True)
class EvaluatedReport:
    summary: list[EvaluatedValue]
    power: dict[str, list[EvaluatedValue]]
    temperature: dict[str, list[EvaluatedValue]]
    warnings: list[ReviewFinding]
    review_sections: list[str]


@dataclass(frozen=True)
class ReviewFinding:
    section: str
    dut: str
    label: str
    status: Status
    reason: str


OS_KEYS = ("windows", "linux", "macos")
MAX_IO_RMS_FAIL_MA = 1000.0
MAX_IO_RMS_WARN_MA = 900.0
MAX_IO_MIN_VOLTAGE_FAIL_V = 4.7
INRUSH_WARN_MA = 900.0
MAX_IO_RMS_FIELDS = {
    "rms_read_write_current": "Max I/O RMS current",
    "rms_read_write_current_5v": "Max I/O RMS current 5V",
    "rms_read_write_current_12v": "Max I/O RMS current 12V",
}
MAX_IO_MIN_VOLTAGE_FIELDS = {
    "min_read_write_voltage": "Max I/O minimum voltage",
    "min_read_write_voltage_5v": "Max I/O minimum voltage 5V",
    "min_read_write_voltage_12v": "Max I/O minimum voltage 12V",
}
MAX_IO_PEAK_FIELDS = {
    "max_read_write_current": "Max read/write current",
    "max_read_write_current_5v": "Max read/write current 5V",
    "max_read_write_current_12v": "Max read/write current 12V",
}
INRUSH_FIELDS = {
    "max_inrush_current": "In-Rush current",
    "max_inrush_current_5v": "In-Rush current 5V",
    "max_inrush_current_12v": "In-Rush current 12V",
}


def evaluate_report(data: dict[str, Any]) -> EvaluatedReport:
    power = evaluate_power(data.get("power"))
    temperature = evaluate_temperature(data.get("temperature"))
    summary = _build_summary(power, temperature)
    warnings = _build_warning_findings(power, temperature)
    review_sections = _build_review_sections(data, power, temperature)
    return EvaluatedReport(
        summary=summary,
        power=power,
        temperature=temperature,
        warnings=warnings,
        review_sections=review_sections,
    )


def case_material_for_product(product_name: str) -> str:
    return case_material_for_product_name(product_name)


def evaluate_power(power: object) -> dict[str, list[EvaluatedValue]]:
    if not isinstance(power, dict):
        return {}

    evaluated: dict[str, list[EvaluatedValue]] = {}
    for dut_name, fields in power.items():
        if not isinstance(fields, dict):
            continue
        rows: list[EvaluatedValue] = []
        rows.extend(_evaluate_power_field_group(fields, MAX_IO_RMS_FIELDS, _evaluate_max_io_rms))
        rows.extend(_evaluate_power_field_group(fields, MAX_IO_PEAK_FIELDS, _evaluate_present_power_value))
        if any(field_name in fields for field_name in MAX_IO_MIN_VOLTAGE_FIELDS):
            rows.extend(_evaluate_power_field_group(fields, MAX_IO_MIN_VOLTAGE_FIELDS, _evaluate_max_io_min_voltage))
        rows.extend(_evaluate_power_field_group(fields, INRUSH_FIELDS, _evaluate_inrush))
        evaluated[str(dut_name)] = rows
    return evaluated


def evaluate_temperature(temperature: object) -> dict[str, list[EvaluatedValue]]:
    if not isinstance(temperature, dict):
        return {}

    representative_by_material = _temperature_representatives(temperature)
    evaluated: dict[str, list[EvaluatedValue]] = {}
    for dut_name, dut_data in temperature.items():
        material = case_material_for_product(str(dut_name))
        rows = _evaluate_dut_temperature(str(dut_name), dut_data)
        if not rows or all(row.status == Status.MISSING for row in rows):
            representative = representative_by_material.get(material)
            if representative and representative != dut_name:
                rows = [
                    EvaluatedValue(
                        label="Temperature coverage",
                        value=material,
                        status=Status.NOT_APPLICABLE,
                        reason=f"Covered by {representative} {material} representative.",
                    )
                ]
        evaluated[str(dut_name)] = rows
    return evaluated


def _evaluate_power_field_group(
    fields: dict[str, Any],
    field_labels: dict[str, str],
    evaluator: Any,
) -> list[EvaluatedValue]:
    rows: list[EvaluatedValue] = []
    slots = [
        (field_label, slot)
        for field_name, field_label in field_labels.items()
        if isinstance((slot := fields.get(field_name)), dict)
    ]
    if not slots:
        return rows
    for os_key in OS_KEYS:
        label, value = _best_power_field_value(slots, os_key)
        rows.append(evaluator(f"{label} ({os_key})", value))
    return rows


def _best_power_field_value(slots: list[tuple[str, dict[str, Any]]], os_key: str) -> tuple[str, object]:
    best_label = slots[0][0]
    best_value: float | None = None
    for field_label, slot in slots:
        numeric = _to_float(slot.get(os_key))
        if numeric is not None and (best_value is None or numeric > best_value):
            best_label = field_label
            best_value = numeric
    if best_value is not None:
        return best_label, best_value
    return best_label, None


def _evaluate_present_power_value(label: str, value: object) -> EvaluatedValue:
    numeric = _to_float(value)
    if numeric is None:
        return EvaluatedValue(label, value, Status.MISSING, "No power value was recorded.")
    return EvaluatedValue(label, numeric, Status.PASS, "Power value was recorded.")


def _evaluate_max_io_rms(label: str, value: object) -> EvaluatedValue:
    numeric = _to_float(value)
    if numeric is None:
        return EvaluatedValue(label, value, Status.MISSING, "No Max I/O RMS current was recorded.")
    if numeric >= MAX_IO_RMS_FAIL_MA:
        return EvaluatedValue(label, numeric, Status.FAIL, "Must be less than 1000 mA.")
    if numeric >= MAX_IO_RMS_WARN_MA:
        return EvaluatedValue(label, numeric, Status.WARN, "Between 900 mA and 1000 mA review band.")
    return EvaluatedValue(label, numeric, Status.PASS, "Below 900 mA review band.")


def _evaluate_max_io_min_voltage(label: str, value: object) -> EvaluatedValue:
    numeric = _to_float(value)
    if numeric is None:
        return EvaluatedValue(label, value, Status.MISSING, "No Max I/O minimum voltage was recorded.")
    if numeric <= MAX_IO_MIN_VOLTAGE_FAIL_V:
        return EvaluatedValue(label, numeric, Status.FAIL, "Must be greater than 4.7 V.")
    return EvaluatedValue(label, numeric, Status.PASS, "Greater than 4.7 V.")


def _evaluate_inrush(label: str, value: object) -> EvaluatedValue:
    numeric = _to_float(value)
    if numeric is None:
        return EvaluatedValue(label, value, Status.MISSING, "No In-Rush current was recorded.")
    if numeric > INRUSH_WARN_MA:
        return EvaluatedValue(label, numeric, Status.WARN, "Over 900 mA flag threshold.")
    return EvaluatedValue(label, numeric, Status.PASS, "At or below 900 mA flag threshold.")


def _evaluate_dut_temperature(dut_name: str, dut_data: object) -> list[EvaluatedValue]:
    if not isinstance(dut_data, dict):
        return []
    performance = dut_data.get("performance")
    if not isinstance(performance, dict):
        return []

    rows: list[EvaluatedValue] = []
    for temp_label, temp_data in performance.items():
        if not isinstance(temp_data, dict):
            continue
        error = temp_data.get("error")
        for metric in ("read_mb_s", "write_mb_s"):
            label = f"{temp_label} {metric.replace('_', ' ')}"
            value = temp_data.get(metric)
            if error:
                rows.append(EvaluatedValue(label, value, Status.FAIL, f"Temperature test error: {error}"))
                continue
            numeric = _to_float(value)
            if numeric is None:
                rows.append(EvaluatedValue(label, value, Status.MISSING, f"No temperature value for {dut_name}."))
            elif numeric == 0:
                rows.append(EvaluatedValue(label, numeric, Status.FAIL, "Speed dropped to 0."))
            else:
                rows.append(EvaluatedValue(label, numeric, Status.PASS, "Recorded non-zero speed."))
    return rows


def _temperature_representatives(temperature: dict[Any, Any]) -> dict[str, str]:
    representatives: dict[str, str] = {}
    for dut_name, dut_data in temperature.items():
        rows = _evaluate_dut_temperature(str(dut_name), dut_data)
        if any(row.status in {Status.PASS, Status.WARN, Status.FAIL} for row in rows):
            representatives.setdefault(case_material_for_product(str(dut_name)), str(dut_name))
    return representatives


def _build_summary(
    power: dict[str, list[EvaluatedValue]], temperature: dict[str, list[EvaluatedValue]]
) -> list[EvaluatedValue]:
    rows = [row for values in power.values() for row in values]
    rows.extend(row for values in temperature.values() for row in values)
    return [
        EvaluatedValue("Failures", _count_status(rows, Status.FAIL), Status.FAIL, "Total failing evaluated results."),
        EvaluatedValue("Warnings", _count_status(rows, Status.WARN), Status.WARN, "Total warning evaluated results."),
        EvaluatedValue(
            "Missing",
            _count_status(rows, Status.MISSING),
            Status.MISSING,
            "Total missing evaluated results.",
        ),
    ]


def _count_status(rows: list[EvaluatedValue], status: Status) -> int:
    return sum(1 for row in rows if row.status == status)


def _build_warning_findings(
    power: dict[str, list[EvaluatedValue]], temperature: dict[str, list[EvaluatedValue]]
) -> list[ReviewFinding]:
    findings = _section_warning_findings("Power Data", power)
    findings.extend(_section_warning_findings("Temperature Data", temperature))
    return findings


def _section_warning_findings(section: str, values_by_dut: dict[str, list[EvaluatedValue]]) -> list[ReviewFinding]:
    return [
        ReviewFinding(section, dut, row.label, row.status, row.reason)
        for dut, rows in values_by_dut.items()
        for row in rows
        if row.status == Status.WARN
    ]


def _build_review_sections(
    data: dict[str, Any],
    power: dict[str, list[EvaluatedValue]],
    temperature: dict[str, list[EvaluatedValue]],
) -> list[str]:
    sections: list[str] = []
    if _has_review_status(power):
        sections.append("Power Data")
    if _compatibility_requires_review(data.get("compatibility")):
        sections.append("Compatibility Data")
    sections.extend(_performance_review_sections(data.get("performance")))
    if _compliance_requires_review(data.get("compliance"), data.get("reliability")):
        sections.append("Compliance/Reliability Test")
    if _has_review_status(temperature):
        sections.append("Temperature Data")
    return sections


def _has_review_status(values_by_dut: dict[str, list[EvaluatedValue]]) -> bool:
    return any(
        row.status in {Status.WARN, Status.FAIL, Status.MISSING} for rows in values_by_dut.values() for row in rows
    )


def _compatibility_requires_review(compatibility: object) -> bool:
    if not isinstance(compatibility, dict):
        return False
    return any(
        isinstance(slot, dict) and any(value is False for value in slot.values()) for slot in compatibility.values()
    )


def _performance_review_sections(performance: object) -> list[str]:
    if not isinstance(performance, dict):
        return []
    required_tools = (
        ("Windows", "CrystalDiskMark", ("read", "write")),
        ("Windows", "ATTO", ("read", "write")),
        ("macOS", "Blackmagic Disk Speed Test", ("read", "write")),
    )
    sections: list[str] = []
    for dut_name, platforms in performance.items():
        dut_name_text = str(dut_name)
        if not isinstance(platforms, dict):
            _append_unique(sections, "Disk Performance")
            continue
        if _cdi_details_require_review(str(dut_name), platforms):
            _append_unique(sections, _raw_data_section(dut_name_text))
        for platform, tool, metrics in required_tools:
            tool_data = platforms.get(platform, {}).get(tool) if isinstance(platforms.get(platform), dict) else None
            if not isinstance(tool_data, dict) or any(_to_float(tool_data.get(metric)) is None for metric in metrics):
                _append_unique(sections, "Disk Performance")
                break
    return sections


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _raw_data_section(dut_name: str) -> str:
    return f"Disk Performance Raw Data & Measurements ({dut_name})"


def _cdi_details_require_review(dut_name: str, platforms: dict[str, Any]) -> bool:
    if "ask3" in dut_name.casefold():
        return False
    windows_performance = platforms.get("Windows")
    if not isinstance(windows_performance, dict):
        return True
    cdi_details = windows_performance.get("CrystalDiskInfo")
    if not isinstance(cdi_details, dict):
        return True
    return any(not str(cdi_details.get(key) or "").strip() for key, _label in CDI_APPENDIX_FIELDS)


def _compliance_requires_review(compliance: object, reliability: object) -> bool:
    if not isinstance(compliance, dict):
        return False
    result_values = (
        compliance.get("usb_if_msc_result"),
        _reliability_result(reliability),
    )
    return any(_result_text(value).casefold() != "pass" for value in result_values)


def _reliability_result(reliability: object) -> object:
    if not isinstance(reliability, dict):
        return None
    windows = reliability.get("windows")
    if not isinstance(windows, dict):
        return None
    status = str(windows.get("status") or "").casefold()
    if status == "pass":
        return True
    if status == "fail":
        return False
    return None


def _result_text(value: object) -> str:
    if value is True:
        return "Pass"
    if value is False:
        return "Fail"
    return str(value or "")


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None
