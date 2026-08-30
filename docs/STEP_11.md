# Step 11 — The PPU, part 1: tiles, the background map, and a frame you can look at

## Goal

The README has ended on the same paragraph for two steps now:

> Nothing writes `LY` yet, so `CP` never matches. An endless loop here is the
> correct outcome, and it ends in Step 11.

This is that step.

Tetris sits at `0x0233` reading `0xFF44` and comparing it to `148`. It is
waiting for the LCD to reach the first line of VBlank, because that is the only
moment a program can touch video memory without fighting the hardware for it.
Give it a register that counts, and the loop ends — and what the ROM does two
instructions later is the reason this step is bigger than "make `LY` go up".

Seven registers join the map:

| Address | Name | What it is |
| --- | --- | --- |
| `0xFF40` | `LCDC` | LCD control. Eight switches, of which this step uses four |
| `0xFF41` | `STAT` | LCD status. Which mode, whether `LY == LYC`, and four interrupt selects |
| `0xFF42` | `SCY` | how far down the 256×256 background the screen is looking |
| `0xFF43` | `SCX` | how far right |
| `0xFF44` | `LY` | the line being drawn, `0`–`153`. Read-only |
| `0xFF45` | `LYC` | the line a ROM wants to be told about |
| `0xFF47` | `BGP` | background palette: four indices to four shades |

And one output the project has never had: **160×144 bytes that mean something
when you look at them.**

Three things become observable that were not before:

- a ROM that gets past its VBlank wait, and starts configuring a machine it
  believes is real
- a second device raising interrupts, one of which (`VBlank`) is the one every
  game is actually built around
- a picture. Not a register dump, not a serial log — a picture, of tiles the ROM
  put in VRAM itself

> **Visual companion:** two things in this step draw far better than they read —
> the two bytes of a tile row becoming eight two-bit pixels, and the two tile
> data addressing modes sharing one region from opposite ends. Ask if theory
> sections 6 and 7 do not click.

---

## Theory

### 1. What the PPU is, and the shortcut this step takes

The Picture Processing Unit is a second processor. It has its own clock, its own
memory (VRAM and OAM), and its own program, which is fixed in silicon: draw 144
lines of 160 pixels, then rest, then do it again, forever, whether or not anyone
is watching.

It is not a frame buffer that the CPU fills in. It is a machine that walks the
screen at a fixed rate and *fetches* what it needs as it goes. That distinction
is the source of every constraint in this step. The CPU cannot write VRAM at an
arbitrary moment, because the PPU may be reading it. The screen cannot be
composed at an arbitrary moment, because a ROM is allowed to change `SCX`
between two scanlines and expect the second one to move.

Real hardware draws **one pixel per dot**, through a pipeline: a fetcher pulls
tile bytes into an 8-pixel FIFO, a shifter pops one pixel per dot onto the LCD.
Reproducing that is how you get the hard cases right — mid-scanline `SCX`
changes, the window turning on halfway across a line, the exact length of mode 3.

**We are not going to do that.** This step builds a *scanline renderer*: the PPU
tracks its position with a dot counter, and when a line's drawing period ends, it
computes all 160 of that line's pixels at once, from whatever the registers say
at that instant.

The trade is worth naming precisely, because it is the same trade Step 09 made
and it will be the one Step 13 revisits:

| | Dot renderer | Scanline renderer |
| --- | --- | --- |
| Register changes *between* lines | correct | correct |
| Register changes *within* a line | correct | wrong — the whole line uses the final value |
| Cost per frame | 70224 steps | 144 renders |
| Lines of code | several hundred | several dozen |

Almost no DMG game changes `SCX` mid-line. The ones that do are doing it
deliberately, to warp a status bar or shear an image, and they are famous for it.
A scanline renderer draws every commercial game correctly enough to play, and it
is the right amount of machine to build first.

### 2. The dot clock, and why 70224 was already familiar

The PPU is clocked by the same 4.194304 MHz crystal as everything else. Its unit
of time is called a **dot**, and one dot is one T-cycle — the same T-cycles the
opcode table has been reporting since Step 04, and the same ones `bus.tick`
already hands to the timer.

```
1 scanline  = 456 dots
1 frame     = 154 scanlines  =  70224 dots
              ├── 144 visible lines  (LY 0–143)
              └──  10 blank lines    (LY 144–153)
```

The screen is 144 lines tall, but the PPU counts to 154. The ten extra lines are
VBlank: no pixels are produced, VRAM is free, and the CPU has 4560 dots —
roughly 1140 machine cycles — to do everything that touches video memory.

70224 is the number the trace summary has been printed against since Step 04.
That was not decoration; it was this step, waiting.

### 3. The four modes

Within a visible line the PPU passes through three phases, and the whole of
VBlank is a fourth. `STAT` bits 1-0 report which one is current.

```
 LY 0                                                                LY 143
 │                                                                        │
 ├──── one scanline, 456 dots ──────────────────────────────────────────┤ │
 │                                                                        │
 │ mode 2 · 80 dots │ mode 3 · 172 dots       │ mode 0 · 204 dots        │
 │ OAM scan         │ drawing                 │ HBlank                   │
 └──────────────────┴─────────────────────────┴──────────────────────────┘
                                              ▲
                                              this project renders the whole
                                              line here, in one go

 LY 144 ─────────────────────────────────────────────────────── LY 153
 │ mode 1 · VBlank · 10 lines · 4560 dots                             │
```

