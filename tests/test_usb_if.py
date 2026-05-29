from __future__ import annotations

from pathlib import Path

from drive_qual.core.usb_if import (
    UsbIfMscResult,
    parse_msc_result_line,
    parse_msc_result_text,
    update_usb_if_compliance,
    usb_if_artifact_dir,
)

MSC_TEST_COUNT = 20


def test_parse_msc_result_line_returns_latest_result() -> None:
    result = parse_msc_result_line(
        "\n".join(
            [
                "Tests run (20), Failures (1)",
                "some other log line",
                "Tests run (20), Failures (0)",
            ]
        )
    )

    assert result is not None
    assert result.tests_run == MSC_TEST_COUNT
    assert result.failures == 0
    assert result.passed is True
    assert result.status == "Pass"


def test_parse_msc_result_text_reads_pass_fail_result_dialog_text() -> None:
    passed = parse_msc_result_text("Results Mass Storage Compliance Test Passed OK")
    failed = parse_msc_result_text("Results Mass Storage Compliance Test Failed OK")

    assert passed is not None
    assert passed.status == "Pass"
    assert failed is not None
    assert failed.status == "Fail"


def test_update_usb_if_compliance_sets_iterations_and_boolean_result() -> None:
    first = parse_msc_result_line("Tests run (20), Failures (0)")
    second = parse_msc_result_line("Tests run (20), Failures (0)")
    assert first is not None
    assert second is not None
    payload: dict[str, object] = {"compliance": {}}

    update_usb_if_compliance(
        payload,
        UsbIfMscResult(iterations=2, iteration_results=(first, second), artifact_dir=Path("reports")),
    )

    assert payload["compliance"] == {
        "usb_if_msc_iterations": 2,
        "usb_if_msc_result": True,
    }


def test_update_usb_if_compliance_requires_all_iterations_to_pass() -> None:
    first = parse_msc_result_line("Tests run (20), Failures (0)")
    second = parse_msc_result_line("Tests run (20), Failures (1)")
    assert first is not None
    assert second is not None
    payload: dict[str, object] = {"compliance": {}}

    update_usb_if_compliance(
        payload,
        UsbIfMscResult(iterations=2, iteration_results=(first, second), artifact_dir=Path("reports")),
    )

    assert payload["compliance"] == {
        "usb_if_msc_iterations": 2,
        "usb_if_msc_result": False,
    }


def test_update_usb_if_compliance_requires_all_iterations_to_be_present() -> None:
    first = parse_msc_result_line("Tests run (20), Failures (0)")
    assert first is not None
    payload: dict[str, object] = {"compliance": {}}

    update_usb_if_compliance(
        payload,
        UsbIfMscResult(iterations=2, iteration_results=(first,), artifact_dir=Path("reports")),
    )

    assert payload["compliance"] == {
        "usb_if_msc_iterations": 2,
        "usb_if_msc_result": False,
    }


def test_usb_if_artifact_dir_uses_part_windows_usb_if_layout() -> None:
    assert usb_if_artifact_dir("69-420") == Path(r"Z:\69-420\Windows\USB-IF")
