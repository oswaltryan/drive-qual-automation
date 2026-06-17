from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import datetime

DEFAULT_F4T_IP = "169.254.79.43"
SCPI_PORT = 5025
DEFAULT_TIMEOUT_S = 3.0
DEFAULT_WRITE_HOLD_SECONDS = 2.0
TEMPERATURE_UNITS_QUERY = ":UNIT:TEMPerature?"
PROCESS_VALUE_QUERY = ":SOURce:CLOop1:PVALue?"
SETPOINT_QUERY = ":SOURce:CLOop1:SPOint?"
SETPOINT_COMMAND_TEMPLATE = ":SOURce:CLOop1:SPOint {value}"
RECV_BYTES = 4096


@dataclass(frozen=True)
class TemperatureReading:
    timestamp: str
    temperature_c: float
    temperature_f: float


@dataclass(frozen=True)
class F4TSnapshot:
    timestamp: str
    temperature_c: float
    temperature_f: float
    setpoint_c: float


@dataclass(frozen=True)
class F4TController:
    ip: str = DEFAULT_F4T_IP
    timeout_s: float = DEFAULT_TIMEOUT_S
    write_hold_seconds: float = DEFAULT_WRITE_HOLD_SECONDS

    def query(self, query: str) -> str:
        with socket.create_connection((self.ip, SCPI_PORT), timeout=self.timeout_s) as conn:
            conn.settimeout(self.timeout_s)
            return _query_connection(conn, query)

    def command(self, command: str) -> None:
        with socket.create_connection((self.ip, SCPI_PORT), timeout=self.timeout_s) as conn:
            conn.settimeout(self.timeout_s)
            conn.sendall(_scpi_line(command))
            time.sleep(self.write_hold_seconds)

    def read_temperature(self) -> TemperatureReading:
        with socket.create_connection((self.ip, SCPI_PORT), timeout=self.timeout_s) as conn:
            conn.settimeout(self.timeout_s)
            units = normalize_units(_query_connection(conn, TEMPERATURE_UNITS_QUERY))
            measured = parse_temperature(_query_connection(conn, PROCESS_VALUE_QUERY))
        return _temperature_reading(measured, units)

    def read_setpoint_c(self) -> float:
        with socket.create_connection((self.ip, SCPI_PORT), timeout=self.timeout_s) as conn:
            conn.settimeout(self.timeout_s)
            units = normalize_units(_query_connection(conn, TEMPERATURE_UNITS_QUERY))
            measured = parse_temperature(_query_connection(conn, SETPOINT_QUERY))
        return to_celsius(measured, units)

    def read_snapshot(self) -> F4TSnapshot:
        with socket.create_connection((self.ip, SCPI_PORT), timeout=self.timeout_s) as conn:
            conn.settimeout(self.timeout_s)
            units = normalize_units(_query_connection(conn, TEMPERATURE_UNITS_QUERY))
            measured = parse_temperature(_query_connection(conn, PROCESS_VALUE_QUERY))
            setpoint = parse_temperature(_query_connection(conn, SETPOINT_QUERY))
        reading = _temperature_reading(measured, units)
        return F4TSnapshot(
            timestamp=reading.timestamp,
            temperature_c=reading.temperature_c,
            temperature_f=reading.temperature_f,
            setpoint_c=to_celsius(setpoint, units),
        )

    def write_setpoint_c(self, setpoint_c: float) -> None:
        command = SETPOINT_COMMAND_TEMPLATE.format(value=f"{setpoint_c:.3f}")
        self.command(command)


def _scpi_line(command: str) -> bytes:
    return (command.strip() + "\n").encode("ascii")


def _query_connection(conn: socket.socket, query: str) -> str:
    conn.sendall(_scpi_line(query))
    response = conn.recv(RECV_BYTES).decode("ascii", errors="replace").strip()
    if not response:
        raise RuntimeError(f"Empty response for SCPI query: {query}")
    return response


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _temperature_reading(value: float, units: str) -> TemperatureReading:
    return TemperatureReading(
        timestamp=_timestamp(),
        temperature_c=to_celsius(value, units),
        temperature_f=to_fahrenheit(value, units),
    )


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
