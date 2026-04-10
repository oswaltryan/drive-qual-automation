from __future__ import annotations

import os
import shutil
import sys
from pathlib import PureWindowsPath

FIO_NOT_FOUND_MESSAGE = (
    "fio not found. Install fio and ensure it is on PATH "
    "(macOS: `brew install fio`; Linux: use your package manager; "
    "Windows: https://bsdio.com/fio/)."
)
DISKSPD_NOT_FOUND_MESSAGE = "diskspd not found in PATH. Download it and add to system PATH"
DRIVE_TOKEN_LEN = 1
DRIVE_TOKEN_WITH_COLON_LEN = 2


def _resolve_tool(*candidates: str) -> str | None:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    return None


def _fio_candidates() -> tuple[str, ...]:
    if sys.platform == "win32":
        return (
            "fio.exe",
            "tools/fio.exe",
            "fio",
        )
    if sys.platform == "darwin":
        return (
            "fio",
            "/opt/homebrew/bin/fio",
            "/usr/local/bin/fio",
            "tools/fio",
        )
    return (
        "fio",
        "/usr/bin/fio",
        "/usr/local/bin/fio",
    )


def _require_fio() -> str:
    tool = _resolve_tool(*_fio_candidates())
    if tool is None:
        raise FileNotFoundError(FIO_NOT_FOUND_MESSAGE)
    return tool


def require_fio() -> str:
    return _require_fio()


def _require_diskspd() -> str:
    tool = _resolve_tool("diskspd.exe", "tools/diskspd.exe")
    if tool is None:
        raise FileNotFoundError(DISKSPD_NOT_FOUND_MESSAGE)
    return tool


def benchmark_directory(target_dir: str) -> str:
    token = target_dir.strip()
    if len(token) == DRIVE_TOKEN_LEN and token.isalpha():
        return f"{token}:\\"
    if len(token) == DRIVE_TOKEN_WITH_COLON_LEN and token[1] == ":" and token[0].isalpha():
        return f"{token}\\"
    return token


def benchmark_file_path(target_dir: str, filename: str) -> str:
    if sys.platform != "win32":
        return os.path.join(target_dir, filename)
    return str(PureWindowsPath(benchmark_directory(target_dir)) / filename)
