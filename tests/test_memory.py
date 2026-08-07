import pytest
from conftest import FakeCartridge

from gameboy import memory_map
from gameboy.memory import Bus

# ---------------------------------------------------------------------------
# Console RAM
# ---------------------------------------------------------------------------


def test_wram_banks_do_not_alias(bus: Bus) -> None:
    low = 0xC000 - memory_map.WRAM.start  # 0x0000
    high = 0xD000 - memory_map.WRAM.start # 0x1000

    # TODO: avoid coupling to internal representation, use write method when
    # implemented:
    bus.wram[low] = 0xFA
    bus.wram[high] = 0xAC

    assert bus.read(0xC000) == 0xFA
    assert bus.read(0xD000) == 0xAC

def test_hram_round_trips(bus: Bus) -> None:
    # TODO: avoid coupling to internal representation, use write method when
    # implemented:
    bus.hram[0] = 0xBA
    bus.hram[-1] = 0x67

    assert bus.read(0xFF80) == 0xBA
    assert bus.read(0xFFFE) == 0x67

def test_interrupt_enable_is_not_hram(bus: Bus) -> None:
    # Regression for the second bug: a truthy guard made this branch match
    # everything below it.
    last_hram = memory_map.HRAM.stop - 1  # 0xFFFE, byte next to IE flag

    bus.ie = 0x1F
    bus.hram[last_hram - memory_map.HRAM.start] = 0x5A

    assert bus.read(memory_map.INTERRUPT_ENABLE) == 0x1F
    assert bus.read(last_hram) == 0x5A
    assert bus.read(memory_map.PROHIBITED.start) == memory_map.PROHIBITED_READ


# ---------------------------------------------------------------------------
# The cartridge seam
# ---------------------------------------------------------------------------


def test_rom_reads_come_from_the_cartridge(bus: Bus) -> None:
    assert bus.read(0x0000) == 0xAA
    assert bus.read(0x1234) == 0xBB
    assert bus.read(0x4000) == 0xCC
    assert bus.read(0x7FFF) == 0xDD



def test_external_ram_reads_open_bus(bus: Bus) -> None:
    # A ROM_ONLY cartridge has no RAM chip, so 0xA000 and 0xBFFF read 0xFF.
    # Assert against memory_map.OPEN_BUS, not against the literal.
    assert bus.read(0xA000) == memory_map.OPEN_BUS
    assert bus.read(0xBFFF) == memory_map.OPEN_BUS


def test_bus_delegates_cartridge_regions(fake_bus: tuple[Bus, FakeCartridge]) -> None:
    bus, device = fake_bus
    addresses = [
        memory_map.ROM_BANK_0.start,
        memory_map.ROM_BANK_1.start,
        memory_map.EXTERNAL_RAM.start,
        memory_map.EXTERNAL_RAM.stop - 1,
    ]

    for address in addresses:
        assert bus.read(address) == device.value

    assert device.reads == addresses


# ---------------------------------------------------------------------------
# PPU and I/O placeholders
# ---------------------------------------------------------------------------


def test_vram_round_trip(bus: Bus) -> None:
    # TODO: avoid coupling to internal representation, use write method when
    # implemented:
    bus.vram[0] = 0x34
    bus.vram[-1] = 0x12

    assert bus.read(0x8000) == 0x34
    assert bus.read(0x9FFF) == 0x12

def test_oam_round_trip(bus: Bus) -> None:

    # TODO: avoid coupling to internal representation, use write method when
    # implemented:
    bus.oam[0] = 0x34
    bus.oam[-1] = 0x12

    assert bus.read(0xFE00) == 0x34
    assert bus.read(0xFE9F) == 0x12

def test_io_round_trip(bus: Bus) -> None:
    # TODO: avoid coupling to internal representation, use write method when
    # implemented:
    bus.io[0] = 0x76
    bus.io[-1] = 0x67

    assert bus.read(0xFF00) == 0x76
    assert bus.read(0xFF7F) == 0x67

def test_prohibited_region_reads_a_constant(bus: Bus) -> None:
    # 0xFEA0 and 0xFEFF both read memory_map.PROHIBITED_READ.
    # TODO: Writes are dropped without raising.
    assert bus.read(0xFEA0) == memory_map.PROHIBITED_READ
    assert bus.read(0xFEFF) == memory_map.PROHIBITED_READ


# ---------------------------------------------------------------------------
# Addressing rules
# ---------------------------------------------------------------------------


def test_addresses_are_masked_to_16_bits(bus: Bus) -> None:
    # read(0x10000) is read(0x0000); read(-1) is read(0xFFFF).
    assert bus.read(0x10000) == bus.read(0x0000)
    assert bus.read(-1) == bus.read(0xFFFF)


def test_every_address_returns_a_byte(bus: Bus) -> None:
    for address in range(0x10000):
        assert 0 <= bus.read(address) <= 0xFF


# ---------------------------------------------------------------------------
# 16-bit access
# ---------------------------------------------------------------------------


def test_read16_is_little_endian(bus: Bus) -> None:
    bus.wram[0] = 0x34 # low
    bus.wram[1] = 0x12 # high

    assert bus.read16(0xC000) == 0x1234


