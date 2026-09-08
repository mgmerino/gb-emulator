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
    OBP0,
    OBP1,
    SCX,
    SCY,
    STAT,
    WX,
    WY,
)
from gameboy.ppu import (
    MAX_SPRITES_PER_LINE,
    PPU,
    SCANLINE_DOTS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_DATA_UNSIGNED,
    TILE_MAP_0,
    TILE_SIZE,
    Mode,
    Sprite,
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
        (OBP0, "obp0"),
        (OBP1, "obp1"),
        (WY, "window_y"),
        (WX, "window_x"),
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


@pytest.mark.parametrize("lcdc", [0x10, 0x00])
def test_objects_read_their_tiles_the_0x8000_way_whatever_bit_4_says(
    lcdc: int,
) -> None:
    # Tile 0 unsigned is at 0x8000, tile 0 signed at 0x9000. The background
    # follows LCDC bit 4 between them; an object never does.
    ppu = PPU(lcdc=lcdc)
    ppu.vram[0x0000:0x0002] = bytes((0xFF, 0xFF))
    ppu.vram[0x1000:0x1002] = bytes((0x00, 0x00))

    assert ppu.object_tile_row(0x00, 0) == (3,) * 8


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
        ppu.frame[0] = 1


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


def test_sprite_decode_properties_from_input_bytes() -> None:
    sprite = Sprite(0x20, 0x10, 0x2F, 0xA0)

    assert sprite.screen_y == 16
    assert sprite.screen_x == 8
    assert sprite.tile == 0x2F
    assert sprite.behind_background
    assert not sprite.flip_on_y
    assert sprite.flip_on_x
    assert not sprite.uses_obp1


# --- 12A task 3: the objects on one line --------------------------------------

# Y = 16 puts an object's top edge on screen row 0, so every entry below covers
# line 0 unless it says otherwise. Tiles number the entries so a returned list
# says which ones survived.
ON_LINE_0 = 16


def ppu_with_oam(*entries: tuple[int, int, int, int], lcdc: int = 0x91) -> PPU:
    """A PPU whose OAM holds `entries` from index 0. The other slots stay zeroed,
    and Y = 0 keeps them off every line.
    """
    ppu = PPU(lcdc=lcdc)
    for index, entry in enumerate(entries):
        start = index * 4
        ppu.oam[start : start + 4] = bytes(entry)

    return ppu


def test_only_the_first_ten_objects_on_a_line_survive() -> None:
    ppu = ppu_with_oam(*((ON_LINE_0, 8, tile, 0) for tile in range(12)))

    on_line = ppu.sprites_on_line(0)

    assert len(on_line) == MAX_SPRITES_PER_LINE
    assert [sprite.tile for sprite in on_line] == list(range(10))


def test_an_object_off_the_left_edge_still_spends_a_slot() -> None:
    # Entry 0 sits at X = 0, eight columns left of the screen and invisible.
    ppu = ppu_with_oam(
        *((ON_LINE_0, 0 if tile == 0 else 8, tile, 0) for tile in range(11))
    )

    on_line = ppu.sprites_on_line(0)

    assert [sprite.tile for sprite in on_line] == list(range(10))


def test_a_short_object_covers_eight_lines() -> None:
    ppu = ppu_with_oam((ON_LINE_0, 8, 0, 0))

    assert [ppu.sprites_on_line(line) != [] for line in range(9)] == [True] * 8 + [
        False
    ]


def test_the_line_above_a_short_object_is_the_last_one_it_misses() -> None:
    # Y = 8 is one row short of reaching line 0; Y = 9 reaches it and nothing else.
    above = ppu_with_oam((8, 8, 0, 0))
    touching = ppu_with_oam((9, 8, 0, 0))

    assert above.sprites_on_line(0) == []
    assert len(touching.sprites_on_line(0)) == 1
    assert touching.sprites_on_line(1) == []


def test_lcdc_bit_2_makes_an_object_sixteen_lines_tall() -> None:
    ppu = ppu_with_oam((ON_LINE_0, 8, 0, 0), lcdc=0x95)

    assert [ppu.sprites_on_line(line) != [] for line in range(17)] == [True] * 16 + [
        False
    ]


def test_an_empty_oam_puts_nothing_on_any_line() -> None:
    ppu = PPU(lcdc=0x91)

    assert all(ppu.sprites_on_line(line) == [] for line in range(SCREEN_HEIGHT))


# --- 12A task 4: objects drawn over the background ----------------------------

# Five tiles, all in the 0x8000 block, all rows identical unless noted:
#   0 at 0x8000  the background, whatever index the helper is asked for
#   1 at 0x8010  PATTERN, so (0, 2, 3, 3, 3, 3, 2, 0): transparent at both ends
#   2 at 0x8020  index 1 everywhere
#   3 at 0x8030  index 2 everywhere
#   4 at 0x8040  index 1 in the leftmost pixel only, so it is not a palindrome
#   5 at 0x8050  index 1 across row 0 only, so the rows differ
PATTERN_TILE = 1
FLAT_1_TILE = 2
FLAT_2_TILE = 3
LEFT_EDGE_TILE = 4
TOP_ROW_TILE = 5
# LCD on, tile data 0x8000, map 0, background on, objects on.
LCDC_OBJECTS = 0x93


def ppu_drawing_objects(
    *entries: tuple[int, int, int, int],
    lcdc: int = LCDC_OBJECTS,
    background: int = 0,
) -> PPU:
    """Every palette is the identity, so a shade and a colour index read alike.

    `background` is the colour index every background pixel carries, which is
    what decides whether a behind-the-background object can show.
    """
    ppu = PPU(lcdc=lcdc, bgp=0xE4, obp0=0xE4, obp1=0xE4)
    low = 0xFF if background & 0b01 else 0x00
    high = 0xFF if background & 0b10 else 0x00
    ppu.vram[0x00:0x10] = bytes((low, high) * 8)
    ppu.vram[0x10:0x20] = bytes((0x3C, 0x7E) * 8)
    ppu.vram[0x20:0x30] = bytes((0xFF, 0x00) * 8)
    ppu.vram[0x30:0x40] = bytes((0x00, 0xFF) * 8)
    ppu.vram[0x40:0x50] = bytes((0x80, 0x00) * 8)
    ppu.vram[0x50:0x60] = bytes((0xFF, 0x00)) + bytes(14)

    for index, entry in enumerate(entries):
        ppu.oam[index * 4 : index * 4 + 4] = bytes(entry)

    return ppu


def test_an_object_draws_its_row_over_the_background() -> None:
    ppu = ppu_drawing_objects((ON_LINE_0, 8, PATTERN_TILE, 0), background=1)

    run_dots(ppu, 70224)

    assert tuple(line_of(ppu, 0)[0:8]) == (1, 2, 3, 3, 3, 3, 2, 1)


def test_colour_index_0_lets_the_background_through() -> None:
    # The two ends of PATTERN are index 0, and only those two keep the background.
    ppu = ppu_drawing_objects((ON_LINE_0, 8, PATTERN_TILE, 0), background=1)

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert (line[0], line[7]) == (1, 1)
    assert set(line[1:7]) == {2, 3}


def test_an_object_behind_a_non_empty_background_lands_nowhere() -> None:
    ppu = ppu_drawing_objects((ON_LINE_0, 8, FLAT_1_TILE, 0x80), background=2)

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 0)) == {2}


