from __future__ import annotations

import csv
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_F4T_IP = "169.254.79.42"
SCPI_PORT = 5025
DEFAULT_INTERVAL_SECONDS = 5.0


@dataclass(frozen=True)
class TemperatureReading:
    timestamp: str
    temperature_c: float
    temperature_f: float


@contextmanager
def f4t_connection(ip: str = DEFAULT_F4T_IP, *, timeout_s: float = 3.0) -> Iterator[socket.socket]:
    with socket.create_connection((ip, SCPI_PORT), timeout=timeout_s) as conn:
        conn.settimeout(timeout_s)
        yield conn


def scpi_query(conn: socket.socket, query: str) -> str:
    conn.sendall((query.strip() + "\n").encode("ascii"))
    return conn.recv(4096).decode("ascii", errors="replace").strip()


def poll_temperature(conn: socket.socket) -> TemperatureReading:
    units = normalize_units(scpi_query(conn, ":UNIT:TEMPERATURE?"))
    measured = parse_temperature(scpi_query(conn, ":SOURce:CLOop1:PVALue?"))
    temp_c = to_celsius(measured, units)
    temp_f = to_fahrenheit(measured, units)
    return TemperatureReading(
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        temperature_c=temp_c,
        temperature_f=temp_f,
    )


def ensure_temperature_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    with path.open("w", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(["timestamp", "temperature_c", "temperature_f"])


def append_temperature_reading(path: Path, reading: TemperatureReading) -> None:
    with path.open("a", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        writer.writerow([reading.timestamp, f"{reading.temperature_c:.3f}", f"{reading.temperature_f:.3f}"])


def parse_temperature(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"Unexpected temperature response: {value!r}") from exc


def normalize_units(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"C", "CELSIUS", "DEGC", "DEG C"}:
        return "C"
    if normalized in {"F", "FAHRENHEIT", "DEGF", "DEG F"}:
        return "F"
    raise RuntimeError(f"Unexpected unit response: {value!r}")


def to_celsius(value: float, units: str) -> float:
    if units == "C":
        return value
    return (value - 32.0) * 5.0 / 9.0


def to_fahrenheit(value: float, units: str) -> float:
    if units == "F":
        return value
    return value * 9.0 / 5.0 + 32.0
