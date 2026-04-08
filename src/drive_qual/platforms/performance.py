from __future__ import annotations

import sys


def run_software_step(part_number: str | None = None) -> None:
    if sys.platform.startswith("linux"):
        from drive_qual.platforms.linux.performance import run_software_step as run_linux_software_step

        run_linux_software_step(part_number=part_number)
        return

    if sys.platform == "darwin":
        from drive_qual.platforms.macos.performance import run_software_step as run_macos_software_step

        run_macos_software_step(part_number=part_number)
        return

    from drive_qual.platforms.windows.performance import run_software_step as run_windows_software_step

    run_windows_software_step(part_number=part_number)
