from __future__ import annotations

from drive_qual.reports.constants import STATUS_COLORS
from drive_qual.reports.evaluation import (
    Status,
    case_material_for_product,
    evaluate_power,
    evaluate_report,
    evaluate_temperature,
)


def test_power_evaluation_applies_max_io_thresholds() -> None:
    result = evaluate_power(
        {
            "Padlock DT": {
                "rms_read_write_current_5v": {
                    "windows": 899,
                    "linux": 900,
                    "macos": 1000,
                }
            }
        }
    )

    statuses = {row.label: row.status for row in result["Padlock DT"]}

    assert statuses["Max I/O RMS current 5V (windows)"] == Status.PASS
    assert statuses["Max I/O RMS current 5V (linux)"] == Status.WARN
    assert statuses["Max I/O RMS current 5V (macos)"] == Status.FAIL


def test_power_evaluation_applies_voltage_and_inrush_rules() -> None:
    result = evaluate_power(
        {
            "Padlock DT": {
                "min_read_write_voltage_5v": {"windows": 4.8, "linux": 4.7, "macos": None},
                "max_inrush_current_5v": {"windows": 900, "linux": 901, "macos": None},
            }
        }
    )

    statuses = {row.label: row.status for row in result["Padlock DT"]}

    assert statuses["Max I/O minimum voltage 5V (windows)"] == Status.PASS
    assert statuses["Max I/O minimum voltage 5V (linux)"] == Status.FAIL
    assert statuses["Max I/O minimum voltage 5V (macos)"] == Status.MISSING
    assert statuses["In-Rush current 5V (windows)"] == Status.PASS
    assert statuses["In-Rush current 5V (linux)"] == Status.WARN


def test_report_evaluation_records_warning_sections_by_document_heading() -> None:
    result = evaluate_report(
        {
            "power": {
                "Padlock DT": {
                    "rms_read_write_current_5v": {
                        "windows": 899,
                        "linux": 900,
                    }
                }
            }
        }
    )

    assert [(warning.section, warning.dut, warning.label) for warning in result.warnings] == [
        ("Power Data", "Padlock DT", "Max I/O RMS current 5V (linux)")
    ]


def test_report_evaluation_records_review_sections_by_document_heading() -> None:
    result = evaluate_report(
        {
            "power": {
                "Padlock SSD": {
                    "max_inrush_current": {"windows": 1480, "linux": 1080, "macos": 1520},
                }
            },
            "temperature": {"Padlock SSD": {"performance": {"20c": {"read_mb_s": None, "write_mb_s": None}}}},
            "compliance": {
                "usb_if_msc_result": None,
                "disk_tester_reliability_result": None,
            },
        }
    )

    assert result.review_sections == ["Power Data", "Compliance/Reliability Test", "Temperature Data"]


def test_report_evaluation_treats_true_compliance_results_as_pass() -> None:
    result = evaluate_report(
        {
            "compliance": {
                "usb_if_msc_iterations": 4,
                "usb_if_msc_result": True,
                "disk_tester_reliability_iterations": 8,
                "disk_tester_reliability_result": True,
            },
        }
    )

    assert "Compliance/Reliability Test" not in result.review_sections


def test_report_evaluation_reports_raw_data_section_for_missing_cdi_details() -> None:
    result = evaluate_report(
        {
            "performance": {
                "Padlock SSD": {
                    "Windows": {
                        "CrystalDiskInfo": {"model": "Padlock SSD"},
                        "CrystalDiskMark": {"read": 100, "write": 100},
                        "ATTO": {"read": 100, "write": 100},
                    },
                    "macOS": {"Blackmagic Disk Speed Test": {"read": 100, "write": 100}},
                }
            },
        }
    )

    assert result.review_sections == ["Disk Performance Raw Data & Measurements (Padlock SSD)"]


def test_report_evaluation_keeps_main_disk_performance_section_for_missing_benchmark_metrics() -> None:
    result = evaluate_report(
        {
            "performance": {
                "Padlock SSD": {
                    "Windows": {
                        "CrystalDiskInfo": {
                            "model": "Padlock SSD",
                            "transfer_mode": "SATA/600 | SATA/600",
                            "standard": "ACS-4",
                            "features": "S.M.A.R.T., NCQ, TRIM",
                            "rotation_rate": "---- (SSD)",
                        },
                        "CrystalDiskMark": {"read": 100, "write": None},
                        "ATTO": {"read": 100, "write": 100},
                    },
                    "macOS": {"Blackmagic Disk Speed Test": {"read": 100, "write": 100}},
                }
            },
        }
    )

    assert result.review_sections == ["Disk Performance"]


def test_power_evaluation_uses_visible_grouped_power_rows_for_missing_counts() -> None:
    expected_warning_count = 3
    result = evaluate_report(
        {
            "power": {
                "Padlock SSD": {
                    "max_inrush_current": {"windows": 1480, "linux": 1080, "macos": 1520},
                    "max_inrush_current_5v": {"windows": None, "linux": None, "macos": None},
                    "max_inrush_current_12v": {"windows": None, "linux": None, "macos": None},
                    "max_read_write_current": {"windows": 671.66, "linux": 708.44, "macos": 680.06},
                    "max_read_write_current_5v": {"windows": None, "linux": None, "macos": None},
                    "max_read_write_current_12v": {"windows": None, "linux": None, "macos": None},
                    "rms_read_write_current": {"windows": 342.37, "linux": 346.88, "macos": 338.13},
                    "rms_read_write_current_5v": {"windows": None, "linux": None, "macos": None},
                    "rms_read_write_current_12v": {"windows": None, "linux": None, "macos": None},
                }
            }
        }
    )

    assert next(row.value for row in result.summary if row.label == "Missing") == 0
    assert next(row.value for row in result.summary if row.label == "Warnings") == expected_warning_count


def test_temperature_evaluation_marks_zero_and_errors_red() -> None:
    result = evaluate_temperature(
        {
            "Padlock DT": {
                "performance": {
                    "20c": {"read_mb_s": 100, "write_mb_s": 0},
                    "30c": {"read_mb_s": None, "write_mb_s": None, "error": "benchmark failed"},
                }
            }
        }
    )

    statuses = {row.label: row.status for row in result["Padlock DT"]}

    assert statuses["20c read mb s"] == Status.PASS
    assert statuses["20c write mb s"] == Status.FAIL
    assert statuses["30c read mb s"] == Status.FAIL
    assert statuses["30c write mb s"] == Status.FAIL


def test_temperature_material_coverage_marks_untested_like_products_not_applicable() -> None:
    result = evaluate_temperature(
        {
            "Padlock DT": {"performance": {"20c": {"read_mb_s": 100, "write_mb_s": 100}}},
            "ASK3": {"performance": {"20c": {"read_mb_s": None, "write_mb_s": None}}},
        }
    )

    assert result["ASK3"][0].status == Status.NOT_APPLICABLE
    assert "Padlock DT" in result["ASK3"][0].reason


def test_case_material_classification_defaults_to_plastic() -> None:
    assert case_material_for_product("Fortress L3") == "aluminum"
    assert case_material_for_product("Padlock DT FIPS") == "aluminum"
    assert case_material_for_product("Padlock NVX") == "plastic"


def test_missing_report_cells_are_shaded_red() -> None:
    assert STATUS_COLORS[Status.MISSING] == "FFC7CE"
