from dataclasses import dataclass, field
from enum import IntEnum
from typing import Final, Self

from gameboy.memory_map import BGP, LCDC, LY, LYC, OPEN_BUS, SCX, SCY, STAT

# Not modelled in this class:
# - VRAM and OAM blocking.
# - The variable length of mode 3.
# - The pixel FIFO.
# - The `LY == 153` quirk.
# - Sprites and the window.
#
# Geometry W×H: 160×144
# 1 scanline  = 456 dots
# 1 frame     = 154 scanlines  =  70224 dots
#               ├── 144 visible lines  (LY 0–143)
#               └──  10 blank lines    (LY 144–153)
#
# The VRAM treasure map
# Tile data: 384 tiles (6144 bytes)
# 0x8000 ┌──────────────┐ ─┐
#        │  block 0     │  ├── 128 tiles (128×16 = 2048 bytes)
# 0x8800 ├──────────────┤  │
#        │  block 1     │  ├── 128 tiles
# 0x9000 ├──────────────┤  │
#        │  block 2     │  ├── 128 tiles
# 0x97FF └──────────────┘ ─┘
#       ---------------------
# Tile maps: 2048 bytes
# 0x9800 ┌──────────────┐ ─┐
#        │  tile map 0  │  ├── 1024 bytes
# 0x9BFF └──────────────┘ ─┘
# 0x9C00 ┌──────────────┐ ─┐
#        │  tile map 1  │  ├── 1024 bytes
# 0x9FFF └──────────────┘ ─┘
#
# Tile data
#
# A tile is an 8×8 pixel square. Each pixel is two bits, and those two bits are
# an *index* 0–3: BGP translates that index into shades of green-ish. Each row of 8
# pixels is two bytes, one per bitplane, so a tile is 8 rows × 2 bytes = 16 bytes (the
# two bits are *not* stored together). Decoding one row:
#
#   byte 0 (low plane)   0  0  0  0  0  0  1  0   → 0x02
#   byte 1 (high plane)  1  1  1  1  1  1  1  1   → 0xFF
#                       ─────────────────────────
#   index                2  2  2  2  2  2  3  2
#                        ▲                    ▲
#                        bit 7 = leftmost     bit 0 = rightmost
#
#
# Tile maps
#
# - Each map has 32×32 = 1024 cells, one byte per cell.
# - The byte is the index naming which tile to draw from the collection.
# - A cell is 8 pixels on a side, so 32 cells × 8 = 256 pixels in total
# - The screen is a 20×18 cell viewport onto it, placed by SCX/SCY.
# - Two maps exist so a game can build the next screen in one while the other is
#   displayed.
#
# Tile index
#
# The index is one byte, so a single base reaches 256 of the 384 tiles. Hence two
# bases, chosen by `LCDC` bit 4:
#
# LCDC bit 4 = 1         the "0x8000 method": index is UNSIGNED, 0–255
#    0x8000 ┌─────────┐  index 0
#           │         │
#           │   ...   │      address = 0x8000 + index × 16
#           │         │
#    0x8FF0 └─────────┘  index 255
#
# LCDC bit 4 = 0         the "0x8800 method": index is SIGNED, −128–127
#    0x8800 ┌─────────┐  index 128  (0x80, read as −128)
#           │         │
#    0x9000 ├─────────┤  index 0    (0x00)      <- the base is HERE
#           │         │
#    0x97F0 └─────────┘  index 127  (0x7F)      address = 0x9000 + signed × 16

SCREEN_WIDTH: Final = 160
SCREEN_HEIGHT: Final = 144
LINES_PER_FRAME: Final = 154
SCANLINE_DOTS: Final = 456
OAM_SCAN_DOTS: Final = 80
DRAWING_DOTS: Final = 172
# Region for dispatch
VRAM_SIZE: Final = 0x2000
TILE_SIZE: Final = 16  # bytes: 8 rows × 2 bitplanes
# Bases for arithmetic
TILE_DATA_UNSIGNED: Final = 0x8000
TILE_DATA_SIGNED: Final = 0x9000
TILE_MAP_0: Final = 0x9800
TILE_MAP_1: Final = 0x9C00