| Mode | Name | Length | What the hardware is doing | VRAM | OAM |
| --- | --- | --- | --- | --- | --- |
| 2 | OAM scan | 80 dots | picking which sprites are on this line | free | blocked |
| 3 | Drawing | 172–289 dots | pushing pixels to the LCD | blocked | blocked |
| 0 | HBlank | the rest of 456 | nothing. Idling to the end of the line | free | free |
| 1 | VBlank | 4560 dots | nothing, for ten lines | free | free |

Two notes on that table.

Mode 3 is variable on hardware: it stretches when `SCX` is not a multiple of 8,
and when sprites are on the line. Mode 0 shrinks by exactly as much, so the line
is always 456. **This project fixes mode 3 at its 172-dot minimum**, which makes
mode 0 always 204. That is a lie, and it is the lie a scanline renderer is
already committed to.

The "blocked" columns describe hardware that refuses the CPU: a read of VRAM
during mode 3 returns `0xFF` and a write is dropped. **This project does not
model that either**, and theory section 13 says why.

### 4. `LY`, `LYC`, and `STAT`

`LY` is the line the PPU is on. It is the single most-read register in the
machine, because it is the only clock a program has that is synchronised to the
display. A ROM that wants to do something at a particular point in the frame
polls `LY` until it matches — which is exactly what Tetris is doing at `0x0233`.

`LY` is **read-only**. Writing it does nothing at all. This matters more than it
sounds: a bus that lets `LY` be written will let a stray `LD (HL), A` desynchronise
the display from the machine, and nothing will point at the cause.

`LYC` is the ROM's side of a comparison the hardware performs for it. On every
line, the PPU checks `LY == LYC` and reports the answer in `STAT` bit 2. A game
uses this to get an interrupt on one specific scanline — the classic use is a
status bar that does not scroll with the rest of the screen.

```
0xFF41 byte:  │ 7 │ 6 │ 5 │ 4 │ 3 │ 2 │ 1  0 │
                │   │   │   │   │   │   └──┴── current mode      read-only
                │   │   │   │   │   └────────── LY == LYC        read-only
                │   │   │   │   └────────────── mode 0 select    writable
                │   │   │   └────────────────── mode 1 select    writable
                │   │   └────────────────────── mode 2 select    writable
                │   └────────────────────────── LYC select       writable
                └────────────────────────────── unused, reads 1
```

`STAT` is the first register in this project where read and write see genuinely
different bits. Bits 2-0 are the PPU reporting to the ROM; bits 6-3 are the ROM
configuring the PPU. A write must land on bits 6-3 and leave 2-0 alone; a read
must assemble 2-0 from live state rather than from whatever was last written.

This is worth doing carefully, because the failure is quiet. A `STAT` that stores
the whole byte on write will read back a *stale* mode, and a ROM that polls
`STAT` for mode 0 instead of polling `LY` will hang — with no error, on a
register that looks right in a dump.

### 5. Two interrupts, and a rising edge on an OR

The PPU raises two of the five interrupts.

**`VBlank`, `IF` bit 0.** Fires once per frame, at the moment `LY` becomes 144.
Unconditional — there is no enable bit in `STAT` for it, only the usual `IE`.
This is the heartbeat every game is built on: sixty times a second, "the screen
is yours for the next 4560 dots".

**`LCD_STAT`, `IF` bit 1.** Fires on four selectable conditions, and it does not
fire the way you would first guess.

The four conditions are OR'd into a single internal signal — the **STAT interrupt
line** — and the interrupt is requested when that line goes from low to high.
Not while it is high. On the *transition*.

```
   LY == LYC ──── AND ──── STAT bit 6 ──┐
                                        │
   mode == 0 ──── AND ──── STAT bit 3 ──┤
                                        ├─── OR ───► did it rise 0 → 1 ?
   mode == 1 ──── AND ──── STAT bit 4 ──┤                    │
                                        │                    ▼
   mode == 2 ──── AND ──── STAT bit 5 ──┘             IF bit 1 · 0xFF0F
```

Compare that with the diagram at the top of `timer.py`. The timer watches one
bit through an AND and fires on the **falling** edge. The PPU watches four
conditions through an OR and fires on the **rising** edge. Different polarity,
different gate, identical discipline: keep the previous sample in a field,
compare, act on the change and not on the level.

The consequence has a name — **STAT blocking**. If mode 0 is selected and the
line is already high because `LY == LYC` just became true, entering mode 0 raises
no interrupt, because the line was never low in between. Games rely on this. An
implementation that requests `LCD_STAT` on every condition it notices will
deliver several interrupts per line instead of one, and a ROM whose handler
advances a counter will run its frame logic four times too often.

You already know how to write this. That is the point of having done the timer
first.

### 6. A tile is sixteen bytes and two bitplanes

The DMG has no pixels in the ordinary sense. It has **tiles**: 8×8 blocks, four
colours, stored at `0x8000`–`0x97FF`. 384 of them fit.

Four colours is two bits per pixel, so a tile is 8 × 8 × 2 = 128 bits = 16 bytes.
The interesting part is how those two bits are laid out. Not as pairs — as two
separate **bitplanes**, interleaved by row:

