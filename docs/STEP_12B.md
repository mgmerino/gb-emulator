# Step 12B — The window

## Goal

Add the third layer and close the frame. The background is Step 11B, objects are
Step 12A, and the window goes between them: over the background, under the
objects.

Two registers join the map:

| Address | Name | What it is |
| --- | --- | --- |
| `0xFF4A` | `WY` | the screen line the window's top row lands on |
| `0xFF4B` | `WX` | the screen column of its left edge, plus 7 |

And two `LCDC` bits: bit 5 turns the window on, bit 6 picks which tile map it
reads.

After this the PPU draws everything a DMG draws. What is left in `LCDC` is
nothing.

---

## Theory

### 1. Where the window sits

```
   objects        Step 12A     stamps with holes, ten per line, priority by X
      ▲
      │  over
      │
   window         here         opaque, no scrolling, its own line counter
      ▲
      │  over
      │
   background     Step 11B     256x256 torus, scrolled by SCX/SCY
```

Each layer covers the one below it. The window is opaque: where it is drawn, the
background is gone. There is no transparent colour index in it, unlike an
object.

Objects sit above both, and they cannot tell the two apart. `LCDC` bit 0 on a
DMG blanks the background **and** the window together, which is the first hint
that the hardware treats them as one thing wearing two hats.

### 2. What the window actually is

A second view onto a tile map. That is the whole of it.

It reads tiles the same way the background does, through `LCDC` bit 4, and it
colours them with the same `BGP`. What it does not have is scrolling.

```
   background                        window

   a 256x256 torus                   a corner of a tile map
   positioned by SCX / SCY           positioned by WY / WX
   wraps on both axes                does not wrap, has edges
   the screen is a hole              the window is a rectangle
   you look through                  laid on top

   its pixel at screen x, y is       its pixel at screen x, y is
   map[(y + SCY) % 256]              map[y - the window's own counter]
      [(x + SCX) % 256]                 [x - (WX - 7)]
```

The window always starts from the **top-left corner of its map**. There is no
`WINX`/`WINY` pair that scrolls it. `WY` and `WX` say where on the *screen* its
corner lands, not which part of the map to show.

That is why the window is the natural way to draw a status bar. A bar pinned to
the bottom of the screen while the level scrolls underneath is exactly "a second
tile map that ignores `SCX` and `SCY`".

Which of the two maps it uses is `LCDC` bit 6, independent of the background's
bit 3. Both layers can share one map or take one each.

### 3. `WY`, `WX`, and the seven

```
                        WX = 7
                        │
   0 ┌────────────────────────────────────────┐
     │                                        │
     │        the background                  │
WY ──┼───────┌────────────────────────────────┤
     │       │                                │
     │       │        the window              │
     │       │                                │
 143 └───────┴────────────────────────────────┘
     0                                      159
```

`WY` is a plain screen line. `WY = 0` puts the window's first row on screen line
0, `WY = 100` on line 100, and `WY > 143` keeps it off the screen entirely.

`WX` carries an offset of 7, so the left edge is at screen column `WX - 7`:

```
    WX =   7   ->  column 0, the whole width
    WX =  87   ->  column 80, the right half
    WX = 166   ->  column 159, one column of pixels
    WX >= 167  ->  off the right edge, nothing shows
```

The 7 is not the 8 the objects use, and it is not a mistake in the docs. It
comes from the fetcher's pipeline, which is three steps ahead of the pixel being
pushed out. `WX < 7` puts the window's edge off the left of the screen, and on
real hardware the result is a documented mess of edge cases rather than a clean
clip. Section 7 says what to do about that.

The window is drawn on line `LY` when `LY >= WY`. It has no bottom edge: once it
starts, it runs to the bottom of the screen.

### 4. The internal line counter

This is the part of the step to get right, and the only part that is not
arithmetic.

The obvious implementation is `window_row = LY - WY`. It is wrong, and it is
wrong in a way that looks correct in every simple test.

The hardware keeps a counter of its own. It starts each frame at 0, and it
**increments only on the lines where the window was actually drawn**. Not once
per `LY`, and not derived from `WY`.

The two agree as long as nothing changes mid-frame, which is why the bug hides.
They diverge the moment a game switches the window off partway down and back on:

```
   LY   window on?     internal counter      LY - WY   (WY = 40)
   ...
   40   yes            0                     0
   41   yes            1                     1
   42   no             -                     2
   43   no             -                     3
   44   yes            2                     4
   45   yes            3                     5
```

From line 44 the two disagree, and they never agree again for the rest of the
frame. The hardware carries on from where it stopped; `LY - WY` has kept
counting through the gap and skips two rows of the window's map.

Games rely on this. Turning the window off for a band of scanlines and back on
is how a DMG draws a split screen or an effect that looks like a hole punched in
a status bar, and the counter is what makes the two halves line up.

The counter resets at the start of each frame, not at `WY`. `WY` decides when
drawing starts; the counter decides which row is drawn.

