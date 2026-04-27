from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


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


ALUMINUM_PRODUCTS = {
    "ask3",
    "ask3-nx",
    "fortress l3",
    "padlock dt",
    "padlock dt fips",
    "padlock ssd",
}
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
INRUSH_FIELDS = {
    "max_inrush_current": "In-Rush current",
    "max_inrush_current_5v": "In-Rush current 5V",
    "max_inrush_current_12v": "In-Rush current 12V",
}


def evaluate_report(data: dict[str, Any]) -> EvaluatedReport:
    power = evaluate_power(data.get("power"))
    temperature = evaluate_temperature(data.get("temperature"))
    summary = _build_summary(power, temperature)
    return EvaluatedReport(summary=summary, power=power, temperature=temperature)


def case_material_for_product(product_name: str) -> str:
    normalized = _normalize_product(product_name)
    if normalized in ALUMINUM_PRODUCTS:
        return "aluminum"
    return "plastic"


def evaluate_power(power: object) -> dict[str, list[EvaluatedValue]]:
    if not isinstance(power, dict):
        return {}

    evaluated: dict[str, list[EvaluatedValue]] = {}
    for dut_name, fields in power.items():
        if not isinstance(fields, dict):
            continue
        rows: list[EvaluatedValue] = []
        rows.extend(_evaluate_power_field_group(fields, MAX_IO_RMS_FIELDS, _evaluate_max_io_rms))
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
    for field_name, field_label in field_labels.items():
        raw_slot = fields.get(field_name)
        if raw_slot is None and field_name in MAX_IO_MIN_VOLTAGE_FIELDS:
            continue
        slot = raw_slot if isinstance(raw_slot, dict) else {}
        for os_key in OS_KEYS:
            label = f"{field_label} ({os_key})"
            rows.append(evaluator(label, slot.get(os_key)))
    return rows


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


def _normalize_product(value: str) -> str:
    return " ".join(value.replace("_", " ").casefold().split())


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None
