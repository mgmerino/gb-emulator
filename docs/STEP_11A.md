# Step 11A — The PPU as a clock

## Goal

Make the PPU count time, report its position through its registers, and raise its
two interrupts. Nothing is drawn in this part. Step 11B does the pixels.

Tetris waits at `0x0233` for `LY` to reach 148. Two instructions later it writes
`0x03` to `LCDC`, which clears bit 7 and turns the LCD off. A PPU that only
counts `LY` escapes the first loop and stalls in the second, so this part needs
the mode machine, the interrupts and the LCD-off path as well as the counter.

Seven registers join the map:

| Address | Name | What it is |
| --- | --- | --- |
| `0xFF40` | `LCDC` | LCD control. Eight switches. This part uses bit 7 |
| `0xFF41` | `STAT` | LCD status. Which mode, whether `LY == LYC`, and four interrupt selects |
| `0xFF42` | `SCY` | how far down the 256×256 background the screen is looking |
| `0xFF43` | `SCX` | how far right |
| `0xFF44` | `LY` | the line being drawn, `0`–`153`. Read-only |
| `0xFF45` | `LYC` | the line a ROM wants to be told about |
| `0xFF47` | `BGP` | background palette: four indices to four shades |

`SCY`, `SCX` and `BGP` are stored and not yet used. They arrive here because a
ROM writes all seven in one burst during setup, and a register that drops writes
is harder to debug later than one that stores them early.

At the end of this part Tetris gets past `0x0237` and starts filling VRAM. The
screen is still blank.

---

## Theory

### 1. What is the PPU

The Picture Processing Unit is a second processor. It has its own clock, its own
memory (VRAM and OAM), and its own program, fixed in silicon: draw 144 lines of
160 pixels, rest, repeat.

It walks the screen at a fixed rate and fetches what it needs as it goes. The CPU
cannot write VRAM at an arbitrary moment, because the PPU may be reading it. The
screen cannot be composed at an arbitrary moment either, because a ROM is allowed
to change `SCX` between two scanlines and expect the second one to move.

The hardware draws one pixel per dot, through a pipeline: a fetcher pulls tile
bytes into an 8-pixel FIFO, a shifter pops one pixel per dot onto the LCD.
Reproducing that is how you get the hard cases right: mid-scanline `SCX` changes,
the window turning on halfway across a line, the exact length of mode 3.

This project does not do that. It builds a **scanline renderer**: the PPU tracks
its position with a dot counter, and when a line's drawing period ends it
computes all 160 of that line's pixels at once, from whatever the registers say
at that instant. Step 13 revisits the trade.

| | Dot renderer | Scanline renderer |
| --- | --- | --- |
| Register changes *between* lines | correct | correct |
| Register changes *within* a line | correct | wrong — the whole line uses the final value |
| Cost per frame | 70224 steps | 144 renders |
| Lines of code | several hundred | several dozen |

Almost no DMG game changes `SCX` mid-line. The ones that do are doing it
deliberately, to warp a status bar or shear an image. A scanline renderer draws
every commercial game correctly enough to play.

### 2. The dot clock

The PPU is clocked by the same 4.194304 MHz crystal as everything else. Its unit
of time is a **dot**, and one dot is one T-cycle: the same T-cycles the opcode
table has reported since Step 04, and the same ones `bus.tick` already hands to
the timer.

```
1 scanline  = 456 dots
1 frame     = 154 scanlines  =  70224 dots
              ├── 144 visible lines  (LY 0–143)
              └──  10 blank lines    (LY 144–153)
```

The screen is 144 lines tall and the PPU counts to 154. The ten extra lines are
VBlank: no pixels are produced, VRAM is free, and the CPU has 4560 dots, roughly
1140 machine cycles, to do everything that touches video memory.

70224 is the number the trace summary has been printed against since Step 04.

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
                                              Step 11B renders the whole line
                                              here, in one go

 LY 144 ─────────────────────────────────────────────────────── LY 153
 │ mode 1 · VBlank · 10 lines · 4560 dots                             │
