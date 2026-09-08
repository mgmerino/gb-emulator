# Step 13A — The screen

## Goal

Put the framebuffer in a window and turn the loop around, so the emulator runs
frames instead of instructions.

At the end Tetris moves on screen. It moves slowly: the measurement in section 4
says 9 frames per second against the 59.7 a DMG produces. This part does not fix
that. It makes it visible and gives it a number, which is what Step 13B needs in
order to have something to improve.

---

## Theory

### 1. From a byte to a pixel

The chain has four links and three of them already exist.

```
   two bitplanes in VRAM                        Step 11B
        │
        ▼   decode_row_index
   colour index, 0-3                            11B, 12A, 12B
        │
        ▼   BGP, OBP0, OBP1
   shade, 0-3                                   the framebuffer, 23040 bytes
        │
        ▼   a four-entry table in the frontend
   a colour in a window                         here
```

Each arrow is a lookup in a four-entry table, and each table belongs to a
different owner. The palette registers belong to the ROM. The last table belongs
to whoever is displaying, which is why `__main__.py` can spell it `" .+#"` and
`experiments/frame_to_png.py` can spell it as four greys, from the same bytes.

This part adds a third spelling, and it is the first one that is a colour.

### 2. The framebuffer is already an image

An 8-bit paletted image is a byte per pixel, each byte an index into a colour
table. The framebuffer is a byte per pixel, each byte a shade 0-3. They are the
same layout.

So the conversion is not a loop:

```
   ppu.frame                    23040 bytes, a read-only memoryview
        │
        │   pygame.image.frombuffer(frame, (160, 144), "P")
        ▼
   Surface, 8 bits per pixel        no copy, no Python running per pixel
        │
        │   surface.set_palette(GREENS)
        ▼
   Surface wearing the four greens
        │
        │   scale, blit, flip
        ▼
   the window
```

`frombuffer` takes the buffer as it stands, and it accepts the read-only
`memoryview` that `ppu.frame` has returned since Step 11B. That decision looked
like a nicety at the time. It turns out to be exactly the shape a C library
wants, and the read-only guarantee survives all the way to SDL.

Only `scale` touches every pixel, and it happens in C.

### 3. Where the boundary is

`PLAN.md` constraint 1:

> The core is framework-independent. No pygame, no SDL, no I/O library inside
> `gameboy/`. The core exposes a framebuffer and accepts button state.

So the window lives in a sibling package, and depends on whatever it likes.
`gameboy/` stays importable with nothing installed, which is what keeps the
emulator testable headlessly and the display swappable.

```
   src/gameboy/          the emulator. imports: nothing outside the stdlib
   src/screen/           the window. imports: pygame
```

The seam between them is a framebuffer going one way. In Step 14 button state
starts coming back the other way, and the same boundary carries it.

### 4. The numbers, and the one this part reports

A DMG produces frames at:

```
   4194304 dots per second / 70224 dots per frame = 59.7275 frames per second
```

Measured on this emulator, in the middle of Tetris's title screen:

```
   82k instructions per second  ->  9.0 frames per second  =  15% of real time
```

So a frame takes about 110 ms where the hardware takes 16.7 ms.

That is worth stating plainly rather than discovering later. Frame pacing, which
`PLAN.md` promises for Step 13, means *holding back* to 59.7. There is nothing to
hold back yet, which is why it is in 13B behind the optimisation and not here.

What this part builds is the instrument: a frames-per-second number on screen or
on the console, measured over a rolling window rather than from a single frame.
13B's job is to move that number, and an optimisation without a before and after
is a guess.

### 5. Four greens

```
   shade 0    0x9BBC0F      the lightest
   shade 1    0x8BAC0F
   shade 2    0x306230
   shade 3    0x0F380F      the darkest
```

These are the DMG's own greens, near enough. The panel was a reflective STN LCD
with a green backing, so "white" was the colour of the backing showing through.

Nothing in `gameboy/` knows they exist, and nothing should. They are the
frontend's four-entry table from section 1, the same kind of object as
`__main__.py`'s `" .+#"`.

### 6. The dependency