def test_an_object_behind_an_empty_background_lands_everywhere() -> None:
    ppu = ppu_drawing_objects((ON_LINE_0, 8, FLAT_1_TILE, 0x80), background=0)

    run_dots(ppu, 70224)

    assert tuple(line_of(ppu, 0)[0:8]) == (1,) * 8


def test_the_smaller_x_is_in_front() -> None:
    ppu = ppu_drawing_objects(
        (ON_LINE_0, 8, FLAT_1_TILE, 0),  # screen columns 0-7
        (ON_LINE_0, 12, FLAT_2_TILE, 0),  # screen columns 4-11
    )

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert tuple(line[0:8]) == (1,) * 8
    assert tuple(line[8:12]) == (2,) * 4


def test_an_equal_x_falls_back_to_the_oam_order() -> None:
    ppu = ppu_drawing_objects(
        (ON_LINE_0, 8, FLAT_2_TILE, 0),
        (ON_LINE_0, 8, FLAT_1_TILE, 0),
    )

    run_dots(ppu, 70224)

    assert tuple(line_of(ppu, 0)[0:8]) == (2,) * 8


def test_an_object_hidden_by_the_background_keeps_the_one_behind_it_out() -> None:
    # Entry 0 is in front and loses to the background, but it still owns its
    # eight columns. Entry 1 only reaches the one column entry 0 does not cover.
    ppu = ppu_drawing_objects(
        (ON_LINE_0, 8, FLAT_1_TILE, 0x80),  # screen columns 0-7, behind the background
        (ON_LINE_0, 9, FLAT_2_TILE, 0),  # screen columns 1-8
        background=1,
    )

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert tuple(line[0:8]) == (1,) * 8
    assert line[8] == 2


