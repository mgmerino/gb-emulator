import pytest

from gameboy.bits import get_bit
from gameboy.cartridge import Cartridge
from gameboy.interrupts import Interrupt
from gameboy.memory import Bus
from gameboy.memory_map import (
    BGP,
    DIVIDER,
    INTERRUPT_FLAG,
    LCDC,
    LY,
    LYC,
    SCX,
    SCY,
    STAT,
)
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


@pytest.fixture
def running() -> PPU:
    """A PPU with the LCD on, which every timing test needs from task 5 onward."""
    return PPU(lcdc=0x91)


def run_dots(ppu: PPU, dots: int, step: int = 4) -> list[Interrupt]:
    """Tick `dots` in bus-sized steps, collecting every interrupt raised."""
    raised: list[Interrupt] = []
    for _ in range(dots // step):
        raised.extend(ppu.tick(step))

    return raised


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
    running: PPU, dots: int, expected: Mode
) -> None:
    running.tick(dots)

    assert running.mode is expected


def test_a_scanline_is_456_dots(running: PPU) -> None:
    running.tick(456)

    assert running.ly == 1
    assert running.dots == 0


def test_the_dot_counter_carries_into_the_next_line(running: PPU) -> None:
    running.tick(400)
    running.tick(100)

    assert running.ly == 1
    assert running.dots == 44


def test_vblank_begins_on_line_144(running: PPU) -> None:
    running.tick(456 * 144)

    assert running.ly == 144
    assert running.mode is Mode.VBLANK


def test_a_whole_frame_returns_to_the_top(running: PPU) -> None:
    for _ in range(70224 // 4):
        running.tick(4)

    assert running.ly == 0
    assert running.dots == 0
    assert running.mode is Mode.OAM_SCAN


def test_ly_wraps_after_the_last_line(running: PPU) -> None:
    running.tick(456 * 153)

    assert running.ly == 153

    running.tick(456)

    assert running.ly == 0


def test_a_tick_longer_than_a_line_advances_several_lines(running: PPU) -> None:
    running.ly = 0
    running.tick(456 * 3 + 3)

    assert running.ly == 3
    assert running.dots == 3


# --- task 4: the two interrupts ---------------------------------------------


def test_vblank_is_raised_once_per_frame(running: PPU) -> None:
    raised = run_dots(running, 70224)

    assert raised.count(Interrupt.VBLANK) == 1


def test_a_completed_frame_increments_the_counter(running: PPU) -> None:
    assert running.frames == 0

    run_dots(running, 70224)

    assert running.frames == 1


def test_the_mode_0_select_fires_once_per_visible_line(running: PPU) -> None:
    running.stat = 0b0000_1000  # mode 0 select
    running.lyc = 200  # never reached, so LYC never contributes to the OR

    raised = run_dots(running, 70224)

    assert raised.count(Interrupt.LCD_STAT) == 144


def test_stat_blocking_collapses_two_conditions_into_one(running: PPU) -> None:
    # LYC is already true when mode 0 arrives, so the OR line never goes low in
    # between and the second condition raises nothing.
    running.stat = 0b0100_1000  # LYC select and mode 0 select
    running.lyc = 0

    raised = run_dots(running, 456)  # line 0 only

    assert raised.count(Interrupt.LCD_STAT) == 1


def test_no_selects_means_no_stat_interrupts(running: PPU) -> None:
    raised = run_dots(running, 70224)

    assert Interrupt.LCD_STAT not in raised
    assert Interrupt.VBLANK in raised


def test_the_stat_interrupt_fires_on_the_rising_edge(running: PPU) -> None:
    # Stop inside mode 0 without leaving the line. A falling-edge detector sees
    # nothing yet; a rising-edge one has already fired on the entry into mode 0.
    running.stat = 0b0000_1000
    running.lyc = 200

    raised = run_dots(running, 300)

    assert raised.count(Interrupt.LCD_STAT) == 1


# --- task 5: turning the LCD off --------------------------------------------


def test_turning_the_lcd_off_resets_the_clock(running: PPU) -> None:
    run_dots(running, 456 * 50)
    assert running.ly == 50

    running.write(LCDC, 0x11)  # bit 7 clear

    assert running.ly == 0
    assert running.dots == 0
    assert running.mode is Mode.HBLANK
    assert running.last_stat_line is False


def test_the_lcd_off_stops_the_clock(running: PPU) -> None:
    running.write(LCDC, 0x11)

    raised = run_dots(running, 70224)

    assert running.ly == 0
    assert running.frames == 0
    assert raised == []


def test_turning_the_lcd_off_blanks_the_framebuffer(running: PPU) -> None:
    running.framebuffer[:] = b"\x03" * len(running.framebuffer)

    running.write(LCDC, 0x11)

    assert set(running.framebuffer) == {0}


def test_turning_the_lcd_back_on_restarts_at_the_top_of_a_frame(running: PPU) -> None:
    run_dots(running, 456 * 50)
    running.write(LCDC, 0x11)

    running.write(LCDC, 0x91)

    assert running.ly == 0

    run_dots(running, 456 * 3)

    assert running.ly == 3


# --- task 6: the bus ---------------------------------------------------------


def test_the_bus_hands_elapsed_time_to_the_ppu(cartridge: Cartridge) -> None:
    bus = Bus.post_boot(cartridge)

    bus.tick(456)

    assert bus.ppu.ly == 1


def test_a_frame_through_the_bus_requests_vblank(cartridge: Cartridge) -> None:
    bus = Bus.post_boot(cartridge)

    for _ in range(70224 // 4):
        bus.tick(4)

    assert get_bit(bus.read(INTERRUPT_FLAG), Interrupt.VBLANK)


def test_post_boot_assembles_a_machine_the_boot_rom_would_have_left(
    cartridge: Cartridge,
) -> None:
    bus = Bus.post_boot(cartridge)

    assert bus.read(DIVIDER) == 0xAB
    assert bus.read(LCDC) == 0x91


def test_a_plain_bus_leaves_the_lcd_off(bus: Bus) -> None:
    # Everything written before this task assumes a bus whose PPU stays idle.
    for _ in range(70224 // 4):
        bus.tick(4)

    assert bus.ppu.ly == 0
    assert bus.ppu.frames == 0
    assert not get_bit(bus.read(INTERRUPT_FLAG), Interrupt.VBLANK)
