"""How do you get a viewable image out of the framebuffer, with no dependency?

`PLAN.md` constraint 1 says the core exposes a framebuffer and nothing else: no
pygame, no SDL, no Pillow inside `gameboy/`. So the frame arrives as 23040 bytes
holding the numbers 0-3, and turning those into something an image viewer opens
is the frontend's problem.

This is that problem solved twice over, to show that the second solution is not
a different renderer. `__main__.py` already prints a frame with a four-character
ramp; this writes the same bytes as a PNG. The only thing that differs is the
lookup table at the end.

Run with:

    uv run python experiments/frame_to_png.py ~/games/TETRIS.gb --frame 600

Sample run (Python 3.12.13, Tetris (World) Rev 1):

    frame 600 reached after 4,593,431 instructions
    shades   0: 39.5%   1: 26.6%   2:  8.2%   3: 25.7%
    wrote tetris-600.png   480x432   2170 bytes   0.084 bits/pixel

Four things it showed:

1. The framebuffer is already the image. `RAMP = " .+#"` and
   `GREY = (0xE8, 0xA8, 0x58, 0x10)` are the same kind of object: four entries
   indexed by a shade. That is the third link in a chain the PPU starts -- a
   tile stores a colour index, BGP maps it to a shade, the frontend maps the
   shade to a medium. Only the last link knows what "grey" means.

2. A minimal PNG is three chunks and about twenty lines. Signature, then
   IHDR / IDAT / IEND, each one `length | tag | data | crc32`. Colour type 0 is
   greyscale, so one byte per pixel and no palette chunk; filter 0 on every row,
   so no filtering to implement.

3. No dependency is needed because PNG's compression *is* deflate, and `zlib`
   plus `struct` are standard library. This is the whole reason the format is
   worth hand-writing rather than reaching for Pillow.

4. 0.084 bits per pixel. Four distinct values, runs of identical bytes from the
   integer scale-up, and large flat areas: deflate eats all three. The CLI still
   writes PGM instead, which needs no compression at all -- a three-line header
   and the raw bytes. A debug dump you open once does not justify a PNG encoder
   living in `__main__.py`.

The scale-up is nearest-neighbour on purpose: any interpolation blurs exactly
the pixel grid you are trying to inspect.
"""

import argparse
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

from gameboy.__main__ import run
from gameboy.cartridge import Cartridge
from gameboy.memory import Bus

# Indexed by shade, like the CLI's " .+#". Not the DMG's greens: this is for
# looking at pixel data, and a neutral ramp keeps the four steps even.
GREY = (0xE8, 0xA8, 0x58, 0x10)

SCREEN_WIDTH = 160
SCREEN_HEIGHT = 144


def chunk(tag: bytes, data: bytes) -> bytes:
    """One PNG chunk: length, tag, data, and a CRC32 over tag and data."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(frame: memoryview, scale: int) -> bytes:
    """A greyscale PNG of the frame, scaled by an integer factor."""
    width, height = SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale

    raw = bytearray()
    for y in range(SCREEN_HEIGHT):
        row = bytes(
            GREY[frame[y * SCREEN_WIDTH + x]]
            for x in range(SCREEN_WIDTH)
            for _ in range(scale)
        )
        for _ in range(scale):
            # Every scanline carries a filter byte first; 0 means "no filter".
            raw += b"\x00" + row

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render one frame of a ROM to a PNG, with no dependency."
    )
    parser.add_argument("rom", type=Path)
    parser.add_argument("--frame", type=int, default=600)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--budget", type=int, default=12_000_000)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    bus = Bus.post_boot(Cartridge.from_path(args.rom))

    executed = 0
    for _cpu, _address, _cycles in run(bus, args.budget):
        executed += 1
        if bus.ppu.frames >= args.frame:
            break
    else:
        print(
            f"only {bus.ppu.frames} frames in {executed:,} instructions",
            file=sys.stderr,
        )
        return 1

    print(f"frame {args.frame} reached after {executed:,} instructions")

    histogram = Counter(bus.ppu.framebuffer)
    total = SCREEN_WIDTH * SCREEN_HEIGHT
    shades = "   ".join(
        f"{shade}: {100 * histogram.get(shade, 0) / total:4.1f}%" for shade in range(4)
    )
    print(f"shades   {shades}")

    png = encode_png(bus.ppu.frame, args.scale)
    out = args.out or Path(f"{args.rom.stem.lower()}-{args.frame}.png")
    out.write_bytes(png)

    pixels = total * args.scale * args.scale
    print(
        f"wrote {out}   {SCREEN_WIDTH * args.scale}x{SCREEN_HEIGHT * args.scale}   "
        f"{len(png)} bytes   {len(png) * 8 / pixels:.3f} bits/pixel"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