```

| Mode | Name | Length | What the hardware is doing | VRAM | OAM |
| --- | --- | --- | --- | --- | --- |
| 2 | OAM scan | 80 dots | picking which sprites are on this line | free | blocked |
| 3 | Drawing | 172–289 dots | pushing pixels to the LCD | blocked | blocked |
| 0 | HBlank | the rest of 456 | nothing. Idling to the end of the line | free | free |
| 1 | VBlank | 4560 dots | nothing, for ten lines | free | free |

Mode 3 is variable on hardware: it stretches when `SCX` is not a multiple of 8,
and when sprites are on the line. Mode 0 shrinks by exactly as much, so the line
is always 456. This project fixes mode 3 at its 172-dot minimum, which makes mode
0 always 204. It is an approximation the scanline renderer was already committed
to.

The "blocked" columns describe hardware that refuses the CPU: a read of VRAM
during mode 3 returns `0xFF` and a write is dropped. This project does not model
that either. Section 7 says why.

### 4. `LY`, `LYC`, and `STAT`

`LY` is the line the PPU is on, and it is the only clock a program has that is
synchronised to the display. A ROM that wants to act at a particular point in the
frame polls `LY` until it matches. That is what Tetris does at `0x0233`.

`LY` is **read-only**. Writing it does nothing at all. A bus that lets `LY` be
written will let a stray `LD (HL), A` desynchronise the display from the machine,
and nothing in the output will point at the cause.

`LYC` is the ROM's side of a comparison the hardware performs for it. On every
line the PPU checks `LY == LYC` and reports the answer in `STAT` bit 2. A game
uses this to get an interrupt on one specific scanline; the classic use is a
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

`STAT` is the first register in this project where read and write see different
bits. Bits 2-0 are the PPU reporting to the ROM; bits 6-3 are the ROM configuring
the PPU. A write must land on bits 6-3 and leave 2-0 alone. A read must assemble
2-0 from live state rather than from whatever was last written.

The failure here is quiet. A `STAT` that stores the whole byte on write reads
back a stale mode, and a ROM that polls `STAT` for mode 0 instead of polling `LY`
hangs, with no error, on a register that looks right in a dump.

The consequence for the class: bits 2-0 do not belong in the `stat` field. Store
the selects, derive the rest.

### 5. Two interrupts, and a rising edge on an OR

The PPU raises two of the five interrupts.

**`VBlank`, `IF` bit 0.** Fires once per frame, when `LY` becomes 144.
Unconditional: there is no enable bit in `STAT` for it, only the usual `IE`. This
is the heartbeat every game is built on, sixty times a second telling it the
screen is free for the next 4560 dots.

**`LCD_STAT`, `IF` bit 1.** Fires on four selectable conditions. The four are
OR'd into a single internal signal, the **STAT interrupt line**, and the
interrupt is requested when that line goes from low to high. Not while it is
high, only on the transition.

```
   LY == LYC ──── AND ──── STAT bit 6 ──┐
                                        │
   mode == 0 ──── AND ──── STAT bit 3 ──┤
                                        ├─── OR ───► did it rise 0 → 1 ?
   mode == 1 ──── AND ──── STAT bit 4 ──┤                    │
                                        │                    ▼
   mode == 2 ──── AND ──── STAT bit 5 ──┘             IF bit 1 · 0xFF0F
```

Compare that with the diagram at the top of `timer.py`. The timer watches one bit
through an AND and fires on the falling edge. The PPU watches four conditions
through an OR and fires on the rising edge. Different polarity, different gate,
same discipline: keep the previous sample in a field, compare, act on the change
and not on the level.

The consequence is called **STAT blocking**. If mode 0 is selected and the line
is already high because `LY == LYC` just became true, entering mode 0 raises no
interrupt, because the line was never low in between. Games rely on this. An
implementation that requests `LCD_STAT` on every condition it notices delivers
several interrupts per line instead of one, and a ROM whose handler advances a
counter runs its frame logic four times too often.

### 6. `LCDC` bit 7, and turning the LCD off

```
0xFF40 byte:  │ 7 │ 6 │ 5 │ 4 │ 3 │ 2 │ 1 │ 0 │
                │   │   │   │   │   │   │   └── BG & window enable    11B
                │   │   │   │   │   │   └────── OBJ enable            Step 12
                │   │   │   │   │   └────────── OBJ size              Step 12
                │   │   │   │   └────────────── BG tile map           11B
                │   │   │   └────────────────── tile data             11B
                │   │   └────────────────────── window enable         Step 12
                │   └────────────────────────── window tile map       Step 12
                └────────────────────────────── LCD & PPU enable      here
