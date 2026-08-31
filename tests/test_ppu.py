import pytest

from gameboy.bits import get_bit
from gameboy.memory_map import BGP, LCDC, LY, LYC, SCX, SCY, STAT
from gameboy.ppu import (
    PPU,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_DATA_UNSIGNED,
    TILE_MAP_0,
    TILE_SIZE,
    Mode,
)


@pytest.fixture
def ppu() -> PPU:
    return PPU()


def test_ppu_post_boot() -> None:
    ppu = PPU.post_boot()
    assert ppu.lcdc == 0x91
    assert ppu.bgp == 0xFC
    assert ppu.mode is Mode.VBLANK
    assert ppu.stat == 0x00  # the selects; STAT assembles 0x85 on read


def test_ppu_constants() -> None:
    assert len(PPU().framebuffer) == 23040
    assert SCREEN_WIDTH * SCREEN_HEIGHT == 23040
    assert TILE_SIZE == 16
    # 384 tiles between the unsigned base and the first map
    assert (TILE_MAP_0 - TILE_DATA_UNSIGNED) // TILE_SIZE == 384


@pytest.mark.parametrize(
    ("address", "attribute"),
    [
        (LCDC, "lcdc"),
        (SCY, "scy"),
        (SCX, "scx"),
        (LYC, "lyc"),
        (BGP, "bgp"),
    ],
)
def test_the_plain_registers_round_trip(ppu: PPU, address: int, attribute: str) -> None:
    ppu.write(address, 0x5A)

    assert ppu.read(address) == 0x5A
    # Reading back is not enough: all five could be landing on the same field.
    assert getattr(ppu, attribute) == 0x5A


def test_ly_reports_the_current_line(ppu: PPU) -> None:
    ppu.ly = 42

    assert ppu.read(LY) == 42


def test_ly_is_read_only(ppu: PPU) -> None:
    ppu.ly = 42

    ppu.write(LY, 0xFF)

    assert ppu.read(LY) == 42


def test_stat_bit_7_always_reads_set(ppu: PPU) -> None:
    assert get_bit(ppu.read(STAT), 7)


def test_stat_write_lands_only_on_the_selects(ppu: PPU) -> None:
    ppu.write(STAT, 0xFF)
    assert ppu.stat == 0b0111_1000


@pytest.mark.parametrize("mode", list(Mode))
def test_stat_reports_the_current_mode(ppu: PPU, mode: Mode) -> None:
    ppu.mode = mode

    assert ppu.read(STAT) & 0b11 == mode


def test_stat_reports_whether_ly_matches_lyc(ppu: PPU) -> None:
    ppu.ly = 7
    ppu.lyc = 7

    assert get_bit(ppu.read(STAT), 2)

    ppu.lyc = 8

    assert not get_bit(ppu.read(STAT), 2)


def test_stat_derives_the_low_bits_after_a_write_of_all_ones(ppu: PPU) -> None:
    # The acceptance criterion from task 2: writing 0xFF must not make bits 2-0
    # read back as the ones that were written.
    ppu.mode = Mode.DRAWING
    ppu.ly = 1
    ppu.lyc = 2

    ppu.write(STAT, 0xFF)

    assert ppu.read(STAT) == 0b1111_1011


def test_post_boot_stat_reads_the_documented_byte() -> None:
    # Theory section 8: 0x85 is what a ROM reads, not what the field holds.
    assert PPU.post_boot().read(STAT) == 0x85


def test_reading_an_address_the_ppu_does_not_own_is_open_bus(ppu: PPU) -> None:
    assert ppu.read(0xFF46) == 0xFF  # DMA, Step 12