```
tile at address T:

   T+0, T+1   row 0   ─┐
   T+2, T+3   row 1    │   even byte: bit 0 of each of that row's 8 pixels
   T+4, T+5   row 2    ├─  odd byte:  bit 1 of each of that row's 8 pixels
      ...              │
   T+14, T+15 row 7   ─┘

decoding one row:

   low  byte  0 1 1 1 1 1 1 0
   high byte  0 0 1 1 1 1 0 0
              ─────────────────
   index      0 1 3 3 3 3 1 0
              ▲             ▲
              bit 7         bit 0
              leftmost      rightmost
```

Two things in that picture are the classic mistakes.

The first byte of a pair is the **low** plane and the second is the **high**
plane. Get them the wrong way round and colours 1 and 2 swap everywhere — which
looks *almost* right, which is why it survives a glance.

Bit 7 is the **leftmost** pixel. The pixel at x-offset `n` within a tile lives in
bit `7 - n`. Get this wrong and every tile is mirrored, which looks obviously
wrong and is therefore the easier of the two bugs to have.

### 7. Two tile maps, and two ways to name a tile

Tiles are pictures. A **tile map** says where they go.

```
0x8000 ┌──────────────────────────┐
       │   tile data              │  384 tiles × 16 bytes
0x9800 ├──────────────────────────┤
       │   tile map 0             │  32 × 32 = 1024 bytes, one index per cell
0x9C00 ├──────────────────────────┤
       │   tile map 1             │  1024 bytes
0xA000 └──────────────────────────┘
```

A tile map is 32×32 **bytes**, each one an index naming the tile to draw in that
cell. 32 cells × 8 pixels = 256, so a map describes a 256×256-pixel image. The
screen shows a 160×144 window onto it.

Which of the two maps the background uses is `LCDC` bit 3. Two maps exist so a
game can build the next screen in one while the other is being displayed.

Now the part that trips everyone. **The tile index is interpreted in one of two
ways**, chosen by `LCDC` bit 4:

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

The name "the `0x8800` method" is the historical one and it is actively
misleading: the base address you compute from is `0x9000`, not `0x8800`. `0x8800`
is merely where the region starts, which is where index `0x80` lands once you
read it as −128.

`to_signed8` in `bits.py` has been sitting there since Step 01 for `JR`. This is
its second caller.

Why two methods at all: the two ranges overlap at `0x8800`–`0x8FFF`, so tiles a
game wants available under both addressing modes are stored once, in the middle,
and reachable from either end. Sprites, when they arrive in Step 12, always use
the `0x8000` method regardless of `LCDC` bit 4 — a detail to file away, not to
implement yet.

### 8. `LCDC`, bit by bit

```
0xFF40 byte:  │ 7 │ 6 │ 5 │ 4 │ 3 │ 2 │ 1 │ 0 │
                │   │   │   │   │   │   │   └── BG & window enable
                │   │   │   │   │   │   └────── OBJ enable            Step 12
                │   │   │   │   │   └────────── OBJ size 8×8 / 8×16   Step 12
                │   │   │   │   └────────────── BG tile map   0x9800 / 0x9C00
                │   │   │   └────────────────── tile data     0x8800 / 0x8000
                │   │   └────────────────────── window enable         Step 12
                │   └────────────────────────── window tile map       Step 12
                └────────────────────────────── LCD & PPU enable
```

This step uses bits 7, 4, 3 and 0. The other four are stored and ignored, which
is not a stub — a ROM writes the whole byte and must read the whole byte back.

Note the polarity of bit 4 against the diagram in section 7: **1 means `0x8000`**,
the unsigned method. It reads backwards from the address order, and it is the
single most-transposed bit in the register.

Bit 0 on a DMG means "draw the background at all". When it is clear, the
background and window are blank — the screen goes white — regardless of what is
in VRAM. Tetris clears it, deliberately, before it has loaded any tiles.

### 9. Scrolling is modular arithmetic

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

Both axes **wrap**. The background is a torus: scroll off the right edge and you
come back on the left, off the bottom and you come back on the top. There is no
clipping and no edge — which is why a Game Boy can scroll an infinite level
through a 1 KiB map.

For pixel `x` of line `LY`, the arithmetic is:

```
    background_y = (LY + SCY) mod 256
    background_x = (x  + SCX) mod 256

    map cell     = (background_y / 8) × 32  +  (background_x / 8)
    tile index   = tile_map[ map cell ]
    tile address = per LCDC bit 4, section 7

    row in tile  = background_y mod 8
    bit in row   = 7 − (background_x mod 8)

    colour index = high plane bit  ×2  +  low plane bit
```

The two `mod 256` are the whole of scrolling. The two `mod 8` are the whole of
tiling. Every one of those five divisions is by a power of two, which is not a
coincidence — it is why the arithmetic is free in hardware.

### 10. `BGP`, one more indirection

A tile stores a **colour index**, 0–3. That is not a shade. `BGP` at `0xFF47`
maps each of the four indices to one of four shades:

```
0xFF47 byte:  │ 7  6 │ 5  4 │ 3  2 │ 1  0 │
                └──┴── index 3     │   └──┴── index 0
                       └──┴── index 2
                              └──┴── index 1

shade  0 = white   1 = light grey   2 = dark grey   3 = black
```

