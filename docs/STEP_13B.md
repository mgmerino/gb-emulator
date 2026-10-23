# Step 13B — Real time

## Goal

Make the emulator run Tetris at the speed of a DMG, 59.7 frames per second, and
hold it there.

That is two jobs in a fixed order. First make it fast enough, by measuring where
the time goes and removing the biggest costs one at a time. Then make it no
faster, by pacing the frames against the wall clock. Pacing comes second because
there is nothing to hold back until the emulator can outrun the hardware.

At the end the README's speed line has a before and an after, and both are
measurements.

---

## Theory

### 1. Where a frame's time goes

This is the profile of 120 frames of Tetris's title screen, taken after 600
frames of warm-up. The tree shows *cumulative* time: each line includes
everything called from inside it. Percentages are of the whole run.

```
   machine.step                                   100%
   ├── bus.tick                                    67%
   │   ├── ppu.tick                                60%
   │   │   └── _render_scanline
   │   │       └── _render_background_line         54%
   │   │           └── tile_row                    52%   2,764,800 calls
   │   │               └── decode_row_index        46%
   │   │                   └── compute_index       28%  22,126,080 calls
   │   │                       └── get_bit                59,332,987 calls
   │   └── timer.tick                               6%
   └── cpu.step                                    32%
       ├── pending                                 12%     918,004 calls
       ├── instruction bodies, fetch_u8, bus.read  ~14%
       └── Registers.__setattr__                    6%
```

Two call counts in it explain most of the cost.

**`tile_row` runs 2,764,800 times.** That is 120 frames × 144 lines × 160
pixels: once per pixel. Each call decodes a whole row of eight pixels from two
bytes of VRAM, returns them as a tuple, and the caller keeps one of the eight.
Step 11B's task 3 left this alone on purpose: "the obvious optimisation ... is
not this step's business". This step changes it.

**`pending` runs 918,004 times**, once per instruction, and most of the time
there is nothing pending. It reads `IE` and `IF` through `bus.read`, ANDs them,
and loops over the five members of `Interrupt` to find which bit is set, even
when the AND came out zero.

### 2. Reading a profile

`cProfile` is in the standard library. It records every function call, and
`pstats` sorts and prints the result.

```
uv run python -m cProfile -s cumulative <script> | head -40
```

It reports two times per function:

- **`tottime`** is time spent in the function's own lines, excluding the
  functions it calls.
- **`cumtime`** includes everything it calls.

A high `cumtime` says where to look. A high `tottime` says which line is doing
the work.

The profiler makes everything slower. These 120 frames took 30.8 s under
`cProfile` and about 8.5 s without it. It adds a fixed cost to every function
call, so code made of many small calls looks worse under it than it is. Use the
profile to find *where*; use a plain timer, with the profiler off, to say *how
much* a change helped.

### 3. Why calls are the cost

Each Python function call builds a frame object, binds arguments, and tears it
all down on return. On this machine that is in the tens of nanoseconds, and
`experiments/dispatch_shapes.py` measured some of it. The arithmetic inside
`compute_index` is a shift, an AND and an OR, which costs far less than the call
that wraps it.

So the expensive parts of the profile are not the ones doing hard work. They are
the ones doing easy work millions of times, through several layers of calls per
pixel. Ruby's YARV has the same shape, and the same advice applies there.

The usual remedies, roughly from cheapest to most invasive:

| Remedy | What it trades |
| --- | --- |
| Do the work once and reuse it | Decode a tile row once for its eight pixels, not eight times |
| A lookup table | Memory for calls: compute every answer up front, then index |
| Skip the common case early | Return before the loop when the answer is "nothing" |
| Inline a small helper | Readability for one call per use |

### 4. Measured before writing this

Each candidate below was tried in a scratch script that patched the module from
outside, with the repository unchanged. Tetris title screen, after 600 frames,
six seconds of frames, CPython 3.12:

```
   baseline                                  13.7 - 14.5 fps
   decode table for tile rows                21.1 - 24.6 fps
   pending returns early when IE & IF is 0   16.9 fps
   python -O alone                           15.7 fps
   table and pending                         29.7 - 32.6 fps
   table and pending, under -O               37.7 - 38.5 fps
```

Ranges are the lowest and highest of several runs; a single number is a single
run. The machine had other things running, and one run of "table and pending"
came out at 14.3, the same as the baseline, for no reason in the code. That is
why task 1 asks for three runs before believing any of them. These numbers show
the order of magnitude of each change. Your own measurements are the ones that
count.

They also show that these three changes alone do not reach 59.7. The rest of the
distance is whatever the next profile shows once these three are gone, which is
why task 4 starts with a new profile.

