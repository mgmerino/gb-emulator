import pytest
from conftest import FakeCartridge

from gameboy import memory_map
from gameboy.memory import Bus

# ---------------------------------------------------------------------------
# Console RAM
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("address", [0xC000, 0xDFFF])
def test_wram_round_trips(bus: Bus, address: int) -> None:
    bus.write(address, 0xA7)

    assert bus.read(address) == 0xA7


def test_wram_banks_do_not_alias(bus: Bus) -> None:
    # Regression for the first bug: bank 1 was indexed as if it started at 0,
    # so the second write landed on top of the first.
    bus.write(0xC000, 0xFA)
    bus.write(0xD000, 0xAC)

    assert bus.read(0xC000) == 0xFA
    assert bus.read(0xD000) == 0xAC


def test_hram_round_trips(bus: Bus) -> None:
    bus.write(0xFF80, 0xBA)
    bus.write(0xFFFE, 0x67)

    assert bus.read(0xFF80) == 0xBA
    assert bus.read(0xFFFE) == 0x67


def test_interrupt_enable_round_trips(bus: Bus) -> None:
    bus.write(memory_map.INTERRUPT_ENABLE, 0x1F)

    assert bus.read(memory_map.INTERRUPT_ENABLE) == 0x1F


def test_interrupt_enable_is_not_hram(bus: Bus) -> None:
    # Regression for the second bug: a truthy guard made this branch match
    # everything below it.
    last_hram = memory_map.HRAM.stop - 1  # 0xFFFE, byte next to IE flag

    bus.write(memory_map.INTERRUPT_ENABLE, 0x1F)
    bus.write(last_hram, 0x5A)

    assert bus.read(memory_map.INTERRUPT_ENABLE) == 0x1F
    assert bus.read(last_hram) == 0x5A
    assert bus.read(memory_map.PROHIBITED.start) == memory_map.PROHIBITED_READ


# ---------------------------------------------------------------------------
# Echo RAM
# ---------------------------------------------------------------------------


def test_echo_mirrors_wram(bus: Bus) -> None:
    # Write at 0xC000, read at 0xE000. Then the other direction: write at
    # 0xE000, read at 0xC000. Both must work; the mirror is not read-only.
    bus.write(0xC000, 0xAF)
    value_mirror = bus.read(0xE000)

    assert value_mirror == 0xAF

    bus.write(0xE000, 0xEE)
    value_mirror = bus.read(0xC000)

    assert value_mirror == 0xEE


def test_echo_ends_before_the_top_of_wram(bus: Bus) -> None:
    # Echo covers 0xE000-0xFDFF, which mirrors 0xC000-0xDDFF only. The last 512
    # bytes of WRAM (0xDE00-0xDFFF) have no mirror.
    assert memory_map.ECHO_RAM.stop - 1 - memory_map.ECHO_OFFSET == 0xDDFF

    # The last mirrored pair (0xFDFF <-> 0xDDFF) works,
    bus.write(0xFDFF, 0xA7)
    assert bus.read(0xDDFF) == 0xA7

    # and 0xDE00 is reachable through WRAM but has no echo address. The address
    # that *would* mirror it if the window were bigger is 0xFE00, which belongs
    # to OAM. Seed OAM first so the assertion below is not against zero.
    bus.write(0xFE00, 0x11)
    bus.write(0xDE00, 0xD2)

    assert bus.read(0xDE00) == 0xD2  # reachable through WRAM
    assert bus.read(0xFE00) == 0x11  # untouched, so 0xFE00 is not its mirror


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


def test_bus_delegates_cartridge_reads(fake_bus: tuple[Bus, FakeCartridge]) -> None:
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


def test_bus_delegates_cartridge_writes(fake_bus: tuple[Bus, FakeCartridge]) -> None:
    # The bus must hand ROM writes to the cartridge rather than drop them:
    # 0x2100 is the MBC1 ROM-bank register, so from Step 15 on, swallowing it
    # here means the game never switches banks.
    bus, device = fake_bus
    pairs = [
        (memory_map.ROM_BANK_0.start, 0x01),
        (0x2100, 0x0A),
        (memory_map.ROM_BANK_1.start, 0x02),
        (memory_map.EXTERNAL_RAM.start, 0x0B),
        (memory_map.EXTERNAL_RAM.stop - 1, 0x0C),
    ]

    for address, value in pairs:
        bus.write(address, value)

    assert device.writes == pairs


def test_rom_writes_are_ignored(bus: Bus) -> None:
    # A ROM_ONLY cartridge has no mapper, so the write goes nowhere. It must
    # never raise and never change what the ROM reads back.
    bus.write(0x0000, 0xAF)
    bus.write(0x4000, 0xAF)
    bus.write(0x7FFF, 0xAF)

    assert bus.read(0x0000) == 0xAA
    assert bus.read(0x4000) == 0xCC
    assert bus.read(0x7FFF) == 0xDD