`shade = (BGP >> (index × 2)) & 0b11`.

The indirection exists so a game can fade the screen, flash it, or invert it
without touching a single byte of VRAM — one write to `BGP` recolours everything
on screen in four T-cycles. Tetris writes `0xE4`, which is `11 10 01 00`: the
identity mapping, index *n* to shade *n*.

Index 0 is worth naming separately. It is the background's "nothing here" colour,
and Step 12 will need to know, per pixel, whether the background's colour *index*
was 0 — that is how a sprite decides whether it is behind or in front. The shade
cannot answer that question, because `BGP` can map index 0 to black. Keep this in
mind when choosing what the renderer stores.

### 11. Turning the LCD off, which Tetris does on line 148

`LCDC` bit 7 does not dim the screen. It **stops the PPU**.

When it goes to 0: `LY` resets to 0 and stays there, the mode goes to 0, the dot
counter resets, no interrupts are raised, and the screen is blank. When it goes
back to 1, the PPU restarts at the top of a fresh frame.

This is not an edge case to handle for completeness. It is the very next thing
the ROM in `~/games` does:

```
022F: 3E 80    LD  A, 0x80      ; LCD on, everything else off
0231: E0 40    LDH (0xFF40), A
0233: F0 44    LDH A, (0xFF44)  ; LY
0235: FE 94    CP  A, 0x94      ; 148 — the fifth line of VBlank
0237: 20 FA    JR  NZ, -6       ; spin until we are safely inside VBlank
0239: 3E 03    LD  A, 0x03      ; bit 7 CLEAR — LCD off. BG and OBJ enabled
023B: E0 40    LDH (0xFF40), A
023D: 3E E4    LD  A, 0xE4      ; BGP  = identity
023F: E0 47    LDH (0xFF47), A
0241: E0 48    LDH (0xFF48), A  ; OBP0
0243: 3E C4    LD  A, 0xC4
0245: E0 49    LDH (0xFF49), A  ; OBP1
```

Read that sequence for what it is: **turn the LCD on, wait for VBlank, turn it
off.** The wait is not for VBlank's sake. It is because switching the LCD off
outside VBlank is documented as damaging on real hardware, so every game does the
polite thing first. Only then does it load palettes and start filling VRAM, with
the PPU stopped and the whole address space to itself.

Which means the LCD-off path is on the critical path for this step. Get `LY`
counting and forget bit 7, and the ROM will get past `0x0237`, disable the LCD,
and then be shown an `LY` that keeps advancing anyway — and the next wait loop it
writes will behave in a way that no amount of staring at your renderer will
explain.

### 12. Where the core stops

Design constraint 1 in `PLAN.md`:

> The core is framework-independent. No pygame, no SDL, no I/O library inside
> `gameboy/`. The core exposes a framebuffer and accepts button state.

So the PPU's output is 160 × 144 = 23040 bytes, one per pixel, each `0`–`3`.
Not RGB, not a PNG, not a file. A byte per pixel is the whole product, and every
question about what grey means, what green means, how big the window is and how
often it refreshes belongs to somebody else.

That somebody is `__main__.py` for now. The CLI is the frontend layer today;
Step 13 gives it a real one.

A byte per pixel also means the natural container is a `bytearray` rather than
nested lists. Indexing is `y * 160 + x`, which is the same flattening the tile
map arithmetic in section 9 already does.

### 13. What is deliberately not modelled

Say these out loud now, in a comment at the top of `ppu.py`, the way `serial.py`
says what the link cable does not do.

- **VRAM and OAM blocking.** During mode 3 a real CPU read of VRAM returns `0xFF`.
  Modelling it would make the emulator *stricter* than hardware in exactly the
  wrong direction: a game with a timing bug that hardware forgives would break
  here. It also does nothing for us, because the ROMs that test it are not the
  ROMs we are running. Revisit if `dmg-acid2` disagrees.
- **The variable length of mode 3.** Fixed at 172 dots, per section 3.
- **The pixel FIFO.** Per section 1. This is the one that a mid-line `SCX` change
  would need.
- **The `LY == 153` quirk.** On hardware `LY` reads 0 for all but the first 4 dots
  of line 153. A handful of ROMs detect this. None of ours do.
- **Sprites and the window.** Step 12. `LCDC` bits 6, 5, 2 and 1 are stored and
  ignored, and that is a deliberate state, not an unfinished one.

The rule that has held since Step 03 still holds: an unimplemented read returns
something plausible, an unimplemented write is dropped, nothing raises.

### 14. The state the boot ROM left behind

The project skips the boot ROM and starts at `0x0100` with the registers the
boot ROM would have left. The PPU needs the same treatment, and the values
matter more here than they did for the timer — a game is entitled to assume the
LCD is *already on*, because the boot ROM turned it on to draw the Nintendo logo.

| Register | Post-boot | Meaning |
| --- | --- | --- |
| `LCDC` | `0x91` | LCD on, tile data `0x8000`, map `0x9800`, BG on |
| `STAT` | `0x85` | mode 1, `LY == LYC`, no selects |
| `SCY` | `0x00` | |
| `SCX` | `0x00` | |
| `LY` | `0x00` | |
| `LYC` | `0x00` | |
| `BGP` | `0xFC` | `11 11 11 00` — index 0 white, everything else black |