def test_the_x_flip_mirrors_the_row_inside_the_object() -> None:
    plain = ppu_drawing_objects((ON_LINE_0, 8, LEFT_EDGE_TILE, 0), background=2)
    flipped = ppu_drawing_objects((ON_LINE_0, 8, LEFT_EDGE_TILE, 0x20), background=2)

    run_dots(plain, 70224)
    run_dots(flipped, 70224)

    assert tuple(line_of(plain, 0)[0:8]) == (1, 2, 2, 2, 2, 2, 2, 2)
    assert tuple(line_of(flipped, 0)[0:8]) == (2, 2, 2, 2, 2, 2, 2, 1)


def test_the_y_flip_mirrors_the_rows_inside_the_object() -> None:
    plain = ppu_drawing_objects((ON_LINE_0, 8, TOP_ROW_TILE, 0), background=2)
    flipped = ppu_drawing_objects((ON_LINE_0, 8, TOP_ROW_TILE, 0x40), background=2)

    run_dots(plain, 70224)
    run_dots(flipped, 70224)

    assert [line_of(plain, line)[0] for line in range(8)] == [1] + [2] * 7
    assert [line_of(flipped, line)[0] for line in range(8)] == [2] * 7 + [1]


@pytest.mark.parametrize("tile", [FLAT_1_TILE, FLAT_1_TILE | 1])
def test_lcdc_bit_2_stacks_the_tile_pair_and_ignores_bit_0_of_the_index(
    tile: int,
) -> None:
    ppu = ppu_drawing_objects((ON_LINE_0, 8, tile, 0), lcdc=LCDC_OBJECTS | 0x04)

    run_dots(ppu, 70224)

    assert [line_of(ppu, line)[0] for line in range(16)] == [1] * 8 + [2] * 8


def test_a_tall_objects_halves_swap_under_a_y_flip() -> None:
    ppu = ppu_drawing_objects(
        (ON_LINE_0, 8, FLAT_1_TILE, 0x40), lcdc=LCDC_OBJECTS | 0x04
    )

    run_dots(ppu, 70224)

    assert [line_of(ppu, line)[0] for line in range(16)] == [2] * 8 + [1] * 8


def test_lcdc_bit_1_clear_draws_no_objects() -> None:
    ppu = ppu_drawing_objects(
        (ON_LINE_0, 8, FLAT_1_TILE, 0), lcdc=LCDC_OBJECTS & ~0x02, background=2
    )

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 0)) == {2}


def test_lcdc_bit_0_clear_blanks_the_background_but_keeps_the_objects() -> None:
    ppu = ppu_drawing_objects(
        (ON_LINE_0, 8, FLAT_1_TILE, 0), lcdc=LCDC_OBJECTS & ~0x01, background=2
    )

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert tuple(line[0:8]) == (1,) * 8
    assert set(line[8:]) == {0}