```

The whole byte is stored, because a ROM writes the whole byte and must read the
whole byte back. This part acts on bit 7 only. 11B adds bits 4, 3 and 0.

Bit 7 does not dim the screen. It **stops the PPU**. When it goes to 0: `LY`
resets to 0 and stays there, the mode goes to 0, the dot counter resets, no
interrupts are raised, and the screen is blank. When it goes back to 1, the PPU
restarts at the top of a fresh frame.

It is the next thing Tetris does:

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

The sequence is: turn the LCD on, wait for VBlank, turn it off. The wait exists
because switching the LCD off outside VBlank is documented as damaging on real
hardware, so every game does the polite thing first. Only then does it load
palettes and start filling VRAM, with the PPU stopped and the whole address space
to itself.

The LCD-off path is not optional. Get `LY` counting and forget bit 7, and the ROM
gets past `0x0237`, disables the LCD, and is then shown an `LY` that keeps
advancing anyway. The next wait loop it writes hangs for a reason nowhere near
your code.

### 7. What is deliberately not modelled

Write these into a comment at the top of `ppu.py`, the way `serial.py` records
what the link cable does not do.

- **VRAM and OAM blocking.** During mode 3 a real CPU read of VRAM returns
  `0xFF`. Modelling it would make the emulator stricter than hardware in the
  wrong direction: a game with a timing bug that hardware forgives would break
  here. Revisit if `dmg-acid2` disagrees.
- **The variable length of mode 3.** Fixed at 172 dots, per section 3.
- **The pixel FIFO.** Per section 1. This is the one a mid-line `SCX` change
  would need.
- **The `LY == 153` quirk.** On hardware `LY` reads 0 for all but the first 4
  dots of line 153. A handful of ROMs detect this. None of ours do.
- **Sprites and the window.** Step 12. `LCDC` bits 6, 5, 2 and 1 are stored and
  ignored on purpose.

The rule that has held since Step 03 still holds: an unimplemented read returns
something plausible, an unimplemented write is dropped, nothing raises.

### 8. The state the boot ROM left behind

The project skips the boot ROM and starts at `0x0100` with the registers the boot
ROM would have left. The PPU needs the same treatment. A game is entitled to
assume the LCD is already on, because the boot ROM turned it on to draw the
Nintendo logo.

| Register | Post-boot | Meaning |
| --- | --- | --- |
| `LCDC` | `0x91` | LCD on, tile data `0x8000`, map `0x9800`, BG on |
| `STAT` | `0x85` | mode 1, `LY == LYC`, no selects |
| `SCY` | `0x00` | |
| `SCX` | `0x00` | |
| `LY` | `0x00` | |
| `LYC` | `0x00` | |
| `BGP` | `0xFC` | `11 11 11 00` — index 0 white, everything else black |

`STAT` is the interesting row. `0x85` is what a ROM *reads*, and per section 4
bits 2-0 of that are derived, not stored. So the field holds `0x00` (no selects)
and the state that produces the rest is `mode = VBLANK` with `ly == lyc == 0`.
Storing `0x85` in the field would work today and break the moment task 2 assembles
the register.

There is a related debt to settle. Step 09 specified `Timer.post_boot()` with
`DIV == 0xAB`; the class does not have it, and `__main__.py` builds a plain
`Timer()`, so `DIV` starts at 0 in every run the CLI has ever done. Task 6
collects this into one place.

### 9. Python concepts this part introduces

- **`enum.IntFlag`.** `LCDC` is eight independent booleans in one byte, which is
  what `IntFlag` is for: named members that combine with `|` and test with `in`.
  Whether it beats eight `@property`s named after Pan Docs is a judgement call.
  Task 2 asks you to make it.
- **A tuple as a return value for "zero or more things".** `PPU.tick` returns the
  interrupts it raised. `()` is a singleton in CPython, so the common path
  allocates nothing. In Ruby you would return an array and pay for it.
- **Deriving instead of storing.** `mode` is a pure function of `(ly, dots)` and
  `STAT` bits 2-0 are a pure function of `(mode, ly, lyc)`. Two fields exist
  anyway — `mode` and `last_stat_line` — and section 4 of the questions asks you to
  say why.

---

## Tasks

### 1. `ppu.py`, the state and the geometry

A new module. Like `timer.py` it imports only `bits` and `memory_map`, and it is
tested without a bus.

The geometry constants first, because every later task indexes with them: screen
width and height, dots per line, lines per frame, and the lengths of modes 2 and
3. Name them; do not spell `456` in three places. The VRAM constants belong to
11B, which is where they get used.

Screen height and lines per frame are two different numbers, 144 and 154. A
single constant covering both is the first bug this file can have.

The state is roughly:

```python
@dataclass(slots=True)
class PPU:
    vram: bytearray = field(default_factory=lambda: bytearray(VRAM_SIZE))
    framebuffer: bytearray = field(
        default_factory=lambda: bytearray(SCREEN_WIDTH * SCREEN_HEIGHT)
    )
    dots: int = 0  # position within the current scanline, 0–455
    ly: int = 0
    lyc: int = 0
    lcdc: int = 0
    stat: int = 0  # only bits 6-3 live here; 2-0 are computed
    scy: int = 0
    scx: int = 0
    bgp: int = 0
    mode: Mode = Mode.OAM_SCAN
    last_stat_line: bool = False  # the OR gate's previous sample
    frames: int = 0  # completed frames, for the CLI to count