```toml
[project.optional-dependencies]
gui = ["pygame-ce>=2.5"]
```

An extra rather than a plain dependency, so the test suite still runs on a
checkout with nothing installed. Running the window becomes:

```
uv run --extra gui python -m screen path/to/rom.gb
```

**`pygame-ce` rather than `pygame`.** It is the maintained fork, and the import
name is still `pygame`, so no line of your code says "ce". Version 2.5.8 here,
carrying SDL 2.32.

### 7. Python concepts this part introduces

- **A `Protocol` for the second time.** `MemoryDevice` in Step 03 let the bus
  accept a fake cartridge without inheritance. The display is the same shape:
  the loop should not import pygame to be tested, so it depends on a Protocol
  and the tests pass something that records what it was given. Ruby gets this
  for free and calls it duck typing; the Protocol is how you keep it and still
  have `mypy --strict` check the call.
- **The buffer protocol.** Handing a `memoryview` to a C extension passes a
  pointer and a length, not a copy. Ruby has no equivalent: a `String` handed to
  a C extension is the object itself, and there is no way to expose a read-only
  window onto part of one.
- **Optional dependency groups.** `[project.optional-dependencies]` is a named
  set of extras, installed on request. The nearest Ruby idea is a `Gemfile`
  group, though bundler installs groups by default and uv does not.
- **A package that is not the library.** `src/screen/` sits beside
  `src/gameboy/` and depends on it, never the other way round. Import direction
  is the architecture: if `gameboy` ever imports `screen`, constraint 1 is gone
  and no test will notice.

---

## Tasks

### 1. The extra, and a package to put it in

Add the `gui` extra from section 6 and create `src/screen/` beside
`src/gameboy/`, with its own `__init__.py` and `py.typed`.

Check the direction of the arrow while you are there: `screen` imports
`gameboy`, and `gameboy` imports nothing of `screen`.

**Acceptance:** `uv run pytest` and `uv run mypy` pass with the extra not
installed, and `uv run --extra gui python -c "import pygame"` works.

---

### 2. The display, and the seam behind it

Two pieces. A Protocol the loop talks to:

```python
class Display(Protocol):
    def present(self, frame: memoryview) -> None: ...
    def wants_to_close(self) -> bool: ...
```

And a pygame implementation of it, per section 2: a paletted `Surface` built
once, `frombuffer` per frame, the palette set once, then scale, blit and flip.

`wants_to_close` is what makes the window closeable. SDL delivers a QUIT event
when the title bar's X is clicked, and a loop that never reads the event queue
gets a window the desktop reports as hung.

Two ways to scale, and they are not equivalent in 13B:
`pygame.transform.scale` every frame, or `set_mode(..., pygame.SCALED)` with a
160x144 logical surface and SDL doing the scaling once, possibly on the GPU.
Pick one, and say in a comment which and why.

**Acceptance:** with `SDL_VIDEODRIVER=dummy` in the environment the pygame
display constructs, presents a frame and reports no close, with no window and no
display server. That is what makes it testable in CI and on this machine over
SSH.

---

### 3. `run_frame`, and the guard it needs

The loop turns around. `run` is a generator of instructions with a budget in
instructions, driven by the CLI. What a display wants is:

```
    while not display.wants_to_close():
        run_frame(bus)
        display.present(bus.ppu.frame)
```

So: step the CPU until `bus.ppu.frames` increments, then return.

**It needs a cap, and this is the part to think about.** `frames` only advances
on the VBlank edge, and the PPU does not tick at all while `LCDC` bit 7 is clear.
A ROM turns the LCD off during setup, and Tetris turns it off again at `0x0237`.
A `run_frame` that waits for a frame that is not coming hangs the window with no
diagnostic.

Give it a budget and a way to report that it gave up. Decide what the caller
does with that: freezing on the last good frame and saying so is a defensible
answer, and so is stopping. Pick one and write down why.

**Acceptance:** on a bus whose LCD is off, `run_frame` returns within its budget
instead of looping. On a running Tetris it returns after exactly one VBlank, and
`bus.ppu.frames` has advanced by exactly 1.

---

### 4. The entry point, and the instrument

