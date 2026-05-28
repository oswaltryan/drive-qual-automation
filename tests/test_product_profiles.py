from __future__ import annotations

from drive_qual.core.product_profiles import (
    DUAL_RAIL_POWER_RAILS,
    canonical_report_dut_name,
    case_material_for_product_name,
    power_rails_for_dut,
    report_dut_name_candidates,
    report_dut_names_for_form_factor,
    required_power_fields_for_dut,
)


def test_product_profiles_map_form_factor_to_report_dut_names() -> None:
    assert report_dut_names_for_form_factor("3.5") == ("Padlock DT",)
    assert report_dut_names_for_form_factor("NVMe") == ("Padlock NVX",)


def test_product_profiles_resolve_artifact_aliases_to_report_dut_name() -> None:
    assert canonical_report_dut_name("Aegis FIPS DT") == "Padlock DT"
    assert canonical_report_dut_name("Padlock DT FIPS") == "Padlock DT"


def test_product_profiles_provide_report_dut_name_candidates() -> None:
    assert report_dut_name_candidates("Aegis FIPS DT") == (
        "Padlock DT",
        "Aegis DT",
        "Aegis FIPS DT",
        "Padlock DT FIPS",
    )


def test_product_profiles_define_power_requirements() -> None:
    assert power_rails_for_dut("Padlock DT") == DUAL_RAIL_POWER_RAILS
    assert required_power_fields_for_dut("Padlock DT") == (
        "max_inrush_current_5v",
        "max_inrush_current_12v",
        "max_read_write_current_5v",
        "rms_read_write_current_5v",
        "max_read_write_current_12v",
        "rms_read_write_current_12v",
    )
    assert power_rails_for_dut("Padlock NVX") == (None,)
    assert required_power_fields_for_dut("Padlock NVX") == (
        "max_inrush_current",
        "max_read_write_current",
        "rms_read_write_current",
    )


def test_product_profiles_define_case_material() -> None:
    assert case_material_for_product_name("Padlock DT") == "aluminum"
    assert case_material_for_product_name("Padlock DT FIPS") == "aluminum"
    assert case_material_for_product_name("Padlock NVX") == "plastic"
