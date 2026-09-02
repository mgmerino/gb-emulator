import pytest

from gameboy.bits import get_bit
from gameboy.cartridge import Cartridge
from gameboy.cpu import CPU, Registers
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
    decode_row_index,
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


# --- task 7: the loop the emulator has never escaped -------------------------


def test_a_rom_waiting_on_ly_gets_out_of_its_wait_loop() -> None:
    # What Tetris does at 0x022F: turn the LCD on, spin until LY reaches 148 —
    # the fifth line of VBlank — and only then turn the LCD off to load VRAM
    # with the whole address space to itself.
    program = [
        0x3E,
        0x80,  # LD A, 0x80
        0xE0,
        0x40,  # LDH (0x40), A   -> LCDC, bit 7 set: LCD on
        0xF0,
        0x44,  # LDH A, (0x44)   -> LY            \
        0xFE,
        0x94,  # CP 0x94         -> 148            } the wait loop
        0x20,
        0xFA,  # JR NZ, -6                        /
        0x04,  # INC B           -> got out
        0x3E,
        0x03,  # LD A, 0x03
        0xE0,
        0x40,  # LDH (0x40), A   -> LCDC, bit 7 clear: LCD off
        0x18,
        0xFE,  # JR -2           -> spin here
    ]

    image = bytearray(0x8000)
    image[0x0100 : 0x0100 + len(program)] = bytes(program)

    bus = Bus.post_boot(Cartridge.from_bytes(bytes(image)))
    cpu = CPU(bus, Registers.post_boot())

    for _ in range(20_000):  # bounded: a stuck wait loop must fail, not hang
        bus.tick(cpu.step())

    assert cpu.registers.b == 1
    assert bus.ppu.ly == 0  # the LCD went off, which parks LY at 0
    assert not get_bit(bus.read(LCDC), 7)


def test_a_stray_write_to_ly_cannot_desynchronise_the_wait_loop() -> None:
    # The same wait loop, with a write to LY inside it. LY is read-only, so the
    # write is dropped and the loop still ends. If the bus let it through, LY
    # would be pushed back to 0 on every pass and 148 would never arrive.
    program = [
        0x3E,
        0x80,  # LD A, 0x80
        0xE0,
        0x40,  # LDH (0x40), A   -> LCD on
        0x3E,
        0x00,  # LD A, 0x00      \
        0xE0,
        0x44,  # LDH (0x44), A    |  the stray write
        0xF0,
        0x44,  # LDH A, (0x44)    |
        0xFE,
        0x94,  # CP 0x94          |
        0x20,
        0xF6,  # JR NZ, -10      /
        0x04,  # INC B
        0x18,
        0xFE,  # JR -2
    ]

    image = bytearray(0x8000)
    image[0x0100 : 0x0100 + len(program)] = bytes(program)

    bus = Bus.post_boot(Cartridge.from_bytes(bytes(image)))
    cpu = CPU(bus, Registers.post_boot())

    for _ in range(40_000):
        bus.tick(cpu.step())

    assert cpu.registers.b == 1


# --- a tile row ---------------------------------------------------


def test_a_tile_row_decodes_its_two_bitplanes() -> None:
    assert decode_row_index(0x3C, 0x7E) == (0, 2, 3, 3, 3, 3, 2, 0)


def test_bit_7_is_the_leftmost_pixel() -> None:
    assert decode_row_index(0x80, 0x00) == (1, 0, 0, 0, 0, 0, 0, 0)
    assert decode_row_index(0x01, 0x00) == (0, 0, 0, 0, 0, 0, 0, 1)


def test_the_first_byte_of_a_row_is_the_low_plane() -> None:
    # Swapping the planes swaps colours 1 and 2, which looks almost right.
    assert decode_row_index(0x3C, 0x7E) == (0, 2, 3, 3, 3, 3, 2, 0)
    assert decode_row_index(0x7E, 0x3C) == (0, 1, 3, 3, 3, 3, 1, 0)


def test_tile_row_reads_its_two_bytes_from_vram() -> None:
    ppu = PPU(lcdc=0x10)  # bit 4 set: the 0x8000 method
    # Tile 5, row 3: 0x8000 + 5 * 16 + 3 * 2 = 0x8056
    ppu.vram[0x56] = 0x3C
    ppu.vram[0x57] = 0x7E

    assert ppu.tile_row(5, 3) == (0, 2, 3, 3, 3, 3, 2, 0)


