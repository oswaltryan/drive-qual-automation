from __future__ import annotations

from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core import config

EXPECTED_TEKTRONIX_PORT = 4000
EXPECTED_WINDOWS_ROOT = "Y:\\"


def test_config_reads_platform_paths_from_toml(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "drive_qual.toml"
    config_path.write_text(
        """
[paths]
windows = "Y:/"
macos = "/Volumes/LAB_SHARE"
linux = "/srv/lab-share"

[tektronix]
host = "192.168.10.25"
port = 4000
inrush_path = "C:/custom/inrush"
max_io_path = "C:/custom/maxio"
max_io_dt_path = "C:/custom/maxio_dt"

[watlow]
port = "COM7"
baudrate = 19200
bytesize = 8
parity = "E"
stopbits = 1
unit_id = 2
timeout_s = 2.5
retries = 4
word_order = "high-low"
data_map = 3
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("DRIVE_QUAL_CONFIG", str(config_path))
    config.clear_config_cache()

    assert config.windows_share_root() == "Y:/"
    assert str(config.local_storage_root("win32")) == EXPECTED_WINDOWS_ROOT
    assert config.local_storage_root("darwin") == Path("/Volumes/LAB_SHARE")
    assert config.local_storage_root("linux") == Path("/srv/lab-share")
    assert config.tektronix_host() == "192.168.10.25"
    assert config.tektronix_port() == EXPECTED_TEKTRONIX_PORT
    assert config.watlow_port() == "COM7"
    assert config.watlow_word_order() == "high-low"

    config.clear_config_cache()
