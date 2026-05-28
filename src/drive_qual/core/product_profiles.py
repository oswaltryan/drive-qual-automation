from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_POWER_RAILS: tuple[str | None, ...] = (None,)
DUAL_RAIL_POWER_RAILS: tuple[str | None, ...] = ("5V", "12V")
DEFAULT_REQUIRED_POWER_FIELDS: tuple[str, ...] = (
    "max_inrush_current",
    "max_read_write_current",
    "rms_read_write_current",
)
DUAL_RAIL_REQUIRED_POWER_FIELDS: tuple[str, ...] = (
    "max_inrush_current_5v",
    "max_inrush_current_12v",
    "max_read_write_current_5v",
    "rms_read_write_current_5v",
    "max_read_write_current_12v",
    "rms_read_write_current_12v",
)


@dataclass(frozen=True)
class ProductProfile:
    profile_id: str
    report_dut_name: str
    form_factors: tuple[str, ...] = ()
    artifact_aliases: tuple[str, ...] = ()
    power_rails: tuple[str | None, ...] = DEFAULT_POWER_RAILS
    case_material: str = "plastic"

    @property
    def required_power_fields(self) -> tuple[str, ...]:
        if self.power_rails == DUAL_RAIL_POWER_RAILS:
            return DUAL_RAIL_REQUIRED_POWER_FIELDS
        return DEFAULT_REQUIRED_POWER_FIELDS


PRODUCT_PROFILES: tuple[ProductProfile, ...] = (
    ProductProfile("fortress", "Fortress", form_factors=("2.5",), case_material="plastic"),
    ProductProfile("fortress_l3", "Fortress L3", form_factors=("2.5",), case_material="aluminum"),
    ProductProfile("padlock_3_0", "Padlock 3.0", form_factors=("2.5",), case_material="plastic"),
    ProductProfile(
        "padlock_dt",
        "Padlock DT",
        form_factors=("3.5",),
        artifact_aliases=(
            "Aegis DT",
            "Aegis FIPS DT",
            "Padlock DT FIPS",
        ),
        power_rails=DUAL_RAIL_POWER_RAILS,
        case_material="aluminum",
    ),
    ProductProfile("ask3", "ASK3", form_factors=("sata (custom)",), case_material="aluminum"),
    ProductProfile("padlock_ssd", "Padlock SSD", form_factors=("msata",), case_material="aluminum"),
    ProductProfile("ask3_nx", "ASK3-NX", form_factors=("emmc",), case_material="aluminum"),
    ProductProfile("padlock_nvx", "Padlock NVX", form_factors=("nvme",)),
)


def normalize_product_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return re.sub(r"\s+", " ", normalized)


def profiles_for_form_factor(form_factor: str) -> tuple[ProductProfile, ...]:
    normalized = normalize_product_name(form_factor)
    return tuple(
        profile
        for profile in PRODUCT_PROFILES
        if any(normalize_product_name(candidate) == normalized for candidate in profile.form_factors)
    )


def report_dut_names_for_form_factor(form_factor: str) -> tuple[str, ...]:
    return tuple(profile.report_dut_name for profile in profiles_for_form_factor(form_factor))


def profile_for_report_dut(dut_name: str) -> ProductProfile | None:
    normalized = normalize_product_name(dut_name)
    for profile in PRODUCT_PROFILES:
        candidates = (profile.report_dut_name, *profile.artifact_aliases)
        if any(normalize_product_name(candidate) == normalized for candidate in candidates):
            return profile
    return None


def profile_for_artifact_name(artifact_name: str) -> ProductProfile | None:
    normalized = normalize_product_name(artifact_name)
    for profile in PRODUCT_PROFILES:
        candidates = (profile.report_dut_name, *profile.artifact_aliases)
        if any(normalize_product_name(candidate) == normalized for candidate in candidates):
            return profile
    return None


def canonical_report_dut_name(artifact_name: str) -> str | None:
    profile = profile_for_artifact_name(artifact_name)
    return None if profile is None else profile.report_dut_name


def report_dut_name_candidates(name: str) -> tuple[str, ...]:
    profile = profile_for_report_dut(name) or profile_for_artifact_name(name)
    if profile is None:
        return (name,)
    return (profile.report_dut_name, *profile.artifact_aliases)


def power_rails_for_dut(dut_name: str) -> tuple[str | None, ...]:
    profile = profile_for_report_dut(dut_name)
    return DEFAULT_POWER_RAILS if profile is None else profile.power_rails


def required_power_fields_for_dut(dut_name: str) -> tuple[str, ...]:
    profile = profile_for_report_dut(dut_name)
    return DEFAULT_REQUIRED_POWER_FIELDS if profile is None else profile.required_power_fields


def case_material_for_product_name(product_name: str) -> str:
    profile = profile_for_report_dut(product_name) or profile_for_artifact_name(product_name)
    return "plastic" if profile is None else profile.case_material