def test_objects_ignore_the_tile_data_select_bit() -> None:
    # Bit 4 clear sends the background to 0x9000, which is blank. The object
    # still reads its tile from 0x8000 and shows up.
    ppu = ppu_drawing_objects(
        (ON_LINE_0, 8, FLAT_1_TILE, 0), lcdc=LCDC_OBJECTS & ~0x10, background=3
    )

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert tuple(line[0:8]) == (1,) * 8
    assert set(line[8:]) == {0}


@pytest.mark.parametrize(
    ("x", "visible"),
    [(4, slice(0, 4)), (164, slice(156, 160))],
)
def test_an_object_hanging_off_an_edge_is_clipped(x: int, visible: slice) -> None:
    ppu = ppu_drawing_objects((ON_LINE_0, x, FLAT_1_TILE, 0), background=2)

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert set(line[visible]) == {1}
    assert line.count(1) == 4


def test_colour_index_0_is_transparent_whatever_the_palette_maps_it_to() -> None:
    # OBP0 sends index 0 to shade 3 here. Transparency is decided on the index,
    # before the palette, so the two ends of PATTERN must still show the
    # background rather than shade 3.
    ppu = ppu_drawing_objects((ON_LINE_0, 8, PATTERN_TILE, 0), background=1)
    ppu.obp0 = 0b11_10_01_11

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert (line[0], line[7]) == (1, 1)


@pytest.mark.parametrize(("flags", "shade"), [(0x00, 1), (0x10, 3)])
def test_flag_bit_4_picks_which_object_palette_is_used(flags: int, shade: int) -> None:
    # OBP0 is the identity, so index 1 is shade 1. OBP1 sends index 1 to shade 3.
    ppu = ppu_drawing_objects((ON_LINE_0, 8, FLAT_1_TILE, flags))
    ppu.obp1 = 0b11_10_11_00

    run_dots(ppu, 70224)

    assert tuple(line_of(ppu, 0)[0:8]) == (shade,) * 8


# --- 12B: the window ----------------------------------------------------------

# Four tiles, every row of each one uniform, so a rendered pixel names its layer:
#   0 at 0x8000  colour index 0
#   1 at 0x8010  colour index 3   the background
#   2 at 0x8020  colour index 1   the window's first cell row
#   3 at 0x8030  colour index 2   the window's second cell row
BG_TILE = 1
WINDOW_TILE_A = 2
WINDOW_TILE_B = 3
# LCD on, window map 1, window on, tile data 0x8000, background on map 0.
LCDC_WINDOW = 0xF1


def ppu_with_window(
    *, window_y: int = 0, window_x: int = 7, lcdc: int = LCDC_WINDOW
) -> PPU:
    """A striped background under a window whose two map rows differ.

    The background alternates tile 1 and tile 0 every cell, so `SCX` moving it
    is visible. The window's map rows are uniform, so a line of it says which
    row of its map was drawn.
    """
    ppu = PPU(lcdc=lcdc, bgp=0xE4, obp0=0xE4)
    ppu.vram[0x10:0x20] = bytes([0xFF] * 16)
    ppu.vram[0x20:0x30] = bytes((0xFF, 0x00) * 8)
    ppu.vram[0x30:0x40] = bytes((0x00, 0xFF) * 8)

    for cell in range(0x400):
        ppu.vram[0x1800 + cell] = BG_TILE if cell % 2 == 0 else 0
    ppu.vram[0x1C00:0x1C20] = bytes([WINDOW_TILE_A] * 32)
    ppu.vram[0x1C20:0x1C40] = bytes([WINDOW_TILE_B] * 32)

    ppu.window_y = window_y
    ppu.window_x = window_x

    return ppu


def test_the_window_covers_the_background_from_wy_down() -> None:
    ppu = ppu_with_window(window_y=8)

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 7)) == {3, 0}
    assert set(line_of(ppu, 8)) == {1}