# ---------------------------------------------------------------------------
# PPU and I/O placeholders
# ---------------------------------------------------------------------------


def test_vram_round_trip(bus: Bus) -> None:
    bus.write(0x8000, 0x34)
    bus.write(0x9FFF, 0x12)

    assert bus.read(0x8000) == 0x34
    assert bus.read(0x9FFF) == 0x12


def test_oam_round_trip(bus: Bus) -> None:
    bus.write(0xFE00, 0x34)
    bus.write(0xFE9F, 0x12)

    assert bus.read(0xFE00) == 0x34
    assert bus.read(0xFE9F) == 0x12


def test_io_round_trip(bus: Bus) -> None:
    bus.write(0xFF00, 0x76)
    bus.write(0xFF7F, 0x67)

    assert bus.read(0xFF00) == 0x76
    assert bus.read(0xFF7F) == 0x67


def test_prohibited_region_reads_a_constant(bus: Bus) -> None:
    assert bus.read(0xFEA0) == memory_map.PROHIBITED_READ
    assert bus.read(0xFEFF) == memory_map.PROHIBITED_READ


def test_prohibited_writes_are_dropped(bus: Bus) -> None:
    # The region must not quietly acquire storage: a write is accepted (no
    # raise) and changes nothing.
    bus.write(0xFEA0, 0x5A)
    bus.write(0xFEFF, 0x5A)

    assert bus.read(0xFEA0) == memory_map.PROHIBITED_READ
    assert bus.read(0xFEFF) == memory_map.PROHIBITED_READ


# ---------------------------------------------------------------------------
# Addressing rules
# ---------------------------------------------------------------------------


def test_addresses_are_masked_to_16_bits(bus: Bus) -> None:
    # read(0x10000) is read(0x0000); read(-1) is read(0xFFFF). Seed IE first so
    # the second assertion is not 0 == 0, which would pass either way.
    bus.write(memory_map.INTERRUPT_ENABLE, 0x1F)

    assert bus.read(-1) == 0x1F
    assert bus.read(0x10000) == 0xAA

    # The write path masks too.
    bus.write(0x1C000, 0x42)

    assert bus.read(0xC000) == 0x42


def test_written_values_are_masked_to_8_bits(bus: Bus) -> None:
    # 0xA5 rather than 0xFF: 0xFF is also OPEN_BUS, so a bug that routed this
    # address to the catch-all branch would pass a test expecting 0xFF.
    bus.write(0xC000, 0x1A5)

    assert bus.read(0xC000) == 0xA5


def test_every_address_returns_a_byte(bus: Bus) -> None:
    for address in range(0x10000):
        assert 0 <= bus.read(address) <= 0xFF


def test_every_address_accepts_a_write(bus: Bus) -> None:
    # The mirror of the sweep above. An off-by-one in any region offset is an
    # IndexError here, and only here.
    for address in range(0x10000):
        bus.write(address, 0xFF)

    assert bus.read(0xC000) == 0xFF
    assert bus.read(memory_map.INTERRUPT_ENABLE) == 0xFF


# ---------------------------------------------------------------------------
# 16-bit access
# ---------------------------------------------------------------------------


def test_read16_is_little_endian(bus: Bus) -> None:
    bus.write(0xC000, 0x34)
    bus.write(0xC001, 0x12)

    assert bus.read16(0xC000) == 0x1234


def test_write16_then_read16_round_trips(bus: Bus) -> None:
    # Assert the two individual bytes afterwards, so the test still fails if
    # write16 and read16 are wrong in the same direction and cancel out. A pure
    # round-trip cannot catch that.
    bus.write16(0xC001, 0x0FA1)

    assert bus.read16(0xC001) == 0x0FA1
    assert bus.read(0xC001) == 0xA1
    assert bus.read(0xC002) == 0x0F


def test_read16_wraps_at_the_top_of_memory(bus: Bus) -> None:
    # read16(0xFFFF) reads 0xFFFF (IE) as the low byte and 0x0000 (ROM) as the
    # high byte. Whether that is *correct* is question 4 in STEP_03.md; this
    # test just pins the behaviour you chose, so a future change is deliberate.
    # Is wrapping the right behaviour, or should it be an error? What does real
    # hardware do, and does any real program depend on it?
    bus.write(memory_map.INTERRUPT_ENABLE, 0x1F)

    assert bus.read16(0xFFFF) == 0xAA1F
    assert bus.read16(0x0000) == 0xAA


def test_write16_wraps_at_the_top_of_memory(bus: Bus) -> None:
    # The low byte lands in IE, the high byte at 0x0000, where ROM drops it.
    bus.write16(0xFFFF, 0x1234)

    assert bus.read(memory_map.INTERRUPT_ENABLE) == 0x34
    assert bus.read(0x0000) == 0xAA