`python -m screen path/to/rom.gb`, with `--scale` and whatever else you want.

The frames-per-second number, per section 4. Measure it over a rolling window of
a second or so, not from one frame: a single frame's time swings with whatever
the ROM is doing on that line. Put it in the window title, which costs nothing
and needs no font.

Print it once on exit too. 13B will want to paste a before and after somewhere.

**Acceptance:** a window opens on Tetris, the title screen animates, the title
bar shows a frame rate, and closing the window ends the process cleanly.

---

### 5. Tests

The emulator's tests do not change and must not start needing the extra.

- `run_frame` advances `ppu.frames` by exactly 1
- `run_frame` gives up within budget when the LCD is off
- the loop presents one frame per `run_frame`, asserted against a fake `Display`
  that counts calls and keeps the last frame it was handed
- the fake's last frame is 23040 bytes, so the seam carries what it claims

Those four need no pygame. Mark anything that does with a skip when the import
fails, so the suite stays green on a checkout without the extra.

**Acceptance:** `uv run pytest` green with the extra absent, and green with it
present.

---

### 6. Run the real thing

```
uv run --extra gui python -m screen path/to/TETRIS.gb --scale 3
```

Expect the copyright screen, then the title screen, at a speed that is visibly
wrong. That is the point of the number in the title bar.

`dmg-acid2` is the other one worth opening, because you already know exactly
what it should look like.

---

### 7. Docs

`README.md`: a 13A row, the new command, and a screenshot next to the dmg-acid2
one.

And a correction. The README currently says:

> Roughly 290k instructions/second on CPython 3.12, about 80% of a real DMG.

Both halves are now wrong. It measures 82k instructions per second and 15% of
real time, because that sentence was written before the PPU drew anything.
Replace it with the frames-per-second number, which is the one a reader can
check by opening the window.

`PLAN.md`: split Step 13's row into 13A and 13B the way 11 and 12 were split.

---

## Hints

- If the window is grey and never updates, you are presenting before running the
  frame, or presenting a `Surface` you built once from a buffer that has since
  been replaced rather than written into.
- If the colours are wrong but the shapes are right, the palette is set on a
  different `Surface` than the one being blitted, or set before `frombuffer`
  replaced it.
- If the window is unresponsive and the desktop offers to kill it, nothing is
  reading the SDL event queue. Pump it once per frame even if you ignore every
  event.
- If it hangs on a black screen with no error, `run_frame` is waiting for a
  VBlank from a PPU whose LCD is off. That is task 3's guard, and it is the most
  likely thing to catch you.
- If the frame rate reads far higher than the emulator can possibly be running,
  you are timing the presentation and not the emulation.
- `SDL_VIDEODRIVER=dummy` is how you run any of this without a display server.

---

## Acceptance criteria

- [ ] `gameboy/` imports nothing from `screen/`, and `dependencies` stays empty
- [ ] `uv run pytest` and `uv run mypy` pass with the `gui` extra not installed
- [ ] The display is a Protocol, with a pygame implementation and a fake
- [ ] The pygame display works under `SDL_VIDEODRIVER=dummy`
- [ ] The framebuffer reaches SDL without a per-pixel Python loop
- [ ] `run_frame` advances `ppu.frames` by exactly 1, and gives up within a
      budget when no frame is coming
- [ ] The window closes cleanly when asked
- [ ] A frame rate is measured over a rolling window and shown
- [ ] The README's instructions-per-second claim is replaced by a measured one
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. `frombuffer` hands SDL a pointer into the PPU's own `bytearray`. The PPU keeps
   writing to it while the frame is on screen. Name what a player could see
   because of that, and say whether the fix belongs in the frontend or in the
   PPU.
2. The display is behind a Protocol, so the loop cannot tell pygame from the
   fake. What would have to be true for that to stop being worth the indirection?
3. You measured 9 frames per second before optimising anything. Before you
   profile in 13B, write down where you think the time goes and how much. Then
   check. The gap between the two guesses is worth more than either.
4. `run_frame` needs a budget because a frame may never arrive. The CLI's
   `--frame` already needed one for the same reason. Is that the same guard
   written twice, and should it be?
