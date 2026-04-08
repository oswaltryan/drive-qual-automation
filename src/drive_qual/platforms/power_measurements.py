from __future__ import annotations


def run_power_measurements_step() -> None:
    from drive_qual.platforms.windows.power_measurements import run_power_measurements_step as run_mixed_platform_step

    run_mixed_platform_step()