There is a related debt to settle here. Step 09 specified `Timer.post_boot()`
with `DIV == 0xAB`; the class does not have it, and `__main__.py` builds a plain
`Timer()`. `DIV` therefore starts at 0 in every run the CLI has ever done. Task 8
collects all of this into one place.

### 15. Python concepts this step introduces

- **`memoryview` and `.toreadonly()`.** Handing a caller your `bytearray`
  framebuffer hands them the ability to scribble on it. A read-only `memoryview`
  is a *view*, not a copy: no bytes move, and writes through it raise. Ruby has
  no equivalent — `String#freeze` freezes the object, not a window onto it, and
  `dup` copies. This is the first place in the project where "share without
  copying, but read-only" is worth the vocabulary.
- **`enum.IntFlag`.** `LCDC` is eight independent booleans in one byte, which is
  what `IntFlag` is for: named members that combine with `|` and test with `in`.
  Whether it beats eight `@property`s named after Pan Docs is a genuine judgement
  call, and task 2 asks you to make it rather than telling you the answer.
- **Slice assignment on a `bytearray`.** `frame[start:start + 160] = line`
  replaces a run of bytes in one operation. It is the idiom for "write a
  scanline", and it is closer to `Array#[]=` with a range than to anything else
  in Ruby.
- **Integer division and `%` on powers of two.** `//` and `%` are the readable
  spelling; `>> 3` and `& 7` are the hardware's. Write the readable one. If
  Step 13's profiler disagrees, it will say so with a number.

---

## Tasks

### 1. `ppu.py`, the state and the geometry

A new module. Like `timer.py` it imports only `bits` and `memory_map`, and it is
tested without a bus.

The geometry constants first, because every later task indexes with them:
screen width and height, dots per line, lines per frame, the length of modes 2
and 3, the two tile map bases, the two tile data bases, and the size of a tile in
bytes. Name them; do not spell `456` in three places.

The state is roughly:

```python
@dataclass(slots=True)
class PPU:
    vram: bytearray = field(default_factory=lambda: bytearray(0x2000))
    framebuffer: bytearray = field(
        default_factory=lambda: bytearray(SCREEN_WIDTH * SCREEN_HEIGHT)
    )
    dots: int = 0          # position within the current scanline, 0–455
    ly: int = 0
    lyc: int = 0
    lcdc: int = 0
    stat: int = 0          # only bits 6-3 live here; 2-0 are computed
    scy: int = 0
    scx: int = 0
    bgp: int = 0
    mode: Mode = Mode.OAM_SCAN
    stat_line: bool = False   # what the OR gate read on the previous sample
    frames: int = 0           # completed frames, for the CLI to count
```

`Mode` is an `IntEnum` with the hardware's own numbering — `HBLANK = 0`,
`VBLANK = 1`, `OAM_SCAN = 2`, `DRAWING = 3` — so that assembling `STAT` bits 1-0
is a cast and not a lookup table.

Add `post_boot()` per theory section 14.

Write the "not modelled" comment from theory section 13 now, at the top of the
file, before any of it is tempting to forget.

**Acceptance:** `PPU.post_boot().lcdc == 0x91`, and `456`, `154` and `160` each
appear exactly once in the module.

---

### 2. The registers, and who owns which bits

| Address | Read | Write |
| --- | --- | --- |
| `0xFF40` | `lcdc` | `lcdc` — and act on bit 7 changing, task 5 |
| `0xFF41` | bits 6-3 from `stat`, bit 2 from `ly == lyc`, bits 1-0 from `mode`, bit 7 set | bits 6-3 only |
| `0xFF42` | `scy` | `scy` |
| `0xFF43` | `scx` | `scx` |
| `0xFF44` | `ly` | **dropped** |
| `0xFF45` | `lyc` | `lyc` |
| `0xFF47` | `bgp` | `bgp` |

Per theory section 4, `STAT` is the one that repays care. Read assembles; write
masks. Neither touches the other's bits.

Put the addresses in `memory_map.py` with the rest of the map, and decide there
what range the bus will match on — theory section 8 lists four `LCDC` bits this
step does not use, and `0xFF46`, `0xFF48`–`0xFF4B` belong to Step 12. Leaving
them to fall through to the bus's existing `io` array gives correct read-back for
free; claiming them now means writing storage for registers nothing reads. Prefer
the first.

This is also where task 1's `IntFlag`-or-properties decision gets made, because
this is the first code that has to ask "is bit 4 set". Write it the way that
makes `_tile_data_base` readable in task 6, and say in a comment why.

**Acceptance:** writing `0xFF` to `0xFF44` leaves `LY` unchanged. Writing `0xFF`
to `0xFF41` and reading it back gives bits 6-3 set, bit 7 set, and bits 2-0
reporting live state rather than the `1`s that were written.

---

### 3. `tick`, the dot counter and the mode machine

No rendering, no interrupts. Just position.

```python
def tick(self, cycles: int) -> tuple[Interrupt, ...]:
    """Advance the PPU by `cycles` dots. Returns the interrupts to request."""
```

Return `()` for now; task 4 fills it.

Step 09's question 3 asked what shape a device with two interrupts should return,
and this is the answer being proposed: a tuple, empty on the common path, because
`()` is a singleton in CPython and costs nothing. `Timer.tick` keeps its `bool` —
one source, one answer, and changing it would be churn without a reader. If you
disagree, the asymmetry is worth an argument; have it now rather than in Step 12.