### 5. `LCDC` bits 6, 5 and 0

```
0xFF40 byte:  │ 7 │ 6 │ 5 │ 4 │ 3 │ 2 │ 1 │ 0 │
                │   │   │   │   │   │   │   └── BG & window enable    both layers
                │   │   │   │   │   │   └────── OBJ enable            12A
                │   │   │   │   │   └────────── OBJ size              12A
                │   │   │   │   └────────────── BG tile map           11B
                │   │   │   └────────────────── tile data             11B, shared
                │   │   └────────────────────── window enable         here
                │   └────────────────────────── window tile map       here
                └────────────────────────────── LCD & PPU enable      11A
```

Bit 0 is the one that catches people. On a DMG it is named "BG and window
enable", and clearing it blanks both. So the window needs bit 0 **and** bit 5;
bit 5 alone draws nothing.

Bit 4 is shared: the window reads tile data exactly the way the background does,
signed or unsigned according to that one bit. Objects are the layer that ignores
it, and that is already handled by `object_tile_row`.

### 6. What the object pass needs from this

Step 12A's `line_claimed` and the behind-the-background flag both read
`line_indices`. Nothing in that logic needs to change, on one condition: where
the window is drawn, `line_indices` must carry the **window's** colour index,
not the background's underneath.

Get that wrong and an object with flag bit 7 set will decide it is hidden by a
background pixel the player cannot see, or show through a window pixel that
should cover it.

So the window pass writes both buffers, exactly as the background pass does.
That is the whole of the composition work, and it is the reason `_render_scanline`
already runs its passes in an order that has room for a third.

### 7. What is deliberately not modelled

- **`WX < 7`.** On hardware these are a nest of special cases, `WX = 0` behaving
  differently from `WX = 1..6`, and no game depends on them. Treat the left edge
  as `WX - 7` and clip anything negative. Say so in the "not modelled" list at
  the top of `ppu.py`, next to Step 12A's entries.
- **Mid-line changes to `WX`.** The scanline renderer draws a whole line from
  the registers as they stand at the end of mode 3, the same trade Step 11A made
  for `SCX`.
- **The `WY == LY` latch.** The hardware compares `WY` against `LY` on every
  line of the frame, including lines where the window is off, and remembers it.
  Comparing `LY >= WY` per line is what this project does and it agrees with the
  latch on everything except a `WY` written mid-frame to a line already passed.

### 8. Python concepts this part introduces

- **State that spans calls but not frames.** The window counter is the first
  field on the PPU that is neither a register nor a buffer: it is scratch state
  with a lifetime of one frame. Where it gets reset is a design decision, and
  the answer is a place that already exists.
- **`max()` as a clip.** The window's left edge can be negative and the loop
  must not start there. `max(0, wx - 7)` is the idiom, and it reads better than
  an `if` that adjusts a variable after the fact.
- **A second writer to the same buffers.** Two methods now write `framebuffer`
  and `line_indices` for the same line. Whether the second one overwrites or the
  first one is told to stop early is a real choice; make it deliberately and say
  which in a comment.

---

## Tasks

### 1. `WY`, `WX`, and the two `LCDC` bits

Add `WY` and `WX` to `memory_map.py` and widen `PPU_REGISTERS_2` to cover
`0xFF47`-`0xFF4B`. That range has grown once per step; this is the last time,
because `0xFF4B` is the last DMG video register.

Store them on the PPU and wire them into `read` and `write` next to `BGP` and the
two object palettes. Name the two `LCDC` bits with the rest, following the
convention Step 12A settled: `_OBJ_*` for object bits, so `_WINDOW_*` here.

**Acceptance:** `0xFF4A` and `0xFF4B` round-trip through the bus and land on the
PPU's own fields, the way `test_obp_round_trips` asserts for the palettes.

---

### 2. The window's line counter

One integer field, reset once per frame.

Per section 4, it is not derived from `LY` or `WY`. Find the place in `tick` that
already knows a frame has ended, and reset it there. There is exactly one such
place and it is the same edge that increments `frames`.

`_switch_off` resets the other counters and must reset this one too, or a ROM
that turns the LCD off mid-frame leaves the window one frame out of step.

**Acceptance:** a PPU ticked two whole frames with the window on has a counter
that ends both frames at the same value, rather than one that has counted 288.

---

### 3. The window pass

A third pass in `_render_scanline`, between the background and the objects.

It draws when bit 0 and bit 5 are both set, when `LY >= WY`, and when the left
edge is on the screen. It fills from that edge to column 159, so it needs no
right-hand clip, only a left one.

For each column it draws, the map cell and the row inside the tile come from the
window's own counter and from `x - (WX - 7)`, with no `% 256` anywhere: the
window does not wrap.

Increment the counter once per line drawn, after the loop, not once per call.

Per section 6, write `line_indices` as well as `framebuffer`.