_STAT_UNUSED: Final = 0x80  # bit 7, not wired, reads 1
_STAT_SELECTS: Final = 0x78  # bits 6-3, allowed for write select


class Mode(IntEnum):
    HBLANK = 0
    VBLANK = 1
    OAM_SCAN = 2
    DRAWING = 3


@dataclass(slots=True)
class PPU:
    vram: bytearray = field(default_factory=lambda: bytearray(VRAM_SIZE))
    framebuffer: bytearray = field(
        default_factory=lambda: bytearray(SCREEN_WIDTH * SCREEN_HEIGHT)
    )
    # position within current scanline (0-455)
    dots: int = 0
    # current horizontal line, which might be about to be drawn, being drawn, or just
    # been drawn. Read only.
    ly: int = 0
    # The Game Boy constantly compares the value of the LYC and LY registers. When both
    # values are identical, the LYC=LY flag in the STAT register is set, and (if
    # enabled) a STAT interrupt is requested.
    lyc: int = 0
    # main LCD Control register. Its bits toggle what elements are displayed on the
    # screen, and how.
    lcdc: int = 0
    # LCD status register
    # 0xFF41 byte:  │ 7 │ 6 │ 5 │ 4 │ 3 │ 2 │ 1  0 │
    #                 │   │   │   │   │   │   └──┴─── current mode     read-only
    #                 │   │   │   │   │   └────────── LY == LYC        read-only
    #                 │   │   │   │   └────────────── mode 0 select    writable
    #                 │   │   │   └────────────────── mode 1 select    writable
    #                 │   │   └────────────────────── mode 2 select    writable
    #                 │   └────────────────────────── LYC select       writable
    #                 └────────────────────────────── unused, reads 1
    # Only bits 6-3 live in this field. Bits 2-0 are computed from `mode`, `ly` and
    # `lyc` when the register is read, so they cannot go stale.
    stat: int = 0
    # These two registers specify the top-left coordinates of the visible 160×144 pixel
    # area within the 256×256 pixels BG map. Values in the range 0–255 may be used
    scy: int = 0
    scx: int = 0
    # Background palette. This register assigns gray shades to the color indices of the
    # BG and Window tiles.
    bgp: int = 0
    mode: Mode = Mode.OAM_SCAN
    stat_line: bool = False  # what the OR gate read on the prev sample
    frames: int = 0  # completed frames, for the CLI to count

    @classmethod
    def post_boot(cls) -> Self:
        return cls(
            lcdc=0x91,  # LCD on, tile data `0x8000`, map `0x9800`, BG on
            bgp=0xFC,
            mode=Mode.VBLANK,
        )

    def read(self, address: int) -> int:
        if address == LCDC:
            return self.lcdc
        if address == STAT:
            return self._stat_byte()
        if address == SCY:
            return self.scy
        if address == SCX:
            return self.scx
        if address == LY:
            return self.ly
        if address == LYC:
            return self.lyc
        if address == BGP:
            return self.bgp

        return OPEN_BUS

    def write(self, address: int, value: int) -> None:
        if address == LCDC:
            self.lcdc = value
            return
        if address == STAT:
            self.stat = value & _STAT_SELECTS
            return
        if address == SCY:
            self.scy = value
            return
        if address == SCX:
            self.scx = value
            return
        if address == LYC:
            self.lyc = value
            return
        if address == BGP:
            self.bgp = value
            return

    def _stat_byte(self) -> int:
        selects = self.stat & _STAT_SELECTS
        lyc_match = self.ly == self.lyc

        return _STAT_UNUSED | selects | (lyc_match << 2) | self.mode
