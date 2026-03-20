from __future__ import annotations

import contextlib
import importlib
import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from drive_qual.core.config import (
    watlow_baudrate,
    watlow_bytesize,
    watlow_data_map,
    watlow_parity,
    watlow_port,
    watlow_retries,
    watlow_stopbits,
    watlow_timeout_s,
    watlow_unit_id,
    watlow_word_order,
)


class ModbusResponse(Protocol):
    registers: list[int]

    def isError(self) -> bool: ...


class ModbusClient(Protocol):
    def connect(self) -> bool: ...
    def close(self) -> object: ...
    def read_holding_registers(self, *, address: int, count: int, device_id: int) -> ModbusResponse: ...


class ModbusSerialClientConstructor(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> ModbusClient: ...


# CONFIG
#################################################
PORT = watlow_port()
# Modbus RTU defaults (pmpmintegrated.pdf pages 150-151).
BAUDRATE = watlow_baudrate()
BYTESIZE = watlow_bytesize()
PARITY = watlow_parity()
STOPBITS = watlow_stopbits()
UNIT_ID = watlow_unit_id()
TIMEOUT_S = watlow_timeout_s()
RETRIES = watlow_retries()
WORD_ORDER: Literal["low-high", "high-low"] = cast(Literal["low-high", "high-low"], watlow_word_order())
DATA_MAP = watlow_data_map()

# Default assembly layout (pmpmintegrated.pdf pages 237-238)
POINTER_REGISTER_BASE = 40
WORKING_REGISTER_BASE = 200
POINTER_COUNT = 40
REGISTERS_PER_POINTER = 2


def _modbus_serial_client_class() -> ModbusSerialClientConstructor:
    client_module = importlib.import_module("pymodbus.client")
    return cast(ModbusSerialClientConstructor, client_module.ModbusSerialClient)


@dataclass(frozen=True)
class WatlowPointer:
    index: int
    name: str
    address: int
    pointer_register_pair: tuple[int, int]
    working_register_pair: tuple[int, int]


@dataclass(frozen=True)
class RegisterPairValue:
    word1: int
    word2: int

    def as_u32(self, *, word_order: Literal["low-high", "high-low"] = WORD_ORDER) -> int:
        if word_order == "low-high":
            low, high = self.word1, self.word2
        else:
            high, low = self.word1, self.word2
        return (high << 16) | low

    def as_s32(self, *, word_order: Literal["low-high", "high-low"] = WORD_ORDER) -> int:
        value = self.as_u32(word_order=word_order)
        return value - 0x1_0000_0000 if value & 0x8000_0000 else value

    def as_f32(self, *, word_order: Literal["low-high", "high-low"] = WORD_ORDER) -> float:
        packed = struct.pack(">I", self.as_u32(word_order=word_order))
        return float(struct.unpack(">f", packed)[0])


@dataclass(frozen=True)
class SerialSettings:
    baudrate: int = BAUDRATE
    bytesize: int = BYTESIZE
    parity: str = PARITY
    stopbits: int = STOPBITS
    timeout_s: float = TIMEOUT_S
    retries: int = RETRIES


def _pair(start: int) -> tuple[int, int]:
    return start, start + 1


def _pointer_register_pair(index: int) -> tuple[int, int]:
    start = POINTER_REGISTER_BASE + (index - 1) * REGISTERS_PER_POINTER
    return _pair(start)


def _working_register_pair(index: int) -> tuple[int, int]:
    start = WORKING_REGISTER_BASE + (index - 1) * REGISTERS_PER_POINTER
    return _pair(start)


DEFAULT_POINTERS: tuple[WatlowPointer, ...] = (
    WatlowPointer(1, "Loop Control Mode", 1880, _pointer_register_pair(1), _working_register_pair(1)),
    WatlowPointer(2, "Set Point", 2160, _pointer_register_pair(2), _working_register_pair(2)),
    WatlowPointer(3, "Manual Power", 2162, _pointer_register_pair(3), _working_register_pair(3)),
    WatlowPointer(4, "Alarm 1 High Set Point", 1480, _pointer_register_pair(4), _working_register_pair(4)),
    WatlowPointer(5, "Alarm 1 Low Set Point", 1482, _pointer_register_pair(5), _working_register_pair(5)),
    WatlowPointer(6, "Alarm 2 High Set Point", 1530, _pointer_register_pair(6), _working_register_pair(6)),
    WatlowPointer(7, "Alarm 2 Low Set Point", 1532, _pointer_register_pair(7), _working_register_pair(7)),
    WatlowPointer(8, "Alarm 3 High Set Point", 1580, _pointer_register_pair(8), _working_register_pair(8)),
    WatlowPointer(9, "Alarm 3 Low Set Point", 1582, _pointer_register_pair(9), _working_register_pair(9)),
    WatlowPointer(10, "Alarm 4 High Set Point", 1630, _pointer_register_pair(10), _working_register_pair(10)),
    WatlowPointer(11, "Alarm 4 Low Set Point", 1632, _pointer_register_pair(11), _working_register_pair(11)),
    WatlowPointer(12, "Profile Action Request", 2540, _pointer_register_pair(12), _working_register_pair(12)),
    WatlowPointer(13, "Profile Start", 2520, _pointer_register_pair(13), _working_register_pair(13)),
    WatlowPointer(14, "Heat Proportional Band", 1890, _pointer_register_pair(14), _working_register_pair(14)),
    WatlowPointer(15, "Cool Proportional Band", 1892, _pointer_register_pair(15), _working_register_pair(15)),
    WatlowPointer(16, "Time Integral", 1894, _pointer_register_pair(16), _working_register_pair(16)),
    WatlowPointer(17, "Time Derivative", 1896, _pointer_register_pair(17), _working_register_pair(17)),
    WatlowPointer(18, "On/Off Heat Hysteresis", 1900, _pointer_register_pair(18), _working_register_pair(18)),
    WatlowPointer(19, "On/Off Cool Hysteresis", 1902, _pointer_register_pair(19), _working_register_pair(19)),
    WatlowPointer(20, "Deadband", 1898, _pointer_register_pair(20), _working_register_pair(20)),
    WatlowPointer(21, "Analog Input 1", 360, _pointer_register_pair(21), _working_register_pair(21)),
    WatlowPointer(22, "Analog Input 1 Error", 362, _pointer_register_pair(22), _working_register_pair(22)),
    WatlowPointer(23, "Analog Input 2", 440, _pointer_register_pair(23), _working_register_pair(23)),
    WatlowPointer(24, "Analog Input 2 Error", 442, _pointer_register_pair(24), _working_register_pair(24)),
    WatlowPointer(25, "Alarm 1 State", 1496, _pointer_register_pair(25), _working_register_pair(25)),
    WatlowPointer(26, "Alarm 2 State", 1546, _pointer_register_pair(26), _working_register_pair(26)),
    WatlowPointer(27, "Alarm 3 State", 1596, _pointer_register_pair(27), _working_register_pair(27)),
    WatlowPointer(28, "Alarm 4 State", 1646, _pointer_register_pair(28), _working_register_pair(28)),
    WatlowPointer(29, "Digital Input 5 Status", 1328, _pointer_register_pair(29), _working_register_pair(29)),
    WatlowPointer(30, "Digital Input 6 Status", 1348, _pointer_register_pair(30), _working_register_pair(30)),
    WatlowPointer(31, "Control Mode Active", 1882, _pointer_register_pair(31), _working_register_pair(31)),
    WatlowPointer(32, "Heat Power", 1904, _pointer_register_pair(32), _working_register_pair(32)),
    WatlowPointer(33, "Cool Power", 1906, _pointer_register_pair(33), _working_register_pair(33)),
    WatlowPointer(34, "Limit State", 690, _pointer_register_pair(34), _working_register_pair(34)),
    WatlowPointer(35, "Profile Start (Duplicate)", 2520, _pointer_register_pair(35), _working_register_pair(35)),
    WatlowPointer(
        36, "Profile Action Request (Duplicate)", 2540, _pointer_register_pair(36), _working_register_pair(36)
    ),
    WatlowPointer(37, "Active File", 2524, _pointer_register_pair(37), _working_register_pair(37)),
    WatlowPointer(38, "Active Step", 2526, _pointer_register_pair(38), _working_register_pair(38)),
    WatlowPointer(39, "Active Set Point", 2528, _pointer_register_pair(39), _working_register_pair(39)),
    WatlowPointer(40, "Step Time Remaining", 2536, _pointer_register_pair(40), _working_register_pair(40)),
)


@contextlib.contextmanager
def watlow_client(
    port: str = PORT,
    *,
    settings: SerialSettings | None = None,
) -> Iterator[ModbusClient]:
    resolved = settings or SerialSettings()
    client = _modbus_serial_client_class()(
        port=port,
        baudrate=resolved.baudrate,
        bytesize=resolved.bytesize,
        parity=resolved.parity,
        stopbits=resolved.stopbits,
        timeout=resolved.timeout_s,
        retries=resolved.retries,
    )
    try:
        if not client.connect():
            raise ConnectionError(f"Failed to connect to Watlow controller on {port}.")
        yield client
    finally:
        close_fn = cast(Callable[[], object] | None, getattr(client, "close", None))
        if close_fn is not None:
            close_fn()


def read_holding_registers(
    client: ModbusClient,
    address: int,
    count: int,
    *,
    unit_id: int = UNIT_ID,
    address_offset: int = 0,
) -> list[int] | None:
    """
    Read holding registers. Note: pymodbus uses 0-based register addressing by default.
    """
    adjusted_address = address + address_offset
    try:
        result = client.read_holding_registers(address=adjusted_address, count=count, device_id=unit_id)
    except OSError as exc:
        print(f"Modbus IO error reading {count} registers at {adjusted_address}: {exc}")
        return None
    if result.isError():
        print(f"Modbus error reading {count} registers at {adjusted_address}: {result}")
        return None
    return list(result.registers)


def read_default_assembly(
    client: ModbusClient,
    *,
    unit_id: int = UNIT_ID,
    address_offset: int = 0,
) -> dict[int, RegisterPairValue]:
    """
    Read the default assembly working registers (200-279) and return values keyed by pointer index.
    """
    count = POINTER_COUNT * REGISTERS_PER_POINTER
    registers = read_holding_registers(
        client,
        WORKING_REGISTER_BASE,
        count,
        unit_id=unit_id,
        address_offset=address_offset,
    )
    if registers is None:
        return {}

    values: dict[int, RegisterPairValue] = {}
    for pointer in DEFAULT_POINTERS:
        offset = (pointer.index - 1) * REGISTERS_PER_POINTER
        values[pointer.index] = RegisterPairValue(registers[offset], registers[offset + 1])
    return values


def read_default_assembly_by_name(
    client: ModbusClient,
    *,
    unit_id: int = UNIT_ID,
    address_offset: int = 0,
) -> dict[str, RegisterPairValue]:
    values_by_index = read_default_assembly(client, unit_id=unit_id, address_offset=address_offset)
    return {pointer.name: values_by_index.get(pointer.index, RegisterPairValue(0, 0)) for pointer in DEFAULT_POINTERS}