```

`field(default_factory=...)` rather than a plain default: a dataclass evaluates a
plain default once, at class-creation time, and every instance would share the
same `bytearray`.

`Mode` is an `IntEnum` with the hardware's own numbering — `HBLANK = 0`,
`VBLANK = 1`, `OAM_SCAN = 2`, `DRAWING = 3` — so that assembling `STAT` bits 1-0
is a cast and not a lookup table. Name the dot constants after the phase
(`OAM_SCAN_DOTS`), not the number, or you will write `MODE_1 = 80` and contradict
the enum three lines below.

Add `post_boot()` per section 8, and write the "not modelled" comment from
section 7 now, at the top of the file.

**Acceptance:** `PPU.post_boot().lcdc == 0x91` and its `mode is Mode.VBLANK`, and
`456`, `154` and `160` each appear exactly once in the module's code.

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

Per section 4: `STAT` read assembles, `STAT` write masks. Neither touches the
other's bits.

Put the addresses in `memory_map.py` with the rest of the map, and decide there
what range the bus will match on. `0xFF46` and `0xFF48`–`0xFF4B` belong to Step
12. Letting them fall through to the bus's existing `io` array gives correct
read-back for free; claiming them now means writing storage for registers nothing
reads. Prefer the first.

The `IntFlag`-or-properties decision gets made here, because this is the first
code that has to ask "is bit 7 set". Write it the way that will still read well
when 11B asks the same question about bits 4, 3 and 0, and say in a comment why.

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

Step 09's question 3 asked what shape a device with two interrupts should return.
The answer proposed here is a tuple, empty on the common path. `Timer.tick` keeps
its `bool`: one source, one answer, and changing it would be churn without a
reader. If you disagree, settle it now rather than in Step 12.

The machine, per section 3:

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

Deriving the mode from the position is simpler than tracking a state machine with
transitions, and it is correct because the mode is a pure function of
`(ly, dots)`. Task 4 and 11B still need to know when a transition happened, so
compare the newly derived mode against the stored one. That gives the edge with
no duplicate state.

Write `while` rather than `if`. The longest instruction is 24 T-cycles and a line
is 456, so it can only run once today, but Step 15's `HALT` in a bank-switching
loop is not where you want to discover the difference.

**Acceptance:** a `PPU` ticked 70224 dots in steps of 4 is back at `ly == 0`,
`dots == 0`. Ticked 456, `ly == 1`. Ticked 456 × 144, `mode is Mode.VBLANK`.

---

### 4. The two interrupts

Per section 5.

**VBlank** on the transition into `LY == 144`. Once per frame. Detect it from the
mode change, not from `ly == 144`, or a tick that lands twice inside line 144
raises it twice.

**STAT** on the rising edge of the OR. One helper that computes the line's
current level from `(mode, ly, lyc, stat)`, and one comparison against
`last_stat_line`, named after its sibling `Timer.last_and`. The shape is
`Timer._advance_tima` with the polarity flipped. If
your version does not look like a sibling of it, one of the two is doing more
than it needs to.

Increment `frames` when VBlank is entered. 11B's CLI needs a way to say "run
until frame 3", and the VBlank transition is the definition of a completed frame.

**Acceptance:** a `PPU` ticked across one whole frame returns `Interrupt.VBLANK`
exactly once. With `STAT` bit 3 set (mode 0 select) and bit 6 clear, it returns
`Interrupt.LCD_STAT` exactly 144 times, once per visible line rather than once
per tick spent in mode 0. With bits 3 and 6 both set and `LYC == 0`, line 0
produces **one** `LCD_STAT`. That assertion is STAT blocking, and it fails if you
fire on level instead of edge.

---

### 5. Turning the LCD off

Per section 6. When `LCDC` bit 7 goes from set to clear: `ly = 0`, `dots = 0`,
mode to `HBLANK`, `last_stat_line` to `False`, and fill the framebuffer with
shade 0.

While bit 7 is clear, `tick` returns immediately: no counting, no interrupts.

When it goes from clear to set, the PPU is already at the top of a frame from the
reset above, so there is nothing extra to do. Check that rather than taking it on
trust: it is only true because the disable path reset the counters instead of
freezing them.

**Acceptance:** with the LCD off, ticking 70224 dots leaves `ly == 0` and `frames`
unchanged. Writing `0x91` then `0x11` to `0xFF40` puts `LY` back to 0 from
wherever it was.

---

### 6. The bus: routing, fan-out, and one place that assembles a machine

Three changes, and a debt. VRAM stays on the bus for now; 11B moves it.

**The LCD registers route to the PPU**, per task 2.

**`bus.tick` fans out to both devices.** The PPU returns a tuple; loop over it and
`request` each.

**`Bus.post_boot(cartridge)`.** `Timer.post_boot()` does not exist, and
`__main__.py` constructs `Bus(cartridge, Timer())` in three places. Adding a
third constructor argument would make that four things to get right per call
site. A classmethod that assembles a post-boot timer and a post-boot PPU replaces
all three call sites with one, and gives a home to a fact currently split between
`Registers.post_boot` and nowhere.

Keep the injecting constructor for tests that want a `Timer` in a chosen state.

**Acceptance:** `Bus.post_boot` produces a bus whose `DIV` reads `0xAB` and whose
`LCDC` reads `0x91`. `--trace 3` on Tetris still prints what it printed before
this step.

---

### 7. Tests

**Unit level, `PPU` alone, no bus:**

- the mode machine: a table of `(ly, dots, expected_mode)` covering all four,
  including the boundaries at dots 79/80 and 251/252
- a full frame is 70224 dots and returns to `ly == 0`
- `LY` is read-only through `read`/`write`
- `STAT` read assembles live bits; `STAT` write lands only on bits 6-3
- VBlank fires once per frame
- the STAT rising edge, and STAT blocking, per the assertion in task 4
- LCD disable resets `LY` and stops the clock

**Bus level:**

- the seven registers route both ways
- `bus.tick` across a frame sets `IF` bit 0
- `Bus.post_boot` gives `DIV == 0xAB` and `LCDC == 0x91`

**Program level.** A program that does what Tetris does:

```
; at 0x0100:  LD A, 0x80  ; LDH (0xFF40), A   ; LCD on
;             LDH A, (0xFF44) ; CP 0x94 ; JR NZ, -6   ; wait for line 148
;             INC B                                    ; got out
;             LD A, 0x03  ; LDH (0xFF40), A   ; LCD off
```

Step it in a bounded loop and assert that `B` incremented. That is the loop the
emulator has never escaped.

That program only *reads* `LY`, so it says nothing about whether the register is
writable. Write a second one with an `LDH (0xFF44), A` inside the loop: with `LY`
read-only the write is dropped and the loop still ends, and if the bus let it
through, `LY` would be pushed back to 0 on every pass and 148 would never arrive.
One test, one reason to fail.

**Acceptance:** the first test fails if you drop the `ppu.tick` call from
`bus.tick`, and the second fails if you make `LY` writable. Break each one and
watch the right test go red — a PPU test that passes with the PPU unplugged is
testing your fixture.

---

### 8. Run the real thing

Tetris has been stuck at `0x0233` since Step 08.

```
uv run python -m gameboy ~/games/TETRIS.gb --trace 200 | tail -40
```

Does it get past `0x0237`? Does it write `0x03` to `0xFF40` two instructions
later, as section 6 predicts? Report where it goes after that. The answer should
be a long run of VRAM writes, which is a game loading its font. Step 11B turns
those writes into a picture.

---

### 9. Docs

`README.md`: the step table, and the closing section. `PLAN.md`: Step 11A's row.
Say that the renderer is a scanline renderer and what that gives up, per section
1. The next person to read this will want to know whether it was an oversight or
a decision.

---

## Hints

- If `LCD_STAT` fires hundreds of times a frame, you are testing the level and
  not the edge. `timer.py` already contains the shape you want.
- If VBlank fires twice per frame, you are detecting `ly == 144` rather than the
  transition into it.
- If Tetris escapes the wait loop and then hangs somewhere new, that is progress
  and the trace will name the address. Check first whether `LCDC` bit 7 is clear
  and your `tick` is counting anyway.
- If `STAT` reads back the value you wrote, you stored bits 2-0 instead of
  deriving them.
- Cross-check every number here against
  <https://gbdev.io/pandocs/Rendering.html> and its neighbours before writing it
  down.

---

## Acceptance criteria

- [ ] `LY` counts 0–153, resets, and is read-only through the bus
- [ ] The mode is derived from `(ly, dots)`, and the mode lengths are named
      constants
- [ ] `STAT` reads live bits 2-0 and writes only bits 6-3
- [ ] `VBlank` sets `IF` bit 0 once per frame
- [ ] `LCD_STAT` fires on the rising edge of the OR, and STAT blocking is
      asserted by a test
- [ ] Clearing `LCDC` bit 7 stops the PPU and resets `LY` to 0
- [ ] `PPU` imports nothing from the package but `bits`, `memory_map` and
      `interrupts`, and is tested without a bus
- [ ] `PPU.post_boot()` matches the table in section 8, and `Timer.post_boot()`
      finally exists
- [ ] `Bus.post_boot` is the only place that assembles a machine, and the three
      CLI call sites use it
- [ ] The comment at the top of `ppu.py` states what is not modelled and why
- [ ] Tetris gets past `0x0237`
- [ ] No test runs an unbounded loop
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. The mode is a pure function of `(ly, dots)`, but you still keep the previous
   mode in a field. What is that field actually for, and which other field in the
   project exists for the same reason?
2. `Timer.tick` returns a `bool` and `PPU.tick` returns a tuple. Defend the
   asymmetry, or change one of them. Say which and why before you look at the
   code again.
3. `LCDC` bit 7 stops the PPU dead. What would happen to a game that turned the
   LCD off and never on again, and what does that tell you about which component
   is really driving the emulator's main loop?