### 5. `python -O`

`Registers.__setattr__` checks every register write against the register's
width. It is inside `if __debug__:`, and `python -O` sets `__debug__` to
`False`, so the check is never defined. `-O` also removes `assert` statements.

Step 05 made that choice on purpose ("Leave it that way"). The check exists to
catch masking bugs while the instruction set was being written, and the tests
still run without `-O`, so it keeps doing that job. The window is where speed
matters and the check finds nothing new, so it can run with `-O`:

```
uv run --extra gui python -O -m screen path/to/TETRIS.gb
```

### 6. Keeping it correct while it gets faster

An optimisation that changes a pixel is a bug. The test suite covers the
renderer feature by feature, but it does not run a real ROM. Two checks run one:

- **A frame fingerprint.** Run Tetris to frame 600, hash the framebuffer with
  `hashlib.sha256`, and print the digest. Record it before the first change.
  After every change it must be identical. One differing pixel changes it.
- **`dmg-acid2`.** It must still match its reference image exactly.

Use `hashlib`, not the built-in `hash()`. `hash()` on `bytes` is salted per
process, so two runs print different values for the same frame.

### 7. Pacing

A DMG frame lasts:

```
   70224 dots / 4194304 dots per second = 16.7427 ms
```

Pacing means that after each frame the loop waits until 16.74 ms have passed
since the previous one started, then starts the next.

```
   frame n                   frame n+1
   ├── emulate ──┤░░ wait ░░├── emulate ──┤░░ wait ░░├
   │                        │                        │
   deadline n               deadline n+1             deadline n+2
   └──────── 16.74 ms ──────┘
```

Compute each deadline from the previous **deadline**, not from the moment the
wait ended. `time.sleep` wakes a little late, and measuring from the wake-up
adds that lateness to every frame; after a minute the game has drifted behind.
Adding the period to the deadline keeps the error from accumulating.

If a frame overruns its deadline, do not try to catch up by running the next
ones with no wait. That produces a burst of fast frames after every slow one.
Move the deadline to now and continue.

`pygame.time.Clock.tick(60)` does something similar, but it counts whole
milliseconds and its target is 60, not 59.7275. That runs 0.45% fast, about one
extra frame every four seconds. It would play fine; the deadline version is a
few lines, exact, and testable without pygame.

### 8. Where the pacing lives

The core has no wall clock and should not get one. A frame in `gameboy/` is
70224 T-cycles, and how long that takes in seconds is the frontend's business.
The pacing goes in `screen/loop.py`, next to `FrameRate`, which already reads
`time.perf_counter`.

The loop tests already replace `time.perf_counter` with a fake `Clock` that
moves only when told to. Pacing needs `time.sleep` replaced the same way: a fake
sleep that advances the fake clock by the amount asked, and records it. Then a
test can say "a frame that took 5 ms was followed by a wait of 11.74 ms" without
waiting for anything.

### 9. Python concepts this step introduces

- **`cProfile` and `pstats`.** The standard library's profiler. Ruby's nearest
  equivalents are `ruby-prof` and `stackprof`, which are gems.
- **`__debug__` and `-O`.** A built-in constant the compiler folds away, so code
  under `if __debug__:` costs nothing under `-O`. Ruby has no equivalent switch.
- **Building a table with a comprehension.** A 256 × 256 table of tuples is one
  nested comprehension, built once at import time. Python evaluates module-level
  code once per process, as Ruby does with a constant assigned in a class body.
- **`functools.cache`.** A decorator that remembers a function's results by
  argument. It is the shortest way to a lookup table, at the cost of a call and
  a dict lookup on every use. Measure it against an explicit table.
- **`hashlib`.** Stable digests, unlike `hash()`. `Digest::SHA256` in Ruby.

---

## Tasks

### 1. The instrument

Write `experiments/bench.py`. It loads a ROM, runs a number of frames to warm
up, then runs frames for a fixed number of seconds and prints three things:
frames per second, the percentage of 59.7275 that is, and the SHA-256 of the
framebuffer at the end of the warm-up.

No window, so the number measures the emulator and nothing else. Follow the
other scripts in `experiments/`: a docstring with the question, how to run it,
and a sample run.

Run it three times on Tetris and write down the baseline and the digest.

**Acceptance:** three runs agree within a couple of fps, and the digest is the
same in all three.

---

### 2. The profile, and a guess before it

Step 13A's question 3 asked you to write down where you think the time goes
before profiling. Do that now, in a sentence or two, before running anything.