The machine, per theory section 3:

```
    dots += cycles

    while dots >= 456:
        dots -= 456
        ly = (ly + 1) mod 154

    mode for the current position:
        ly >= 144            → VBLANK
        dots <  80           → OAM_SCAN
        dots <  80 + 172     → DRAWING
        otherwise            → HBLANK
```

Deriving the mode from the position rather than tracking it as a state machine
with transitions is the simpler of the two shapes, and it is correct because the
mode genuinely is a pure function of `(ly, dots)`. The transitions still matter —
tasks 4 and 7 need to know when one *happened* — so compare the newly derived
mode against the stored one and you have the edge, with no duplicate state.

The `while` rather than an `if` is deliberate. The longest instruction is 24
T-cycles and a line is 456, so it can only ever run once today — but write the
loop, because Step 15's `HALT` in a bank-switching loop is not somewhere you want
to discover this.

**Acceptance:** a `PPU` ticked 70224 dots in steps of 4 is back at `ly == 0`,
`dots == 0`. Ticked 456, `ly == 1`. Ticked 456 × 144, `mode is Mode.VBLANK`.

---

### 4. The two interrupts

Per theory section 5.

**VBlank** on the transition into `LY == 144`. Once per frame. Detect it from
the mode change, not from `ly == 144`, or a tick that lands twice inside line 144
will raise it twice.

**STAT** on the rising edge of the OR. One helper that computes the line's
current level from `(mode, ly, lyc, stat)`, and one comparison against
`stat_line`. The shape is `Timer._advance_tima` with the polarity flipped, and if
your version does not look like a sibling of it, one of the two is doing more
than it needs to.

Increment `frames` when VBlank is entered — the CLI needs a way to say "run until
frame 3", and the VBlank transition is the definition of a completed frame.

**Acceptance:** a `PPU` ticked across the whole of one frame returns
`Interrupt.VBLANK` exactly once. With `STAT` bit 3 set (mode 0 select) and bit 6
clear, it returns `Interrupt.LCD_STAT` exactly 144 times — once per visible line,
not once per tick spent in mode 0. With bits 3 and 6 both set and `LYC == 0`, line
0 produces **one** `LCD_STAT`, not two: that assertion is STAT blocking, and it is
the one that fails if you fire on level instead of edge.

---

### 5. Turning the LCD off

Per theory section 11. When `LCDC` bit 7 goes from set to clear: `ly = 0`,
`dots = 0`, mode to `HBLANK`, `stat_line` to `False`, and fill the framebuffer
with shade 0.

While bit 7 is clear, `tick` returns immediately — no counting, no interrupts.

When it goes from clear to set, the PPU is already at the top of a frame from the
reset above, so there is nothing extra to do. Convince yourself of that rather
than taking it on trust; it is only true because the disable path reset the
counters instead of freezing them.

**Acceptance:** with the LCD off, ticking 70224 dots leaves `ly == 0` and
`frames` unchanged. Writing `0x91` then `0x11` to `0xFF40` puts `LY` back to 0
from wherever it was.

---

### 6. A tile row, as a pure function

Before any rendering, the smallest testable piece. Per theory sections 6 and 7:

```python
def tile_row(self, index: int, row: int) -> tuple[int, ...]:
    """The eight colour indices of one row of one tile, left to right."""
```

Two helpers behind it, both worth their own names: one that turns a tile index
into an address per `LCDC` bit 4, and one that turns a pair of plane bytes into
eight indices. The second is a pure function of two bytes and belongs outside the
class — it knows nothing about a PPU.

**Acceptance:** write `0x3C 0x7E` into VRAM as a tile's first row and assert the
eight indices are `0, 2, 3, 3, 3, 3, 2, 0`. Work that out by hand from the
diagram in section 6 before you run it; the whole value of this task is that you
can say what the answer should be. Then flip `LCDC` bit 4 and assert both
addressing modes against two indices, chosen for opposite reasons:

- index `0x00` resolves to `0x8000` unsigned and `0x9000` signed. It differs, so
  it is the one that catches a base address you took from the region's start
  instead of from the middle.
- index `0x80` resolves to `0x8800` **both** ways. It agrees, and working out on
  paper why `0x8000 + 128 × 16` and `0x9000 + (−128) × 16` land on the same byte
  is the moment the overlapping region in section 7 stops being a diagram.

---

### 7. The background scanline, and the framebuffer

Render line `ly` when the mode changes to `HBLANK`, per theory section 3.

Per theory section 9, for each of the 160 pixels: the two `mod 256`, the map
lookup, the tile address, the row, the bit, the index, then `BGP`. Write it as
the arithmetic reads. The obvious optimisation — fetch a tile row once and use it
for up to eight pixels — is a real one and it is not this step's business.

Per theory section 8, if `LCDC` bit 0 is clear the line is shade 0 and nothing is
fetched.

Per theory section 10, keep the raw colour indices for the line as well as the
shades. 160 bytes, and Step 12 needs them for sprite priority. Storing them now
is not speculation: it is the difference between a line renderer that Step 12
extends and one it rewrites. Say so in a comment.