def test_the_window_row_comes_from_its_own_counter() -> None:
    # Map row 0 for the first eight lines, row 1 for the next eight, and rows
    # 2 upward are blank. Reading LY instead of the counter gives the same
    # answer here only because WY is 0.
    ppu = ppu_with_window()

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 7)) == {1}
    assert set(line_of(ppu, 8)) == {2}
    assert set(line_of(ppu, 16)) == {0}


def test_the_window_resumes_its_own_row_after_being_switched_off() -> None:
    # Lines 0-7 draw map row 0, then the window is off for lines 8-15. At line
    # 16 the counter stands at 8, so map row 1 is next. `LY - WY` would be 16
    # and would draw map row 2, which is blank.
    ppu = ppu_with_window()

    run_dots(ppu, SCANLINE_DOTS * 8)
    ppu.lcdc &= ~0x20
    run_dots(ppu, SCANLINE_DOTS * 8)
    ppu.lcdc |= 0x20
    run_dots(ppu, SCANLINE_DOTS)

    assert ppu.window_line == 9
    assert set(line_of(ppu, 16)) == {2}


def test_the_row_inside_the_tile_also_comes_from_the_counter() -> None:
    # The gap is three lines, not a multiple of eight, so the counter and
    # `LY - WY` disagree on the row *inside* the tile as well as on the map row.
    # Tile 4's first row differs from its other seven, which is what makes that
    # disagreement visible: the other tiles here are uniform top to bottom.
    ppu = ppu_with_window()
    ppu.vram[0x40:0x50] = bytes((0xFF, 0x00)) + bytes((0x00, 0xFF)) * 7
    ppu.vram[0x1C20:0x1C40] = bytes([4] * 32)

    run_dots(ppu, SCANLINE_DOTS * 8)
    ppu.lcdc &= ~0x20
    run_dots(ppu, SCANLINE_DOTS * 3)
    ppu.lcdc |= 0x20
    run_dots(ppu, SCANLINE_DOTS)

    assert ppu.window_line == 9
    assert set(line_of(ppu, 11)) == {1}


@pytest.mark.parametrize(("window_x", "edge"), [(7, 0), (87, 80), (166, 159)])
def test_wx_places_the_left_edge_seven_columns_early(window_x: int, edge: int) -> None:
    ppu = ppu_with_window(window_x=window_x)

    run_dots(ppu, 70224)

    line = line_of(ppu, 0)
    assert set(line[edge:]) == {1}
    if edge:
        assert set(line[:edge]) == {3, 0}


def test_wx_past_the_right_edge_draws_nothing() -> None:
    ppu = ppu_with_window(window_x=167)

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 0)) == {3, 0}
    assert ppu.window_line == 0


def test_wx_below_seven_clips_instead_of_writing_outside_the_line() -> None:
    # left_edge is -7. Negative indices are legal in Python and would put those
    # seven pixels at the end of the framebuffer, on line 143.
    ppu = ppu_with_window(window_x=0)

    run_dots(ppu, 300)  # far enough into line 0 to draw it, and no further

    assert set(line_of(ppu, 0)) == {1}
    assert set(ppu.framebuffer[-7:]) == {0}
    assert set(ppu.line_indices[-7:]) == {1}


def test_wx_below_seven_hangs_the_window_off_the_edge_rather_than_shifting_it() -> None:
    # The window's own first cell is different from the rest, so where it lands
    # says whether the clip moved the drawing or the counting. left_edge is -7,
    # so screen column 0 shows the window's column 7: the last pixel of that
    # first cell, and the only one of it still on screen.
    ppu = ppu_with_window(window_x=0)
    ppu.vram[0x1C00] = WINDOW_TILE_B

    run_dots(ppu, 300)

    line = line_of(ppu, 0)
    assert line[0] == 2
    assert set(line[1:]) == {1}


def test_lcdc_bit_5_clear_draws_no_window() -> None:
    ppu = ppu_with_window(lcdc=LCDC_WINDOW & ~0x20)

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 0)) == {3, 0}
    assert ppu.window_line == 0


