# Step 11B — The PPU as a renderer

## Goal

Turn what the ROM wrote into VRAM into 23040 bytes you can look at.

Step 11A gave the PPU a clock, registers and interrupts, and Tetris now gets past
its wait loop and fills VRAM. Nothing reads those bytes yet. This part adds the
three lookups that turn them into pixels, and a CLI flag that prints a frame.

Three `LCDC` bits join the ones 11A stored: bit 4 (which tile data base), bit 3
(which tile map) and bit 0 (draw the background at all). `SCX`, `SCY` and `BGP`
stop being dead storage.

---

## Theory

### 1. The VRAM map

Read this before anything else in this document. Every later section is an
arithmetic detail on top of this picture.

```
0x8000 ┌──────────────┐ ─┐
       │  block 0     │  │  128 tiles
0x8800 ├──────────────┤  │
       │  block 1     │  ├── TILE DATA · 6144 bytes · 384 tiles
0x9000 ├──────────────┤  │
       │  block 2     │  │  128 tiles
0x97FF └──────────────┘ ─┘
0x9800 ┌──────────────┐ ─┐
       │  tile map 0  │  │  1024 cells
0x9BFF ├──────────────┤  ├── TILE MAPS · 2048 bytes
       │  tile map 1  │  │  1024 cells
0x9FFF └──────────────┘ ─┘
```

Two regions, two units, one boundary at `0x97FF`/`0x9800`.

**Tile data** is the catalogue: 384 pictures of 8×8 pixels, 16 bytes each. It is
what can be drawn. It says nothing about where.

**A tile map** is the layout: 1024 cells, one byte each, and that byte is the
*number* of a tile in the catalogue. It says what goes where. It contains no
pixels.

The relationship is a foreign key. If a screen shows the same brick in 300 cells,
the brick is stored once in tile data and its number appears 300 times in the
map. Rendering a frame is the join.

Nothing marks a byte as one or the other. The role comes from the address the PPU
read it from: below `0x9800` it is read as pixels, 16 bytes at a time; at or
above, as a one-byte index. A game can write nonsense into `0x9800` and the PPU
will draw it as indices.

**Why the indirection exists.** The background is 256×256 pixels at 2 bits per
pixel:

```
65536 pixels × 2 bits = 131072 bits = 16 KiB
```

VRAM is 8 KiB. A flat framebuffer does not fit, and it is not close. The split
above is 6144 + 1024 + 1024 = 8192, the whole of VRAM with nothing left over.

The second reason is bandwidth, and it is the stronger one. A frame is 17556
machine cycles. Rewriting a flat 16 KiB framebuffer at 2 M-cycles per byte —
`LD (HL+), A` in a loop, storing a constant, computing nothing — costs 32768
M-cycles, nearly two frames. The CPU could not repaint the screen once per frame
even if it did nothing else. Rewriting a whole tile map costs 2048 M-cycles,
about 12% of a frame, and scrolling costs two register writes.

**Where 384 comes from.** It is a remainder, not a design target:

```
0x8000–0x97FF = 6144 bytes,  6144 / 16 = 384
8192 − 1024 − 1024 = 6144
```

384 is what is left of VRAM after reserving the two maps, divided by the size of
a tile. It has nothing to do with the 360 cells the screen shows. The catalogue
is a vocabulary, not one entry per cell: 1024 cells per map draw from 384 tiles,
so cells share tiles by construction.

### 2. A tile is sixteen bytes and two bitplanes

The DMG has no pixels in the ordinary sense. It has tiles: 8×8 blocks, four
colours, stored at `0x8000`–`0x97FF`.

Four colours is two bits per pixel, so a tile is 8 × 8 × 2 = 128 bits = 16 bytes.
Those two bits are a **colour index** 0–3, not a shade; section 6 turns indices
into shades. The two bits of one pixel are not stored together. They live in two
separate **bitplanes**, interleaved by row:

```
tile at address T:

   T+0, T+1   row 0   ─┐
   T+2, T+3   row 1    │   even byte: bit 0 of each of that row's 8 pixels
   T+4, T+5   row 2    ├─  odd byte:  bit 1 of each of that row's 8 pixels
      ...              │
   T+14, T+15 row 7   ─┘

decoding one row:

   byte 0, low plane   0  0  0  0  0  0  1  0    → 0x02
   byte 1, high plane  1  1  1  1  1  1  1  1    → 0xFF
                      ─────────────────────────
   index               2  2  2  2  2  2  3  2
                       ▲                    ▲
                       bit 7                bit 0
                       leftmost pixel       rightmost pixel
```

