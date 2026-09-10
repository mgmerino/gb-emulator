"""How does the Nintendo logo fall, and can the PPU draw it with no CPU at all?

The emulator starts at `0x0100` with `Registers.post_boot()`, which is the state
the DMG's 256-byte boot ROM leaves behind. Everything the boot ROM does before
that -- the logo dropping into the middle of the screen, the ping, the checksum
that decides whether the cartridge starts -- is skipped, because there is no
boot ROM in this repo.

So this draws the animation the other way round: no CPU, no boot ROM, just the
PPU we built and a `SCY` register written once per frame. If the logo falls, the
background renderer, the tile decoder and the scroll wrap are all correct
together, which no unit test asserts in one go.

Run with:

    uv run --extra gui python experiments/boot_logo.py ~/games/TETRIS.gb
    uv run python experiments/boot_logo.py ~/games/TETRIS.gb --text

Sample run (Python 3.12.13, Tetris (World) Rev 1):

    logo: 48 bytes from the header, expanded into 24 tiles
    101 frames, 1 pixel each, in 3.5s (29 fps)

Four things it showed:

1. The logo is in the cartridge, not in the emulator. Those 48 bytes at
   `0x0104` are the ones the real boot ROM compares against its own copy, and
   refuses to start the game if they differ. Point this at a ROM with one byte
   changed and you see exactly what the DMG would have refused to boot.

2. 48 bytes for a 96x16 image, because it is stored at quarter size and doubled
   in both directions. Each nibble is four pixels of one row; the boot ROM
   widens each pixel to two and writes each row twice.

3. The fall is one register. `SCY` counts down from 100 to 0, and the logo sits
   still at background row 64 the whole time. What moves is where the screen is
   looking, which is the same trick every scrolling game uses.

4. A frame is not one `tick`. The PPU draws a line on the edge into HBlank and
   derives its mode once per call, so `tick(70224)` advances 154 lines and draws
   none of them. It has to be ticked in pieces the way the CPU ticks it, which
   is a thing you only notice with the CPU out of the way.

And a number worth keeping. 29 frames per second with no CPU running at all,
against the 9 the whole emulator manages in Step 13A. Drawing is two thirds of
the cost of a frame here, before a single opcode is decoded, which is a hint
about where 13B should look.
"""

import argparse
import time
from pathlib import Path

from gameboy.cartridge import Cartridge
from gameboy.ppu import (
    DRAWING_DOTS,
    LINES_PER_FRAME,
    OAM_SCAN_DOTS,
    PPU,
    SCANLINE_DOTS,
    SCREEN_WIDTH,
    SCY,
)

# Where the header keeps the logo, and how big it is.
LOGO_START = 0x0104
LOGO_BYTES = 48

# The boot ROM's own numbers: the logo starts 100 pixels above where it stops,
# and lands on background rows 64-79, which is the middle of a 144-pixel screen.
SCROLL_FROM = 100
FRAME_SECONDS = 1 / 60
MAP_ROW = 8
MAP_COLUMN = 4

TILE_MAP = 0x9800 - 0x8000  # both as offsets into VRAM

# The PPU draws a line on the edge into HBlank and works out its mode once per
# call, so `tick(70224)` advances 154 lines and draws none of them. It has to
# be ticked in pieces, the way the CPU ticks it. Three calls per scanline is
# the fewest that still crosses every edge.
SCANLINE_STEPS = (
    OAM_SCAN_DOTS,
    DRAWING_DOTS,
    SCANLINE_DOTS - OAM_SCAN_DOTS - DRAWING_DOTS,
)
FIRST_TILE = 1  # tile 0 stays blank, so it can be the background
TILES_PER_ROW = 32
RAMP = " .+#"


def widen(nibble: int) -> int:
    """Four pixels to eight, each one doubled."""
    wide = 0
    for i in range(4):
        if nibble & (1 << (3 - i)):
            wide |= 0b11 << (6 - 2 * i)

    return wide


def logo_tile(low: int, high: int) -> bytes:
    """Two header bytes to one 8x8 tile, in the Game Boy's 2bpp format.

    Each byte holds two nibbles, each nibble is four pixels of one row, and each
    row is written twice. Two bytes is four source rows is eight tile rows.

    The pixels go in the low bitplane only, so they read as colour index 1. The
    boot ROM leaves `BGP` at 0xFC, which maps 1, 2 and 3 all to the darkest
    shade.
    """
    tile = bytearray()

    for byte in (low, high):
        for nibble in (byte >> 4, byte & 0x0F):
            row = widen(nibble)
            tile += bytes((row, 0x00, row, 0x00))  # the row, twice

    return bytes(tile)


def load_logo(ppu: PPU, logo: bytes) -> None:
    """Expand the header logo into VRAM, and point the tile map at it.

    The 48 bytes are two halves of 24. Within a half, a pair of bytes is one
    tile, and the pairs run left to right across the twelve columns.
    """
    for column in range(12):
        for half in range(2):
            source = half * 24 + column * 2
            tile = FIRST_TILE + half * 12 + column

            # Tile n lives at 0x8000 + 16n, which is offset 16n into VRAM.
            ppu.vram[tile * 16 : tile * 16 + 16] = logo_tile(
                logo[source], logo[source + 1]
            )

            cell = (MAP_ROW + half) * TILES_PER_ROW + MAP_COLUMN + column
            ppu.vram[TILE_MAP + cell] = tile


def tick_frame(ppu: PPU) -> None:
    for _ in range(LINES_PER_FRAME):
        for dots in SCANLINE_STEPS:
            ppu.tick(dots)


def as_text(ppu: PPU) -> str:
    frame = ppu.frame

    return "\n".join(
        "".join(RAMP[shade] for shade in frame[row * SCREEN_WIDTH :][:SCREEN_WIDTH])
        for row in range(0, 144, 2)  # every other line, so it fits a terminal
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Drop the Nintendo logo.")
    parser.add_argument("rom", type=Path, help="path to a .gb file")
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument(
        "--text",
        action="store_true",
        help="print the last frame instead of opening a window",
    )
    args = parser.parse_args()

    cartridge = Cartridge.from_path(args.rom)
    logo = cartridge.raw_bytes[LOGO_START : LOGO_START + LOGO_BYTES]

    # post_boot is already the state the boot ROM leaves: LCD on, the 0x8000
    # tile data method, map 0x9800, and BGP 0xFC.
    ppu = PPU.post_boot()
    load_logo(ppu, logo)

    print(f"logo: {len(logo)} bytes from the header, expanded into 24 tiles")

    display = None
    if not args.text:
        from screen.pygame_display import PygameDisplay

        display = PygameDisplay(scale=args.scale, title="boot")

    started = time.perf_counter()
    deadline = started

    for scy in range(SCROLL_FROM, -1, -1):
        ppu.write(SCY, scy)
        tick_frame(ppu)

        if display is not None:
            if display.wants_to_close():
                return 0

            display.present(ppu.frame)

            # Pace against a deadline rather than sleeping a fixed amount, so a
            # slow frame does not push every later one back. It cannot hold 60
            # anyway: the number below says what it managed.
            deadline += FRAME_SECONDS
            time.sleep(max(0.0, deadline - time.perf_counter()))

    frames = SCROLL_FROM + 1
    elapsed = time.perf_counter() - started
    print(
        f"{frames} frames, 1 pixel each, in {elapsed:.1f}s ({frames / elapsed:.0f} fps)"
    )

    if args.text:
        print(as_text(ppu))
    else:
        time.sleep(2)  # hold the finished logo, the way the DMG does

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
