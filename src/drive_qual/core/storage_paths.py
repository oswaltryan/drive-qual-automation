from __future__ import annotations

from pathlib import PureWindowsPath

SCOPE_ARTIFACT_ROOT = "Z:/"


def artifact_dir(part_number: str, os_name: str, category: str) -> str:
    return str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, os_name, category))


def artifact_file(part_number: str, os_name: str, category: str, filename: str) -> str:
    return str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, os_name, category, filename))