Expose the frame as a read-only `memoryview`, per theory section 15.

**Acceptance:** a PPU with one non-blank tile at index 0, a tile map of all
zeros, `BGP = 0xE4` and `SCX = SCY = 0`, ticked one full frame, has a framebuffer
whose first 8 rows repeat that tile's pattern across all 160 columns. Then set
`SCX = 4` and assert the pattern shifted left by four, wrapping.

---

### 8. The bus, and one place that assembles a machine

Three changes, and a debt.

**VRAM moves to the PPU.** The bus's `self.vram` becomes `self.ppu.vram`, and
`0x8000`–`0x9FFF` routes to the PPU the way the timer registers do. OAM stays on
the bus: nothing in this step reads it, and moving a field because Step 12 will
want it is exactly the "trust me, we'll use this later" that `PLAN.md` rules out.
Move it in Step 12, when there is a reader.

**The LCD registers route to the PPU**, per task 2.

**`bus.tick` fans out to both devices.** The PPU returns a tuple; loop over it and
`request` each.

**The debt from theory section 14.** `Timer.post_boot()` does not exist, and
`__main__.py` constructs `Bus(cartridge, Timer())` in three places. Adding a
third constructor argument would make that four things to get right per call
site. A `Bus.post_boot(cartridge)` classmethod that assembles a machine in the
state the boot ROM leaves it — post-boot timer, post-boot PPU — replaces all
three call sites with one, and is the honest home for a fact that is currently
split between `Registers.post_boot` and nowhere.

Keep the injecting constructor for tests that want a `Timer` in a chosen state.

**Acceptance:** `bus.read(0x8000)` reaches `ppu.vram`, and `Bus.post_boot`
produces a bus whose `DIV` reads `0xAB` and whose `LCDC` reads `0x91`. `--trace 3`
on Tetris still prints what it printed before this step.

---

### 9. The CLI: `--frame`

The step's payoff. Run until *N* frames have completed, then show one.

```
uv run python -m gameboy TETRIS.gb --frame 60
uv run python -m gameboy TETRIS.gb --frame 60 --out frame.ppm
```

Without `--out`, print the frame as text — one character per pixel from a
four-character ramp, so that the terminal you are already looking at is the
display. 160 columns is wide but it fits, and being able to see the answer
without leaving the shell is worth more than fidelity here.

With `--out`, write a binary PPM. `P5` is greyscale, one byte per pixel, and its
whole header is three lines:

```
P5
160 144
255
```

followed by 23040 bytes. Map shade 0–3 to `0xFF, 0xAA, 0x55, 0x00`. Every image
viewer on the machine opens it, and it needs no dependency — which is the point,
because a dependency here would be the first crack in design constraint 1.

Both live in `__main__.py`, next to `dump` and `describe`, per theory section 12.

Drive it with the existing `run()` generator and stop when `bus.ppu.frames`
reaches *N*. Do not write a second loop. Step 09 said two loops that tick
differently is a bug nobody finds until the PPU is drawing, and this is the step
where that stops being hypothetical.

Give it an instruction budget too, so a ROM that never reaches VBlank stops
instead of hanging.

**Acceptance:** `--frame 1` on Tetris terminates, and prints 144 lines of 160
characters.

---

### 10. Tests

**Unit level, `PPU` alone, no bus:**

- the mode machine: a table of `(ly, dots, expected_mode)` covering all four,
  including the boundaries at dots 79/80 and 251/252
- a full frame is 70224 dots and returns to `ly == 0`
- `LY` is read-only through `read`/`write`
- `STAT` read assembles live bits; `STAT` write lands only on bits 6-3
- VBlank fires once per frame
- the STAT rising edge, and STAT blocking — the assertion in task 4
- `tile_row` decoding, including the bitplane order and bit 7 being leftmost
- both tile data addressing modes, including the signed wrap at index `0x80`
- LCD disable resets `LY` and stops the clock
- a rendered line with `SCX`/`SCY` at 0, and the same line scrolled, including
  the wrap past 255

**Bus level:**

- `0x8000`–`0x9FFF` routes to `ppu.vram`
- the seven registers route both ways
- `bus.tick` across a frame sets `IF` bit 0
- `Bus.post_boot` gives `DIV == 0xAB` and `LCDC == 0x91`

**Program level, and this is the one that matters:**

A program that does what Tetris does. Something like:

```
; at 0x0100:  LD A, 0x80  ; LDH (0xFF40), A   ; LCD on
;             LDH A, (0xFF44) ; CP 0x94 ; JR NZ, -6   ; wait for line 148
;             INC B                                    ; got out
;             LD A, 0x03  ; LDH (0xFF40), A   ; LCD off
```

Step it in a bounded loop and assert that `B` incremented. That loop is the one
the emulator has never escaped, and this is the test that says it now does.

**Acceptance:** that test fails if you make `LY` writable, and fails differently
if you drop the `ppu.tick` call from `bus.tick`. Check both. A PPU test that
passes with the PPU unplugged is testing your fixture.

---

### 11. Run the real thing

**Tetris.** It has been stuck at `0x0233` since Step 08.

```
uv run python -m gameboy ~/games/TETRIS.gb --trace 200 | tail -40
```

First: does it get past `0x0237`? Then does it write `0x03` to `0xFF40` two
instructions later, exactly as theory section 11 predicts? Report where it goes
after that — the answer should be a long run of VRAM writes, which is a game
loading its font.

