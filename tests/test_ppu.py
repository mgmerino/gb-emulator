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


# --- task 3: the dot counter and the mode machine ---------------------------


@pytest.mark.parametrize(
    ("dots", "expected"),
    [
        (0, Mode.OAM_SCAN),
        (79, Mode.OAM_SCAN),  # last dot of mode 2
        (80, Mode.DRAWING),  # first dot of mode 3
        (251, Mode.DRAWING),  # last dot of mode 3, 80 + 172 - 1
        (252, Mode.HBLANK),  # first dot of mode 0
        (455, Mode.HBLANK),  # last dot of the line
    ],
)
def test_the_mode_follows_the_position_within_a_line(
    ppu: PPU, dots: int, expected: Mode
) -> None:
    ppu.tick(dots)

    assert ppu.mode is expected


def test_a_scanline_is_456_dots(ppu: PPU) -> None:
    ppu.tick(456)

    assert ppu.ly == 1
    assert ppu.dots == 0


def test_the_dot_counter_carries_into_the_next_line(ppu: PPU) -> None:
    ppu.tick(400)
    ppu.tick(100)

    assert ppu.ly == 1
    assert ppu.dots == 44


def test_vblank_begins_on_line_144(ppu: PPU) -> None:
    ppu.tick(456 * 144)

    assert ppu.ly == 144
    assert ppu.mode is Mode.VBLANK


def test_a_whole_frame_returns_to_the_top(ppu: PPU) -> None:
    for _ in range(70224 // 4):
        ppu.tick(4)

    assert ppu.ly == 0
    assert ppu.dots == 0
    assert ppu.mode is Mode.OAM_SCAN


def test_ly_wraps_after_the_last_line(ppu: PPU) -> None:
    ppu.tick(456 * 153)

    assert ppu.ly == 153

    ppu.tick(456)

    assert ppu.ly == 0


def test_a_tick_longer_than_a_line_advances_several_lines(ppu: PPU) -> None:
    ppu.ly = 0
    ppu.tick(456 * 3 + 3)

    assert ppu.ly == 3
    assert ppu.dots == 3
