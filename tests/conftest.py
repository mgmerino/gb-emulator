"""Shared fixtures.

pytest imports this file automatically for every test in this directory, so
nothing here needs to be imported by name. Fixtures are requested by putting
their name in a test's parameter list, which is pytest's answer to RSpec's
`let` and `subject`.
"""

from typing import Protocol

import pytest

from gameboy.bits import high_byte, join_bytes, low_byte
from gameboy.cartridge import Cartridge
from gameboy.cpu import CPU, Registers
from gameboy.encoding import Operand
from gameboy.memory import Bus


class FakeCartridge:
    """A minimal `MemoryDevice` that records what the bus asked it for.

    The bus is typed against the `MemoryDevice` protocol, not against
    `Cartridge`, so this class needs no inheritance and no registration: having
    `read` and `write` with the right signatures is the whole contract.

    Use it when the test is about *routing* (did the bus delegate?) rather than
    about ROM contents.
    """

    def __init__(self, value: int = 0x11) -> None:
        self.value = value
        self.reads: list[int] = []
        self.writes: list[tuple[int, int]] = []

    def read(self, address: int) -> int:
        self.reads.append(address)
        return self.value

    def write(self, address: int, value: int) -> None:
        self.writes.append((address, value))

    def read16(self, address: int) -> int:
        return join_bytes(self.read(address + 1), self.read(address))

    def write16(self, address: int, value: int) -> None:
        self.write(address, low_byte(value))
        self.write(address + 1, high_byte(value))


class FlatMemory:
    """64 KiB of RAM with no regions and no rules."""

    def __init__(self) -> None:
        self.data = bytearray(0x10000)

    def read(self, address: int) -> int:
        return self.data[address]

    def write(self, address: int, value: int) -> None:
        self.data[address] = value

    def read16(self, address: int) -> int:
        return join_bytes(self.read(address + 1), self.read(address))

    def write16(self, address: int, value: int) -> None:
        self.write(address, low_byte(value))
        self.write(address + 1, high_byte(value))


@pytest.fixture
def rom() -> bytes:
    """A 32 KiB image of zeros, with a couple of recognisable bytes in ROM.

    An all-zero image parses as a valid ROM_ONLY / DMG header, so the bus tests
    do not need `build_rom` from test_cartridge.py. That is a fact worth
    noticing: the bus depends on `MemoryDevice`, so header parsing is not part
    of its test surface.
    """
    image = bytearray(0x8000)
    image[0x0000] = 0xAA  # first byte of bank 0
    image[0x1234] = 0xBB  # somewhere in the middle of bank 0
    image[0x4000] = 0xCC  # first byte of bank 1
    image[0x7FFF] = 0xDD  # last byte of ROM
    return bytes(image)


@pytest.fixture
def cartridge(rom: bytes) -> Cartridge:
    """A real cartridge over the synthetic ROM above.

    Note this fixture takes `rom` as a parameter: fixtures request other
    fixtures the same way tests do.
    """
    return Cartridge.from_bytes(rom)


@pytest.fixture
def bus(cartridge: Cartridge) -> Bus:
    """A bus over a real cartridge. The default for most tests."""
    return Bus(cartridge)


@pytest.fixture
def fake_bus() -> tuple[Bus, FakeCartridge]:
    """A bus over a fake device, plus the device, for routing assertions.

    Returning a tuple is fine, but consider whether you would rather have two
    fixtures and let the test request both. Try it and see which reads better.
    """
    device = FakeCartridge()
    return Bus(device), device


@pytest.fixture
def registers() -> Registers:
    return Registers()


class CpuRunning(Protocol):
    """The call signature of the `cpu_running` fixture.

    `Callable[..., CPU]` cannot express a keyword argument, so `at=` would go
    unchecked. A Protocol with `__call__` can.
    """

    def __call__(self, *program: int, at: int = ...) -> CPU: ...


@pytest.fixture
def cpu_running() -> CpuRunning:
    """A CPU whose PC points at `program`, loaded in flat memory.
    Takes opcode bytes so a test reads like an assembler listing:

        cpu = cpu_running(0xC3, 0x50, 0x01)   # JP 0x0150

    Writes wrap with `& 0xFFFF`, so a program can start at the top of memory and
    run off the end.
    """

    def _cpu_running(*program: int, at: int = 0x0100) -> CPU:
        memory = FlatMemory()
        for offset, byte in enumerate(program):
            memory.data[(at + offset) & 0xFFFF] = byte
        registers = Registers()
        registers.pc = at
        return CPU(memory, registers)

    return _cpu_running


REGISTER_OPERANDS = [
    Operand.B,
    Operand.C,
    Operand.D,
    Operand.E,
    Operand.H,
    Operand.L,
    Operand.A,
]
