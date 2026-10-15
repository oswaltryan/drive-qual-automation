"""Maintained report workflow CLI."""

import os
import sys


def run_report_workflow_cli() -> int:
    arguments = sys.argv[1:]
    if (
        "--l2" in arguments
        or any(
            arguments[index] == "--profile" and arguments[index + 1] == "fortress-l2"
            for index in range(len(arguments) - 1)
        )
        or "--profile=fortress-l2" in arguments
    ):
        # Configure the artifact root before importing modules that cache it.
        os.environ.setdefault("DRIVE_QUAL_OUTPUT_ROOT", "Z:/Done/L2")

    from drive_qual.workflows.report import run_report_workflow_cli as run

    return run()


__all__ = ["run_report_workflow_cli"]