Two mistakes are common here.

The first byte of a pair is the **low** plane and the second is the **high**
plane. Get them the wrong way round and colours 1 and 2 swap everywhere, which
looks almost right and so survives a glance.

Bit 7 is the **leftmost** pixel. The pixel at x-offset `n` within a tile lives in
bit `7 - n`. Get this wrong and every tile is mirrored, which is obvious on
sight, so it is the easier of the two to catch.

### 3. A map is cells, and an index has two readings

A tile map is 32×32 **cells**, each one byte, each byte naming the tile to draw in
that cell. 32 cells × 8 pixels = 256, so one map describes a 256×256-pixel image.
The screen shows a 160×144 window onto it, which is 20×18 cells out of 1024.

Which of the two maps the background uses is `LCDC` bit 3. Two maps exist so a
game can build the next screen in one while the other is displayed.

The index is **one byte**, so a single base reaches 256 of the 384 tiles. Hence
two bases, chosen by `LCDC` bit 4:

```
LCDC bit 4 = 1        the "0x8000 method": index is UNSIGNED, 0–255

   0x8000 ┌─────────┐  index 0
          │         │
          │   ...   │      address = 0x8000 + index × 16
          │         │
   0x8FF0 └─────────┘  index 255


LCDC bit 4 = 0        the "0x8800 method": index is SIGNED, −128–127

   0x8800 ┌─────────┐  index 128  (0x80, read as −128)
          │         │
   0x9000 ├─────────┤  index 0    (0x00)      ◄── the base is HERE
          │         │
   0x97F0 └─────────┘  index 127  (0x7F)      address = 0x9000 + signed × 16
```

The name "the `0x8800` method" is historical and misleading. The base you compute
from is `0x9000`, not `0x8800`. `0x8800` is where the reachable region starts,
which is where index `0x80` lands once it is read as −128.

In terms of section 1's blocks: the unsigned method sees blocks 0 and 1, the
signed method sees blocks 1 and 2. `256 + 256 − 128 = 384`. They overlap on block
1, which is the point: a tile a game wants under both modes is stored once, in
the middle, and reachable from either end.

`to_signed8` in `bits.py` has been there since Step 01 for `JR`. This is its
second caller.

Sprites always use the `0x8000` method regardless of `LCDC` bit 4. That is Step
12's problem.

### 4. `LCDC` bits 4, 3 and 0

```
0xFF40 byte:  │ 7 │ 6 │ 5 │ 4 │ 3 │ 2 │ 1 │ 0 │
                │   │   │   │   │   │   │   └── BG & window enable      here
                │   │   │   │   │   │   └────── OBJ enable              Step 12
                │   │   │   │   │   └────────── OBJ size                Step 12
                │   │   │   │   └────────────── BG tile map  0x9800 / 0x9C00
                │   │   │   └────────────────── tile data    0x8800 / 0x8000
                │   │   └────────────────────── window enable           Step 12
                │   └────────────────────────── window tile map         Step 12
                └────────────────────────────── LCD & PPU enable        11A
```

Note the polarity of bit 4 against the diagram in section 3: **1 means `0x8000`**,
the unsigned method. It reads backwards from the address order.

Bit 0 on a DMG means "draw the background at all". When it is clear the
background and window are blank and the screen goes white, whatever is in VRAM.
Tetris clears it deliberately, before it has loaded any tiles.

### 5. Scrolling is modular arithmetic

`SCY` and `SCX` position the 160×144 screen inside the 256×256 background.

```
        SCX
     ├───────►│
              ├────────── 160 ──────────┤
   ┌─────────────────────────────────────────────────┐ 0
   │                                                 │
 S │          the 256 × 256 background,              │
 C │          described by one 32×32 tile map        │
 Y │                                                 │
 │ │        ┌─────────────────────────┐              │
 ▼ │        │                         │              │
   │        │   what the LCD shows    │  144         │
   │        │                         │              │
   │        └─────────────────────────┘              │
   │                                                 │
   └─────────────────────────────────────────────────┘ 255
```

Both axes wrap. The background is a torus: scroll off the right edge and you come
back on the left, off the bottom and you come back on the top. There is no
clipping and no edge, which is how a Game Boy scrolls an endless level through a
1 KiB map.

For pixel `x` of line `LY`, the arithmetic is:

