from __future__ import annotations

from pathlib import Path, PureWindowsPath

from drive_qual.core.config import local_storage_root, windows_share_root

SCOPE_ARTIFACT_ROOT = windows_share_root()


def artifact_dir(part_number: str, os_name: str, category: str) -> str:
    return str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, os_name, category))


def artifact_file(part_number: str, os_name: str, category: str, filename: str) -> str:
    return str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, part_number, os_name, category, filename))


def localize_windows_path(path: str | Path) -> Path:
    windows_root = PureWindowsPath(SCOPE_ARTIFACT_ROOT)
    windows_path = PureWindowsPath(str(path))
    if not windows_path.drive or windows_path.drive.casefold() != windows_root.drive.casefold():
        return Path(path)
    return local_storage_root().joinpath(*windows_path.parts[1:])