def test_index_0_resolves_differently_in_each_addressing_mode() -> None:
    unsigned = PPU(lcdc=0x10)
    unsigned.vram[0x0000] = 0xFF  # 0x8000, where the unsigned method starts
    unsigned.vram[0x0001] = 0xFF

    signed = PPU(lcdc=0x00)
    signed.vram[0x1000] = 0xFF  # 0x9000, where the signed method counts from
    signed.vram[0x1001] = 0xFF

    assert unsigned.tile_row(0x00, 0) == (3,) * 8
    assert signed.tile_row(0x00, 0) == (3,) * 8
    # Each only sees its own base, so the other one reads blank.
    assert PPU(lcdc=0x00, vram=unsigned.vram).tile_row(0x00, 0) == (0,) * 8


@pytest.mark.parametrize("lcdc", [0x10, 0x00])
def test_index_0x80_lands_on_0x8800_in_both_modes(lcdc: int) -> None:
    # 0x8000 + 128 * 16 and 0x9000 + (-128) * 16 are the same byte: block 1,
    # the overlap that lets a tile be reachable from either end.
    ppu = PPU(lcdc=lcdc)
    ppu.vram[0x0800] = 0xFF  # 0x8800
    ppu.vram[0x0801] = 0xFF

    assert ppu.tile_row(0x80, 0) == (3,) * 8


# --- 11B task 3: the background scanline --------------------------------------

# 0x3C 0x7E decodes to (0, 2, 3, 3, 3, 3, 2, 0), the row worked out by hand in
# the step doc. Every row of the tile carries it, so any SCY shows the same line.
PATTERN = (0, 2, 3, 3, 3, 3, 2, 0)


def ppu_showing_one_tile(*rows: tuple[int, int]) -> PPU:
    """A PPU whose whole background is tile 0: LCD and BG on, identity palette.

    The tile map is already all zeros, so every cell names tile 0.
    """
    ppu = PPU(lcdc=0x91, bgp=0xE4)  # LCD on, tile data 0x8000, map 0x9800, BG on
    for r, (low, high) in enumerate(rows or ((0x3C, 0x7E),) * 8):
        ppu.vram[r * 2] = low
        ppu.vram[r * 2 + 1] = high

    return ppu


def test_a_line_repeats_the_tile_across_all_160_columns() -> None:
    ppu = ppu_showing_one_tile()

    run_dots(ppu, 70224)

    assert tuple(ppu.framebuffer[0:160]) == PATTERN * 20


def test_the_whole_visible_area_is_drawn() -> None:
    ppu = ppu_showing_one_tile()

    run_dots(ppu, 70224)

    for line in range(144):
        start = line * 160
        assert tuple(ppu.framebuffer[start : start + 160]) == PATTERN * 20, line


def test_scx_shifts_the_line_and_wraps() -> None:
    ppu = ppu_showing_one_tile()
    ppu.scx = 4

    run_dots(ppu, 70224)

    shifted = PATTERN[4:] + PATTERN[:4]
    assert tuple(ppu.framebuffer[0:160]) == shifted * 20


def test_scy_picks_the_row_within_the_tile() -> None:
    # Row 0 blank, row 1 solid, the rest blank.
    rows = [(0x00, 0x00), (0xFF, 0xFF)] + [(0x00, 0x00)] * 6
    ppu = ppu_showing_one_tile(*rows)
    ppu.scy = 1

    run_dots(ppu, 70224)

    assert tuple(ppu.framebuffer[0:160]) == (3,) * 160


def test_bgp_maps_indices_to_shades() -> None:
    ppu = ppu_showing_one_tile()
    ppu.bgp = 0x1B  # 00 01 10 11: index n becomes shade 3 - n

    run_dots(ppu, 70224)

    inverted = tuple(3 - index for index in PATTERN)
    assert tuple(ppu.framebuffer[0:160]) == inverted * 20


def test_the_background_can_be_switched_off() -> None:
    ppu = ppu_showing_one_tile()
    ppu.lcdc &= ~0b1  # LCDC bit 0 clear: no background at all

    run_dots(ppu, 70224)

    assert set(ppu.framebuffer) == {0}


