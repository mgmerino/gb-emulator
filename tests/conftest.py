"""Shared fixtures.

pytest imports this file automatically for every test in this directory, so
nothing here needs to be imported by name. Fixtures are requested by putting
their name in a test's parameter list, which is pytest's answer to RSpec's
`let` and `subject`.
"""

import pytest

from gameboy.cartridge import Cartridge
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