**Acceptance:** a PPU whose background is one tile and whose window is another,
with `WY = 8` and `WX = 7`, has the background's pattern on lines 0-7 and the
window's from line 8 down. Move `WX` to 87 and the left half of those lines is
background again.

---

### 4. The objects still land on top

No new code, per section 6. What this task is, is the test that proves it.

**Acceptance:** an object at flag bit 7 over a window pixel of colour index 0
shows, and over a window pixel of index 1-3 does not. Both assertions fail if the
window pass forgot `line_indices`, and neither fails if it wrote only the
framebuffer, which is why this one is worth writing before you believe task 3.

---

### 5. Tests

- both registers round-trip
- the window covers the background from `WY` down, and not above it
- `WX = 7` starts at column 0; `WX = 87` starts at column 80; `WX >= 167` draws
  nothing
- `LCDC` bit 5 clear draws no window; **bit 0 clear draws no window either**,
  even with bit 5 set
- `LCDC` bit 6 picks the second map
- `SCX` and `SCY` move the background and leave the window where it is
- the counter: a frame where the window is switched off for a band of lines and
  back on continues from where it stopped, rather than skipping the band
- the counter is back to its starting value at the top of the next frame
- objects over the window, both ways, per task 4

The counter test is the one that matters and the one a passing screenshot will
not give you. Build it by driving the PPU line by line and writing `LCDC` between
lines, the way `run_dots` already lets you.

---

### 6. Running something that uses it

The acceptance for this step is
[dmg-acid2](https://github.com/mattcurrie/dmg-acid2), which exists for exactly
this: it draws a face out of background, window and objects, and every feature it
tests is one of Step 12A's or this step's.

Do not expect a game to serve instead. The window is what a status bar is made
of, so the games that use it are the ones large enough to need banking, and
those stall long before they draw anything until Step 15. Check dmg-acid2's own
header first, for the same reason:

```
uv run python -m gameboy path/to/dmg-acid2.gb
uv run python -m gameboy path/to/dmg-acid2.gb --frame 10 --out acid2.pgm
```

Compare against the reference image in its repository. It fails in specific,
named ways rather than looking vaguely wrong, and its README maps each broken
feature to what causes it. Expect it to re-test Step 12A as much as this step:
object priority, 8x16, and both flips are all in that face.

---

### 7. Docs

`README.md`: the step table gets a 12B row, and "What is missing" loses the
window. `PLAN.md`: Step 12B's row. The "not modelled" comment at the top of
`ppu.py` gains `WX < 7` and the `WY == LY` latch.

With this the DMG's video hardware is done, so the closing section of the README
is worth rewriting rather than editing: what is left is the joypad, MBCs and
sound.

---

## Hints

- If the window never appears, check `LCDC` bit 0 before bit 5. Bit 5 alone
  draws nothing and the symptom is identical to the window being off.
- If the window is one column too far left or right, you have the 7 confused with
  the objects' 8.
- If the window appears at the right row but shows the wrong part of its map, you
  are using `LY - WY` instead of the counter, or you are incrementing the counter
  on every line rather than on drawn ones.
- If the window scrolls with the background, you left a `+ SCX` or a `% 256` in
  the copied code. The window has neither.
- If objects with flag bit 7 vanish over the window, the window pass wrote
  `framebuffer` and forgot `line_indices`.
- If the top line of the window is right and every line below repeats it, the
  counter is not being incremented at all.
- Cross-check against <https://gbdev.io/pandocs/Scrolling.html>, which is where
  the 7 and the internal counter are both documented.

---

## Acceptance criteria

- [ ] `WY` and `WX` are stored on the PPU and `PPU_REGISTERS_2` reaches `0xFF4B`
- [ ] The window has its own line counter, reset once per frame and by
      `_switch_off`, and it is not derived from `LY` or `WY`
- [ ] A test drives the window off and back on mid-frame and asserts the counter
      continued rather than skipped
- [ ] `LCDC` bit 0 clear draws no window, asserted with bit 5 set
- [ ] `LCDC` bit 6 selects the second map, asserted by a test
- [ ] `SCX`/`SCY` do not move the window, asserted by a test
- [ ] Objects still resolve against the window, both sides of flag bit 7
- [ ] `WX < 7` and the `WY == LY` latch are named in `ppu.py`'s "not modelled"
      list
- [ ] dmg-acid2 renders, and every difference from the reference image is
      identified by name
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. The window has no bottom edge and no right edge: it always runs to the corner
   of the screen. Given that, how would a game draw a status bar across the *top*
   eight lines only, and what does your answer say about why the internal counter
   exists?
2. You reset the counter once per frame. Name the ROM behaviour that would tell
   the difference between resetting it at VBlank and resetting it when `LY`
   returns to 0.
3. The background wraps and the window does not. Both read the same tile maps
   through the same tile data. Where in your code does that difference actually
   live, and is it one line or several?
4. Objects compare against `line_indices`, which now holds background or window
   depending on the column. Is there any DMG behaviour that needs to know which
   of the two a given index came from?