def test_the_frame_is_exposed_read_only() -> None:
    ppu = ppu_showing_one_tile()

    run_dots(ppu, 70224)

    assert len(ppu.frame) == 23040
    assert bytes(ppu.frame[0:8]) == bytes(PATTERN)
    with pytest.raises(TypeError):
        ppu.frame[0] = 1  # type: ignore[index]


def test_lcdc_bit_3_selects_the_second_tile_map() -> None:
    ppu = ppu_showing_one_tile()
    ppu.vram[0x10:0x20] = bytes([0xFF] * 16)  # tile 1 at 0x8010, solid
    ppu.vram[0x1C00:0x2000] = bytes([1] * 1024)  # map 1 at 0x9C00, all tile 1

    run_dots(ppu, 70224)

    assert tuple(ppu.framebuffer[0:160]) == PATTERN * 20

    ppu.lcdc |= 0b1000  # LCDC bit 3: read map 1 from now on
    run_dots(ppu, 70224)

    assert tuple(ppu.framebuffer[0:160]) == (3,) * 160


def test_the_raw_colour_indices_are_kept_for_step_12() -> None:
    ppu = ppu_showing_one_tile()
    ppu.bgp = 0x1B  # index n becomes shade 3 - n, so the two arrays disagree

    run_dots(ppu, 70224)

    assert tuple(ppu.framebuffer[0:8]) == tuple(3 - index for index in PATTERN)
    assert tuple(ppu.line_indices[0:8]) == PATTERN


# --- 11B task 6: the torus, and not reading what you do not need ---------------


def ppu_with_solid_cells(*cells: int) -> PPU:
    """Tile 0 is blank and tile 1 is solid; the named map-0 cells get tile 1.

    Cell n is at row n // 32, column n % 32, so cell 31 is the far right of the
    top row and cells 992-1023 are the bottom row of the 256x256 background.
    """
    ppu = PPU(lcdc=0x91, bgp=0xE4)
    ppu.vram[0x10:0x20] = bytes([0xFF] * 16)  # tile 1 at 0x8010, index 3 everywhere
    for cell in cells:
        ppu.vram[0x1800 + cell] = 1  # tile map 0 is at 0x9800

    return ppu


def line_of(ppu: PPU, line: int) -> bytearray:
    """The 160 shades of one screen line, sliced out of the flat framebuffer."""
    return ppu.framebuffer[line * SCREEN_WIDTH : (line + 1) * SCREEN_WIDTH]


def test_scx_wraps_past_255_back_to_the_left_edge() -> None:
    # The last column of the map, so the screen has to come round the torus to
    # reach it. background_x runs 252, 253, 254, 255, then 0.
    ppu = ppu_with_solid_cells(31)
    ppu.scx = 252

    run_dots(ppu, 70224)

    assert tuple(ppu.framebuffer[0:4]) == (3, 3, 3, 3)
    assert set(ppu.framebuffer[4:160]) == {0}


def test_scy_moves_a_whole_cell_down_not_just_a_row_of_pixels() -> None:
    # Cells 32-63 are the second row of the map. Reaching them needs the // 8,
    # which is the half of background_y that the % 8 does not answer.
    ppu = ppu_with_solid_cells(*range(32, 64))
    ppu.scy = 8

    run_dots(ppu, 70224)

    assert set(ppu.framebuffer[0:160]) == {3}


def test_the_background_off_never_reaches_vram(monkeypatch: pytest.MonkeyPatch) -> None:
    ppu = ppu_showing_one_tile()
    ppu.lcdc &= ~0b1  # LCDC bit 0 clear
    monkeypatch.setattr(
        PPU, "tile_row", lambda *_: pytest.fail("fetched a tile with the BG off")
    )

    run_dots(ppu, 70224)

    assert set(ppu.framebuffer) == {0}


def test_scy_wraps_past_255_back_to_the_top() -> None:
    ppu = ppu_with_solid_cells(*range(32))
    ppu.scy = 250

    run_dots(ppu, 70224)

    for line in range(6):
        assert set(line_of(ppu, line)) == {0}, line
    for line in range(6, 14):
        assert set(line_of(ppu, line)) == {3}, line
    assert set(line_of(ppu, 14)) == {0}
