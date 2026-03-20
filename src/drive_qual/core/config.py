from __future__ import annotations

import os
import sys
import tomllib
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any

CONFIG_ENV_VAR = "DRIVE_QUAL_CONFIG"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "drive_qual.toml"
PLATFORM_KEYS: dict[str, str] = {
    "win32": "windows",
    "darwin": "macos",
    "linux": "linux",
}


def config_path() -> Path:
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override)
    return DEFAULT_CONFIG_PATH


@lru_cache(maxsize=1)
def _raw_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file is not a TOML table: {path}")
    return data


def clear_config_cache() -> None:
    _raw_config.cache_clear()


def _table(name: str) -> dict[str, Any]:
    value = _raw_config().get(name)
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid [{name}] section in {config_path()}")
    return value


def _string(table_name: str, key: str) -> str:
    table = _table(table_name)
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid {table_name}.{key} in {config_path()}")
    return value.strip()


def _int(table_name: str, key: str) -> int:
    table = _table(table_name)
    value = table.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Missing or invalid {table_name}.{key} in {config_path()}")
    return value


def _float(table_name: str, key: str) -> float:
    table = _table(table_name)
    value = table.get(key)
    if isinstance(value, int):
        return float(value)
    if not isinstance(value, float):
        raise ValueError(f"Missing or invalid {table_name}.{key} in {config_path()}")
    return value


def platform_key(platform_name: str | None = None) -> str:
    raw = platform_name or sys.platform
    if raw.startswith("linux"):
        return "linux"
    key = PLATFORM_KEYS.get(raw)
    if key is None:
        raise ValueError(f"Unsupported platform: {raw}")
    return key


def windows_share_root() -> str:
    return PureWindowsPath(_string("paths", "windows")).as_posix()


def local_storage_root(platform_name: str | None = None) -> Path:
    key = platform_key(platform_name)
    raw_path = _string("paths", key)
    if key == "windows":
        return Path(str(PureWindowsPath(raw_path)))
    return Path(raw_path).expanduser()


def tektronix_host() -> str:
    return _string("tektronix", "host")


def tektronix_port() -> int:
    return _int("tektronix", "port")


def tektronix_inrush_path() -> str:
    return _string("tektronix", "inrush_path")


def tektronix_max_io_path() -> str:
    return _string("tektronix", "max_io_path")


def tektronix_max_io_dt_path() -> str:
    return _string("tektronix", "max_io_dt_path")


def watlow_port() -> str:
    return _string("watlow", "port")


def watlow_baudrate() -> int:
    return _int("watlow", "baudrate")


def watlow_bytesize() -> int:
    return _int("watlow", "bytesize")


def watlow_parity() -> str:
    return _string("watlow", "parity")


def watlow_stopbits() -> int:
    return _int("watlow", "stopbits")


def watlow_unit_id() -> int:
    return _int("watlow", "unit_id")


def watlow_timeout_s() -> float:
    return _float("watlow", "timeout_s")


def watlow_retries() -> int:
    return _int("watlow", "retries")


def watlow_word_order() -> str:
    return _string("watlow", "word_order")


def watlow_data_map() -> int:
    return _int("watlow", "data_map")