```
    background_y = (LY + SCY) mod 256
    background_x = (x  + SCX) mod 256

    map cell     = (background_y / 8) × 32  +  (background_x / 8)
    tile index   = tile_map[ map cell ]
    tile address = per LCDC bit 4, section 3

    row in tile  = background_y mod 8
    bit in row   = 7 − (background_x mod 8)

    colour index = high plane bit  ×2  +  low plane bit
```

The two `mod 256` are the whole of scrolling. The two `mod 8` are the whole of
tiling. Every one of those five divisions is by a power of two, which is why the
arithmetic is free in hardware.

### 6. `BGP`, one more indirection

A tile stores a colour index, 0–3. That is not a shade. `BGP` at `0xFF47` maps
each of the four indices to one of four shades:

```
0xFF47 byte:  │ 7  6 │ 5  4 │ 3  2 │ 1  0 │
                └──┴── index 3     │   └──┴── index 0
                       └──┴── index 2
                              └──┴── index 1

shade  0 = white   1 = light grey   2 = dark grey   3 = black
```

`shade = (BGP >> (index × 2)) & 0b11`.

The indirection exists so a game can fade the screen, flash it, or invert it
without touching a byte of VRAM. One write to `BGP` recolours everything on
screen in four T-cycles. Tetris writes `0xE4`, which is `11 10 01 00`: the
identity mapping, index *n* to shade *n*.

Index 0 is the background's "nothing here" colour. Step 12 needs to know, per
pixel, whether the background's colour *index* was 0, because that is how a
sprite decides whether it is behind or in front. The shade cannot answer that,
since `BGP` can map index 0 to black. Keep it in mind when choosing what the
renderer stores.

That makes three lookups per pixel: map → catalogue → palette.

### 7. Where the core stops

Design constraint 1 in `PLAN.md`:

> The core is framework-independent. No pygame, no SDL, no I/O library inside
> `gameboy/`. The core exposes a framebuffer and accepts button state.

So the PPU's output is 160 × 144 = 23040 bytes, one per pixel, each `0`–`3`. A
byte per pixel is the whole product. What grey means, what green means, how big
the window is and how often it refreshes all belong to the frontend, which is
`__main__.py` for now. Step 13 gives it a real one.

A byte per pixel also means the natural container is a `bytearray` rather than
nested lists. Indexing is `y * 160 + x`, the same flattening the map cell
arithmetic in section 5 already does.

### 8. Python concepts this part introduces

- **`memoryview` and `.toreadonly()`.** Handing a caller your `bytearray`
  framebuffer hands them the ability to scribble on it. A read-only `memoryview`
  is a view, not a copy: no bytes move, and writes through it raise. Ruby has no
  equivalent. `String#freeze` freezes the object, not a window onto it, and `dup`
  copies.
- **Slice assignment on a `bytearray`.** `frame[start:start + 160] = line`
  replaces a run of bytes in one operation. It is the idiom for "write a
  scanline", and it is closer to `Array#[]=` with a range than to anything else
  in Ruby.
- **Integer division and `%` on powers of two.** `//` and `%` are the readable
  spelling; `>> 3` and `& 7` are the hardware's. Write the readable one. If Step
  13's profiler disagrees, it will say so with a number.
- **A module-level function for what is not about the object.** Decoding two
  plane bytes into eight indices knows nothing about a `PPU`. It takes two ints
  and returns a tuple. In Ruby it would be a private method anyway; in Python it
  goes outside the class, where it can be tested without constructing one.

---

## Tasks

### 1. The VRAM constants, and the map as a comment

Add to `ppu.py` the constants section 1 and 3 need: the size of a tile in bytes,
the two tile data bases, and the two tile map bases.

They are **bases for arithmetic**, not regions for dispatch. `memory_map.py` uses
`range` because its question is membership — does this address belong to this
device. The question here is `base + index * 16`, so these are plain ints.
`memory_map.VRAM` already covers the region.

Two of them, `0x8000` and `0x9000`, are two bases into the *same* region. A single
`range` cannot express that, which is the tell that `range` is the wrong shape.

Write section 1's diagram into the comment at the top of the file, with the
boundary marked. Name the unit of each region next to it: 16 bytes per tile, one
byte per cell. That comment is what stops you counting cells when you meant
tiles.

**Acceptance:** `(TILE_MAP_0 - TILE_DATA_UNSIGNED) // TILE_SIZE == 384`, as a
test. It ties the three constants together, so moving one breaks it.

---

### 2. A tile row, as a pure function

The smallest testable piece. Per sections 2 and 3:

```python
def tile_row(self, index: int, row: int) -> tuple[int, ...]:
    """The eight colour indices of one row of one tile, left to right."""
```

Two helpers behind it, each with its own name: one that turns a tile index into
an address per `LCDC` bit 4, and one that turns a pair of plane bytes into eight
indices. The second is a pure function of two bytes and belongs outside the
class, per section 8.

**Acceptance:** write `0x3C 0x7E` into VRAM as a tile's first row and assert the
eight indices are `0, 2, 3, 3, 3, 3, 2, 0`. Work that out by hand from the
diagram in section 2 before you run it. Then flip `LCDC` bit 4 and assert both
addressing modes against two indices, chosen for opposite reasons:

- index `0x00` resolves to `0x8000` unsigned and `0x9000` signed. The two differ,
  so it catches a base address taken from the region's start instead of from the
  middle.
- index `0x80` resolves to `0x8800` **both** ways. Work out on paper why
  `0x8000 + 128 × 16` and `0x9000 + (−128) × 16` land on the same byte. That is
  block 1, the overlap from section 3.

---

### 3. The background scanline, and the framebuffer

Render line `ly` when the mode changes to `HBLANK`. 11A's task 3 already gives
you that edge.

Per section 5, for each of the 160 pixels: the two `mod 256`, the map lookup, the
tile address, the row, the bit, the index, then `BGP`. Write it as the arithmetic
reads. The obvious optimisation, fetching a tile row once and using it for up to
eight pixels, is real and it is not this step's business.

Per section 4, if `LCDC` bit 0 is clear the line is shade 0 and nothing is
fetched.

Per section 6, keep the raw colour indices for the line as well as the shades.
160 bytes, and Step 12 needs them for sprite priority. That is the difference
between a line renderer Step 12 extends and one it rewrites. Say so in a comment.

Expose the frame as a read-only `memoryview`, per section 8.

**Acceptance:** a PPU with one non-blank tile at index 0, a tile map of all
zeros, `BGP = 0xE4` and `SCX = SCY = 0`, ticked one full frame, has a framebuffer
whose first 8 rows repeat that tile's pattern across all 160 columns. Then set
`SCX = 4` and assert the pattern shifted left by four, wrapping.

---

### 4. VRAM moves to the PPU

The bus's `self.vram` becomes `self.ppu.vram`, and `0x8000`–`0x9FFF` routes to
the PPU the way the LCD registers already do.

OAM stays on the bus: nothing in this step reads it, and moving a field because
Step 12 will want it is exactly the "trust me, we'll use this later" that
`PLAN.md` rules out. Move it in Step 12, when there is a reader.

**Acceptance:** `bus.read(0x8000)` reaches `ppu.vram`, and every existing bus test
still passes.

---

### 5. The CLI: `--frame`

Run until *N* frames have completed, then show one.

```
uv run python -m gameboy TETRIS.gb --frame 60
uv run python -m gameboy TETRIS.gb --frame 60 --out frame.ppm
```

Without `--out`, print the frame as text: one character per pixel from a
four-character ramp, so the terminal you are already looking at is the display.
160 columns is wide but it fits, and seeing the answer without leaving the shell
is worth more than fidelity here.

With `--out`, write a binary PPM. `P5` is greyscale, one byte per pixel, and its
whole header is three lines:

```
P5
160 144
255
```

followed by 23040 bytes. Map shade 0–3 to `0xFF, 0xAA, 0x55, 0x00`. Every image
viewer on the machine opens it and it needs no dependency, which matters: a
dependency here would be the first crack in design constraint 1.

Both live in `__main__.py`, next to `dump` and `describe`, per section 7.

Drive it with the existing `run()` generator and stop when `bus.ppu.frames`
reaches *N*. Do not write a second loop. Step 09 said two loops that tick
differently is a bug nobody finds until the PPU is drawing, and the PPU is now
drawing.

Give it an instruction budget too, so a ROM that never reaches VBlank stops
instead of hanging.

**Acceptance:** `--frame 1` on Tetris terminates and prints 144 lines of 160
characters.

---

### 6. Tests

**Unit level, `PPU` alone, no bus:**

- `tile_row` decoding, including the bitplane order and bit 7 being leftmost
- both tile data addressing modes, including the signed wrap at index `0x80`
- a rendered line with `SCX`/`SCY` at 0, and the same line scrolled, including
  the wrap past 255
- `LCDC` bit 0 clear renders shade 0 and does not read VRAM
- the framebuffer view is read-only: writing through it raises