Then:

```
uv run python -m gameboy ~/games/TETRIS.gb --frame 120
```

Expect the copyright and title screen's **background**. The menu cursor is a
sprite and will not be there; that is Step 12, not a bug. Expect, too, that the
first thing you see is wrong in some specific way — mirrored tiles, or colours 1
and 2 swapped. Section 6 named both in advance so that you can recognise which
one you are looking at instead of guessing.

If the frame is blank, work backwards in this order: is `LCDC` bit 7 set at the
moment you dumped, is bit 0 set, does the tile map contain anything but zeros,
does tile 0 contain anything but zeros. Four `--dump`s, and one of them is the
answer.

---

### 12. Docs

`README.md`: the step table, the `--frame` mode with example output, and the
closing section. "What is missing" has said "what it cannot do is draw" for two
steps. It can now.

`PLAN.md`: Step 11's row.

A note somewhere on what the scanline renderer gives up, per theory section 1 —
the next person to read this will want to know whether it was an oversight or a
decision.

---

## Hints

- If the whole screen is one solid shade, check `LCDC` bit 0 before you check
  anything else. Tetris clears it early and sets it much later.
- If every tile is mirrored, you used bit `n` instead of bit `7 - n`.
- If the image is nearly right but the two middle shades are swapped, you have
  the bitplanes the wrong way round: the **first** byte of a row is the low
  plane.
- If the top eight rows of the screen are right and everything below repeats
  them, `background_y` is missing its `+ SCY` or its `// 8`, and the map lookup
  is stuck on row 0.
- If the image is sheared diagonally, the map cell arithmetic is multiplying by
  something other than 32.
- If tiles are right in some ROMs and garbage in others, it is the addressing
  mode. `LCDC` bit 4 set means base `0x8000` and an unsigned index; clear means
  base `0x9000` and a signed one. Both halves flip together.
- If `LCD_STAT` fires hundreds of times a frame, you are testing the level and
  not the edge. `timer.py` already contains the shape you want.
- If VBlank fires twice per frame, you are detecting `ly == 144` rather than the
  transition into it.
- If Tetris escapes the wait loop and then hangs somewhere new, that is progress
  and the trace will name the address. Check first whether `LCDC` bit 7 is clear
  and your `tick` is counting anyway.
- If a frame takes visibly long to render, that is expected and not yet a
  problem. `PLAN.md` constraint 4: optimise once a game boots, and with
  measurements.
- Cross-check every number here against
  <https://gbdev.io/pandocs/Rendering.html> and its neighbours before writing it
  down. The `LCDC` bit 4 polarity and the `0x9000` base are the two that get
  copied wrong most often.

---

## Acceptance criteria

- [ ] `LY` counts 0–153, resets, and is read-only through the bus
- [ ] The mode is derived from `(ly, dots)`, and mode 3 is a named constant
- [ ] `STAT` reads live bits 2-0 and writes only bits 6-3
- [ ] `VBlank` sets `IF` bit 0 once per frame
- [ ] `LCD_STAT` fires on the rising edge of the OR, and STAT blocking is
      asserted by a test
- [ ] Clearing `LCDC` bit 7 stops the PPU and resets `LY` to 0
- [ ] Tile decoding is a pure function, tested against a hand-worked example
- [ ] Both tile data addressing modes are tested, including index `0x80`
- [ ] `SCX`/`SCY` wrap at 256, asserted by a test
- [ ] The framebuffer is 160×144 bytes of shades, exposed read-only, and the
      per-line colour indices are kept for Step 12
- [ ] `PPU` imports nothing from the package but `bits`, `memory_map` and
      `interrupts`, and is tested without a bus
- [ ] `PPU.post_boot()` matches the table in theory section 14, and
      `Timer.post_boot()` finally exists
- [ ] `Bus.post_boot` is the only place that assembles a machine, and the three
      CLI call sites use it
- [ ] `--frame N` and `--trace` and `--run` drive one loop
- [ ] The comment at the top of `ppu.py` states what is not modelled and why
- [ ] Tetris gets past `0x0237` and a dumped frame shows its tiles
- [ ] No test runs an unbounded loop
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. The mode is a pure function of `(ly, dots)`, but you still had to keep the
   previous mode in a field. What is that field actually for, and which other
   field in the project exists for the same reason?
2. You render a line at the end of mode 3, using the register values at that
   instant. Name a visual effect a game could produce that your renderer will get
   wrong, and say how you would find out whether any game you own does it.
3. `Timer.tick` returns a `bool` and `PPU.tick` returns a tuple. Defend the
   asymmetry, or change one of them — but say which and why before you look at
   the code again.
4. VRAM is blocked during mode 3 on hardware and unblocked here. Describe a ROM
   that would run correctly on your emulator and fail on a real Game Boy. Is that
   the safe direction for the difference to point?
5. The framebuffer holds shades and not colour indices, and you kept a separate
   line of indices for Step 12. What would have gone wrong if you had stored only
   the indices and applied `BGP` at the very end, in the CLI?
6. `LCDC` bit 7 stops the PPU dead. What would happen to a game that turned the
   LCD off and never on again, and what does that tell you about which component
   is really driving the emulator's main loop?