Then profile the same frames with `cProfile` and compare with the tree in
section 1. Save the top of the output somewhere you can diff it against later.

**Acceptance:** a written guess, a profile, and one sentence on where they
disagreed.

---

### 3. Decode each tile row once

The background loop calls `tile_row` per pixel and uses one of its eight
results. Two ways to stop that, and they compose:

- **Decode once per tile.** Walk the line a tile at a time. Decode the row once
  and use all eight pixels, or the part of them that is on screen. The first and
  last tiles are partial when `SCX` is not a multiple of 8.
- **Make decoding cheap.** A table indexed by the two bytes returns the eight
  indices with no arithmetic at all. Objects and the window use the same
  decoding, so they gain too.

Do one, measure, then decide whether the other is worth it. Whichever you pick,
`decode_row_index` keeps its tests.

**Acceptance:** the frame digest is unchanged, `dmg-acid2` still matches, and
the bench number has moved. Write the before and after in the commit message.

---

### 4. The cost per instruction

Profile again. With the renderer cheaper, the work done on every instruction is
a larger share: `pending`, `timer.tick`, `ppu.tick`'s mode logic, `bus.read`,
and the register guard.

- **`pending`** can return before it loops when `IE & IF & 0x1F` is 0. That is
  the answer on almost every call.
- **The register guard** goes away under `-O`. Decide whether the window runs
  with it, per section 5, and say so in the README.
- **Whatever the new profile shows next.** Pick the top item, change one thing,
  measure. Stop when the change stops paying for itself.

One change per commit, each with its number. A commit that changes two things
cannot say which one helped.

**Acceptance:** the digest is unchanged after every commit, and each commit
message carries a before and an after.

---

### 5. Pace the frames

In `screen/loop.py`, after `present`, wait until the next deadline per section
7. The period is `FRAME_CYCLES / 4194304` seconds; derive it rather than typing
16.74.

Make the wait something the tests can replace, as `time.perf_counter` already
is. Add a flag to turn pacing off, for the bench and for anyone who wants to
see how fast it can go: `--unpaced`, or whatever reads better to you.

Tests, with the fake clock and a fake sleep:

- a frame that took 5 ms is followed by a wait of the rest of the period
- a frame that took longer than the period is followed by no wait
- after an overrun, the next deadline is a period from now, not from the missed
  deadline
- unpaced, nothing waits

**Acceptance:** the window's frame rate reads 59.7 on Tetris, as long as the
unpaced bench reads above it. If the emulator is still slower than real time,
pacing must not make it any slower, and the tests prove that.

---

### 6. Docs

`README.md`: the speed line gets the before and after from tasks 1 and 4, and
the usage section says how to run unpaced and whether to use `-O`. The 13B row
becomes "done". "What is missing" loses the speed paragraph, or keeps whatever
part of it is still true.

`experiments/README.md`: a row for `bench.py`.

---

## Hints

- If the digest changes after an optimisation, the first suspect is the partial
  tile at the left edge: with `SCX % 8 != 0`, the first tile on screen starts
  partway through its row.
- If the numbers jump around by more than a few fps between identical runs,
  something else on the machine is busy. Close it, or take the best of several
  runs rather than the average.
- If an optimisation measures as a loss, check that the bench is not timing
  the table being built. Build it at import, and start the clock after warm-up.
- If the window reads 60.0 rather than 59.7, the period is 1/60.
- If the frame rate slowly falls below 59.7 over a minute while the bench says
  the emulator is fast enough, each deadline is being measured from the wake-up
  instead of from the previous deadline.
- If the tests for pacing are slow, something calls the real `time.sleep`.

---

## Acceptance criteria

- [ ] `experiments/bench.py` prints fps, percentage of real time, and a frame
      digest
- [ ] A baseline and a profile were recorded before the first optimisation
- [ ] Tetris's frame digest and `dmg-acid2` are unchanged after every
      optimisation
- [ ] Every optimisation commit carries its before and after
- [ ] Pacing holds the window at 59.7 when the emulator can go faster, and
      never slows it down when it cannot
- [ ] Pacing is tested with a fake clock and a fake sleep, and can be turned off
- [ ] `gameboy/` still has no wall clock
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. A decode table makes the renderer faster and the code shorter. What did it
   cost, in memory and in startup time, and how would you find out?
2. The register guard was written to catch bugs. Under `-O` it catches none.
   What would have to happen for you to want it back in the window?
3. After task 4, what share of a frame is still the renderer, and what share
   the CPU? Which one would you attack next, if you had to?
4. Pacing sleeps the whole wait in one call. What would a frame look like on
   screen if `time.sleep` overslept by 5 ms once a second?