**Bus level:**

- `0x8000`–`0x9FFF` routes to `ppu.vram`

**Acceptance:** no test runs an unbounded loop, and the render tests build their
VRAM by hand rather than loading a ROM.

---

### 7. Run the real thing, and look at it

```
uv run python -m gameboy ~/games/TETRIS.gb --frame 120
uv run python -m gameboy ~/games/TETRIS.gb --frame 600 --budget 12000000
```

Frame 120 is the copyright screen and frame 600 is the title screen. The menu
cursor is a sprite and will be on neither; that is Step 12, not a bug.

Expect the first thing you see to be wrong in some specific way: mirrored tiles,
or colours 1 and 2 swapped. Section 2 named both in advance so you can recognise
which one you are looking at instead of guessing — but **look at frame 600 to
judge the second one**. The copyright screen's font is monochrome, its two
bitplanes identical, so swapping them changes not one pixel. Print the shade
histogram if you want to see that for yourself: on frame 120 shades 1 and 2 are
both at 0%.

On frame 600, each letter of the logo is bevelled light-to-dark going down. With
the planes swapped that gradient inverts and the logo reads as lit from below.

If the frame is blank, work backwards in this order: is `LCDC` bit 7 set at the
moment you dumped, is bit 0 set, does the tile map contain anything but zeros,
does tile 0 contain anything but zeros. Four `--dump`s, and one of them is the
answer.

---

### 8. Docs

`README.md`: the step table, the `--frame` mode with example output, and the
closing section. "What is missing" has said "what it cannot do is draw" for two
steps. It can now. `PLAN.md`: Step 11B's row.

---

## Hints

- If the whole screen is one solid shade, check `LCDC` bit 0 before anything
  else. Tetris clears it early and sets it much later.
- If every tile is mirrored, you used bit `n` instead of bit `7 - n`.
- If the image is nearly right but the two middle shades are swapped, you have
  the bitplanes the wrong way round: the **first** byte of a row is the low
  plane.
- If the top eight rows are right and everything below repeats them,
  `background_y` is missing its `+ SCY` or its `// 8`, and the map lookup is
  stuck on row 0.
- If the image is sheared diagonally, the map cell arithmetic is multiplying by
  something other than 32.
- If tiles are right in some ROMs and garbage in others, it is the addressing
  mode. `LCDC` bit 4 set means base `0x8000` and an unsigned index; clear means
  base `0x9000` and a signed one. Both halves flip together.
- If you find yourself writing `range(0x8000, 0x9000)` for tile data, you have
  the region's end wrong; it is `0x9800`. `0x9000` is a base, not a boundary.
- If a frame takes visibly long to render, that is expected and not yet a
  problem. `PLAN.md` constraint 4: optimise once a game boots, and with
  measurements.
- Cross-check every number here against
  <https://gbdev.io/pandocs/Tile_Data.html> and its neighbours. The `LCDC` bit 4
  polarity and the `0x9000` base are the two that get copied wrong most often.

---

## Acceptance criteria

- [ ] The VRAM map is a comment at the top of `ppu.py`, with the boundary marked
      and each region's unit named
- [ ] Tile data bases and map bases are named constants, and `range` is not used
      for either
- [ ] Tile decoding is a pure function, tested against a hand-worked example
- [ ] Both tile data addressing modes are tested, including index `0x80`
- [ ] `SCX`/`SCY` wrap at 256, asserted by a test
- [ ] The framebuffer is 160×144 bytes of shades, exposed read-only, and the
      per-line colour indices are kept for Step 12
- [ ] `0x8000`–`0x9FFF` routes to `ppu.vram`
- [ ] `--frame N` and `--trace` and `--run` drive one loop
- [ ] A dumped frame of Tetris shows its tiles
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. You render a line at the end of mode 3, using the register values at that
   instant. Name a visual effect a game could produce that your renderer will get
   wrong, and say how you would find out whether any game you own does it.
2. VRAM is blocked during mode 3 on hardware and unblocked here. Describe a ROM
   that would run correctly on your emulator and fail on a real Game Boy. Is that
   the safe direction for the difference to point?
3. The framebuffer holds shades and not colour indices, and you kept a separate
   line of indices for Step 12. What would have gone wrong if you had stored only
   the indices and applied `BGP` at the very end, in the CLI?
4. A tile map has 1024 cells and VRAM holds 384 tiles. What does that ratio tell
   you about what a Game Boy screen can look like, and what would have to change
   for a game to draw a photograph?