def test_lcdc_bit_0_clear_draws_no_window_even_with_bit_5_set() -> None:
    # Bit 0 is "BG and window enable" on a DMG: it blanks both layers together.
    ppu = ppu_with_window(lcdc=LCDC_WINDOW & ~0x01)

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 0)) == {0}
    assert ppu.window_line == 0


def test_lcdc_bit_6_selects_the_window_tile_map() -> None:
    # Clearing bit 6 sends the window to map 0, which is the background's own,
    # so it draws the same tiles. SCX is what tells the two layers apart: the
    # background is shifted by it and the window is not.
    on_map_1 = ppu_with_window()
    on_map_0 = ppu_with_window(lcdc=LCDC_WINDOW & ~0x40)
    on_map_0.scx = 4
    no_window = ppu_with_window(lcdc=LCDC_WINDOW & ~0x20)
    no_window.scx = 4

    for ppu in (on_map_1, on_map_0, no_window):
        run_dots(ppu, 70224)

    assert set(line_of(on_map_1, 0)) == {1}
    assert set(line_of(on_map_0, 0)) == {3, 0}
    assert line_of(on_map_0, 0) != line_of(no_window, 0)


def test_scx_and_scy_move_the_background_and_leave_the_window_alone() -> None:
    still = ppu_with_window(window_x=87)
    scrolled = ppu_with_window(window_x=87)
    scrolled.scx = 4
    scrolled.scy = 4

    run_dots(still, 70224)
    run_dots(scrolled, 70224)

    assert line_of(still, 0)[:80] != line_of(scrolled, 0)[:80]
    assert line_of(still, 0)[80:] == line_of(scrolled, 0)[80:]


def test_the_window_counter_advances_once_per_drawn_line() -> None:
    ppu = ppu_with_window()

    run_dots(ppu, SCANLINE_DOTS * 3)

    assert ppu.window_line == 3


def test_the_window_counter_pauses_while_the_window_is_off_and_then_resumes() -> None:
    # The reason the counter exists. `LY - WY` would have reached 6 by the end.
    ppu = ppu_with_window()

    run_dots(ppu, SCANLINE_DOTS * 2)
    assert ppu.window_line == 2

    ppu.lcdc &= ~0x20
    run_dots(ppu, SCANLINE_DOTS * 3)
    assert ppu.window_line == 2

    ppu.lcdc |= 0x20
    run_dots(ppu, SCANLINE_DOTS)

    assert ppu.window_line == 3


def test_the_window_counter_starts_each_frame_at_zero() -> None:
    ppu = ppu_with_window()

    run_dots(ppu, 70224)
    assert ppu.window_line == 0

    run_dots(ppu, SCANLINE_DOTS * 2)

    assert ppu.window_line == 2


def test_switching_the_lcd_off_resets_the_window_counter() -> None:
    ppu = ppu_with_window()
    run_dots(ppu, SCANLINE_DOTS * 5)
    assert ppu.window_line == 5

    ppu.write(LCDC, ppu.lcdc & ~0x80)

    assert ppu.window_line == 0


def test_an_object_behind_a_non_empty_window_pixel_stays_hidden() -> None:
    ppu = ppu_with_window(lcdc=LCDC_WINDOW | 0x02)
    ppu.oam[0:4] = bytes((16, 8, WINDOW_TILE_B, 0x80))  # screen (0, 0)

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 0)[0:8]) == {1}


def test_an_object_behind_a_window_pixel_of_index_0_shows_through() -> None:
    # Window map rows 2 upward are blank, so from screen line 16 the window's
    # colour index is 0 and a behind-the-background object is not hidden.
    ppu = ppu_with_window(lcdc=LCDC_WINDOW | 0x02)
    ppu.oam[0:4] = bytes((32, 8, WINDOW_TILE_B, 0x80))  # screen (0, 16)

    run_dots(ppu, 70224)

    assert set(line_of(ppu, 16)[0:8]) == {2}
