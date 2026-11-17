# Step 17C — The APU: channels 1, 3 and 4, the mixer

## Goal

Give the APU its other three channels and mix all four into a stereo signal.
Channel 1 is channel 2 plus a sweep that slides the pitch. Channel 3 plays 32
samples the game writes to wave RAM. Channel 4 plays noise from a shift
register. The mixer routes each channel to the left side, the right side or
both, applies the master volume and removes the constant level with a
high-pass filter.

At the end, `--frame 1800 --audio out.wav` on Tetris writes the title demo's
music with its bass and drums, in stereo.

17B had six short tasks. This step has four, one per piece of hardware, and
each one carries its own tests.

---

## Map: the sound registers

The same 48 bytes as in 17B. This step gives meaning to the three rows that
were storage, and to `NR50` and `NR51`.

```
   0xFF10 ┌──────┬──────┬──────┬──────┬──────┐
          │ NR10 │ NR11 │ NR12 │ NR13 │ NR14 │  channel 1   pulse with sweep   task 1
   0xFF15 ├──────┼──────┼──────┼──────┼──────┤
          │  --  │ NR21 │ NR22 │ NR23 │ NR24 │  channel 2   pulse              17B
   0xFF1A ├──────┼──────┼──────┼──────┼──────┤
          │ NR30 │ NR31 │ NR32 │ NR33 │ NR34 │  channel 3   wave               task 2
   0xFF1F ├──────┼──────┼──────┼──────┼──────┤
          │  --  │ NR41 │ NR42 │ NR43 │ NR44 │  channel 4   noise              task 3
   0xFF24 ├──────┼──────┼──────┼──────┴──────┘
          │ NR50 │ NR51 │ NR52 │                 control                        task 4
   0xFF27 ├──────┴──────┴──────┴────────────────┐
          │ unused, reads 0xFF                  │
   0xFF30 ├─────────────────────────────────────┤
          │ wave RAM, 16 bytes                  │  channel 3's samples          task 2
   0xFF40 └─────────────────────────────────────┘
            NRx0   NRx1   NRx2   NRx3   NRx4
```

The columns keep their jobs, with two exceptions. Channel 3 has no envelope, so
`NR32` holds a fixed output level, and `NR30` holds its DAC switch. Channel 4
has no period, so `NR43` holds the settings of its noise generator.

## Map: from four channels to two samples

```
   channel 1 ─┐                 ┌─ NR51 bits 0-3 ──► sum ─► × NR50 right ─► filter ─► right
   channel 2 ─┤ each: DAC,      │
   channel 3 ─┤ 0..15 ─► ±8000 ─┤
   channel 4 ─┘                 └─ NR51 bits 4-7 ──► sum ─► × NR50 left  ─► filter ─► left
```

In 17B the WAV got channel 2's DAC output directly. Now each channel's DAC
output goes to the mixer, which builds a left and a right sample from them.

---

## Theory

### 1. Two pulse channels, one piece of code

Channel 1 has every register channel 2 has, at the same offsets, plus `NR10`.
Its duty, length, envelope, period, trigger and DAC work the same way. Only
the sweep is new.

In 17B the `APU` reads channel 2's fields from fixed addresses: `_duty` reads
`NR21`, `_pace` reads `NR22`. Channel 1 would need the same properties over
`NR11` and `NR12`. Copying them gives two versions of each rule that can drift
apart. Task 1 starts by moving that logic where both channels can use it.

There are two common shapes:

- **The channel knows its base address.** `PulseChannel` gets a field with the
  address of its `NRx0`, and every register read becomes `base + offset`. The
  channel still asks the `APU` for the bytes.
- **The channel holds a view of its own registers.** The `APU` keeps one
  `bytearray` for all registers and hands each channel a `memoryview` of its
  five bytes. A `memoryview` shares memory with the array it comes from, so a
  write through the `APU` shows up in the channel's view and the other way
  round. The channel reads `regs[2]` for its `NRx2` and never sees an absolute
  address.

The second shape keeps all of a channel's rules inside its class, and the
`APU` becomes a router: it decides which channel an address belongs to and
passes the write on. It is the shape the hints assume, but both work.

### 2. The sweep

The sweep changes channel 1's period on its own, at 128 Hz, without the game
writing anything. Games use it for sliding sound effects.

```
   NR10 0xFF10   │ 7 │ 6  5  4 │ 3 │ 2  1  0 │
                 │ - │  pace   │dir│  step   │   dir 0 = up (period grows), 1 = down
```

The channel keeps a copy of its period, the shadow period, and a sweep timer.
On each sweep clock the timer counts down. When it reaches 0 it reloads from
the pace and, if the pace is not 0, the sweep runs one iteration:

```
   delta = shadow >> step
   new   = shadow + delta      (dir 0)
   new   = shadow - delta      (dir 1)

   if new > 2047:       the channel turns off
   elif step != 0:      shadow = new, and new goes back into NR13 and NR14
                        then the calculation runs once more, only to check
                        for overflow; that second result is not stored
```

A larger step makes smaller changes: step 1 adds half the period each time,
step 7 adds 1/128 of it. A larger period is a higher note, so direction 0
slides the pitch up.

Going down cannot overflow. `shadow - (shadow >> step)` is never negative.

On trigger:

- the shadow period is loaded from `NR13` and `NR14`
- the sweep timer reloads from the pace, and a pace of 0 counts as 8
- the sweep is enabled if the pace or the step is not 0
- if the step is not 0, the calculation and the overflow check run at once, so
  a trigger can turn the channel off straight away

Tetris writes `NR10 = 0x00` in the first 1800 frames, so its music never
sweeps. The sweep is there for the sound effects of other games, and the tests
are the only check on it.

The frame sequencer of 17B already has a place for it: steps 2 and 6.

```
   step       0   1   2   3   4   5   6   7
   length     ●       ●       ●       ●           256 Hz
   sweep              ●               ●           128 Hz
   envelope                               ●        64 Hz
```

### 3. The wave channel

Channel 3 plays a waveform the game draws itself. Wave RAM holds 32 samples of
4 bits each, two per byte, high nibble first:

```
   0xFF30   0xFF31   0xFF32         0xFF3F
   ┌──┬──┐ ┌──┬──┐ ┌──┬──┐        ┌──┬──┐
   │ 0│ 1│ │ 2│ 3│ │ 4│ 5│  ...   │30│31│     sample index
   └──┴──┘ └──┴──┘ └──┴──┘        └──┴──┘
   high low
```

A byte of `0x9F` holds sample 9 at an even index and sample 15 at the odd one
after it.

The registers:

```
   NR30 0xFF1A   │ 7 │ 6 .. 0 │
                 │DAC│ unused │       DAC on when bit 7 is set
   NR31 0xFF1B   │ initial length, 8 bits │      counts 256 - value
   NR32 0xFF1C   │ 7 │ 6  5 │ 4 .. 0 │
                 │ - │level │ unused │      0 mute, 1 100%, 2 50%, 3 25%
   NR33 0xFF1D   │ period, bits 7-0 │
   NR34 0xFF1E   │ T │ L │ - - - │ period 10-8 │  as NR24
```

The divider works like channel 2's but runs twice as fast, every 2 T-cycles
instead of every 4. When it overflows, the channel moves to the next of the 32
samples instead of the next of 8 duty steps.

```
   one sample lasts    2 × (2048 - period) T-cycles
   one wave lasts     32 × that
   frequency          65536 / (2048 - period) Hz

   period 1856  →  65536 / 192  =  341.3 Hz
```

The output level is a right shift of the 4-bit sample, not a multiplication.
Level 1 outputs the sample as it is, level 2 shifts it right once (15 becomes
7), level 3 shifts it twice (15 becomes 3), and level 0 shifts it out
completely. The result goes to a DAC like the other channels'.

The DAC is the one register bit that changes: `NR30` bit 7, instead of any of
`NRx2` bits 7-3. Turning it off turns the channel off, as in 17B.

The length timer counts 256 instead of 64, because `NR31` uses all 8 bits.

A trigger turns the channel on if the DAC is on, reloads the divider, reloads
an expired length timer with 256, and resets the sample index to 0. On
hardware the first sample played is index 1, because the index advances
before the first read. That shifts the wave by 1/32 of a cycle, which nobody
can hear, so you can ignore it.

### 4. The noise channel

Channel 4 plays noise. Its source is a linear feedback shift register, LFSR: a
15-bit number that, on each clock, shifts right by one and feeds a new bit in
at the top, computed from the two bits at the bottom. The bit that ends up at
the bottom decides the output, volume or 0.

```
   NR43 0xFF22   │ 7  6  5  4 │ 3 │ 2  1  0 │
                 │   shift    │ W │ divider │     W: 0 = 15-bit, 1 = 7-bit
```

One LFSR clock, as Pan Docs describes it:

```
   1. x = 1 if bit 0 == bit 1 else 0         (XNOR of the two lowest bits)
   2. bit 15 = x
   3. if W is set: bit 7 = x as well
   4. shift the whole register right by 1
   5. output volume if bit 0 is 1, else 0
```

The register is 16 bits wide, but bit 15 only holds `x` until the shift moves
it to bit 14. A trigger sets the whole register to 0.

```
   start      000 0000 0000 0000     bits 0 and 1 equal → x = 1
   step 1     100 0000 0000 0000     bits 0 and 1 equal → x = 1
   step 2     110 0000 0000 0000
   ...        the 1s walk down; once they reach bits 0 and 1 the pattern mixes
```

The sequence repeats after 32767 clocks in 15-bit mode, long enough to sound
like hiss. In 7-bit mode, bit 7 is overwritten on every clock, so only the
bottom 7 bits matter and the sequence repeats after 127 clocks. That is short
enough to have a pitch, and it sounds metallic.

The clock rate comes from the divider and the shift:

```
   T-cycles per LFSR clock = base[divider] << shift

   divider   0    1    2    3    4    5    6    7
   base      8   16   32   48   64   80   96  112
```

Pan Docs gives the same as `262144 / (divider × 2^shift)` Hz, with divider 0
counted as 0.5. A shift of 14 or 15 stops the LFSR, and the channel holds its
last output.

`NR41` bits 5-0 load a 64-tick length, as `NR21`. `NR42` is an envelope,
exactly as `NR22`, and also controls the DAC. `NR44` has the trigger and the
length enable, with no period bits.

### 5. Length and the status bits, for all four channels

Each channel has its own length timer, clocked by the same sequencer steps.
Channels 1, 2 and 4 count from 64, channel 3 from 256. When one runs out, its
channel turns off.

`NR52` bits 3-0 report the four channels, bit 0 for channel 1. A channel's bit
is set by a trigger with its DAC on, and cleared when its DAC turns off, its
length runs out or, for channel 1, the sweep overflows. The envelope reaching
0 does not clear it.

### 6. The mixer

`NR51` decides which channels reach each side:

```
   NR51 0xFF25   │ 7   6   5   4 │ 3   2   1   0 │
                 │ 4   3   2   1 │ 4   3   2   1 │
                 │     left      │     right     │
```

The boot ROM leaves `0xF3`. Tetris rewrites `NR51` on every frame of the
title demo, switching between `0xFF`, `0xFD` and `0xF3`, so voices move between
the sides as the music plays.

Each side adds the DAC outputs of its channels. With four channels at ±8000,
a side ranges from -32000 to +32000, which fits in a 16-bit sample. That is
why 17A picked a peak of 8000.

`NR50` scales each side:

```
   NR50 0xFF24   │ 7 │ 6  5  4 │ 3 │ 2  1  0 │
                 │VIN│  left   │VIN│  right  │

   side × (volume + 1) / 8         volume 7 → × 1     volume 0 → × 1/8
```

Volume 0 is quiet but not silent. The boot ROM leaves `NR50 = 0x77`, both
sides at full volume, and Tetris keeps it. VIN stays ignored.

### 7. The high-pass filter

A DAC that is on and silent sits at +1, so the sum of the channels has a
constant level added to it. In 17B that showed up as a step in the WAV each
time the DAC turned on. A speaker cannot reproduce a constant level, and the
console removes it with a capacitor in series with the output. A capacitor
lets changes through and blocks a constant voltage.

In software that is a two-line filter per side, run once per output sample:

```
   out = in - capacitor
   capacitor = in - out × charge
```

`capacitor` starts at 0 and follows the slow part of the signal. Subtracting
it leaves the fast part, the sound. `charge` sets how slowly it follows. Pan
Docs gives 0.999958 per T-cycle for the DMG. At 48000 samples a second that
becomes:

```
   charge = 0.999958 ** (4194304 / 48000) = 0.99634
```

When every DAC is off, the output is 0 and the filter does not run.

The filter needs fractions, so `capacitor` is a `float`. That is a different
case from the sample accumulator in 17B. The accumulator counts events, and an
error there adds up forever. The filter's state decays, so a rounding error
in it fades out within a few hundred samples.

### 8. Stereo samples

A stereo WAV interleaves the two sides: left, right, left, right. One frame of
the WAV is a pair. The buffer stays a single `array("h")`, now with two values
per sample instant:

```
   samples   [ L0, R0, L1, R1, L2, R2, ... ]
   one second    96000 values, 48000 frames
```

The WAV header says 2 channels, and the rest of `write_wav` stays the same.
Audio devices take the same interleaved layout, so 17D can pass the buffer to
the window's sound output as it is.

### 9. Python concepts this step introduces

- **`memoryview`.** A view into the memory of a `bytearray` without copying
  it. `memoryview(regs)[0:5]` is a 5-byte window that reads and writes the
  original. Ruby has no direct equivalent; the closest is a `String` slice,
  which copies.
- **Composition across classes.** Three channel classes with the same method
  names (`tick`, `clock_length`, `output`) let the `APU` loop over them. A
  `Protocol` can name that shared shape for mypy, as `MemoryDevice` does for
  the bus. Ruby gets the same through duck typing, with no declaration.
- **Bitwise feedback.** The LFSR is two lines of `&`, `|`, `^` and `>>`. Python
  integers have no width, so masking to 15 bits is your job, like the `u8` and
  `u16` helpers in `bits.py`.
- **`float` where it belongs.** `0.99634` is a `float`, and the filter output
  is rounded back to `int` with `round()` before going into the `array`.

---

## Tasks

The code stays in `src/gameboy/apu.py`, which can grow into a package if it
gets long. Tests go in `tests/test_apu.py`, or one test file per channel.

### 1. Channel 1: one pulse class for two channels, and the sweep

Move the pulse logic out of the `APU` so channels 1 and 2 share it (section
1). Then add the sweep to channel 1 (section 2), clocked on sequencer steps 2
and 6. `NR52` bit 0 reports channel 1.

Do the move first and commit it with every 17B test green, before channel 1
exists. Then add channel 1 on top.

**Acceptance:** every 17B test passes unchanged after the move. Channel 1 at
period 1750 and duty 2 gives a duty step every 298 ticks, as channel 2 does.
With `NR10 = 0x12` (pace 1, up, step 2) and period 1000, the sweep writes
1250, then 1562, then 1952 into `NR13` and `NR14`. The third iteration's
follow-up check gives 2440 and turns the channel off. With `NR10 = 0x11` and
period 1000, the first iteration writes 1500 and its check (2250) turns the
channel off at once. With step 0 and pace 1, the period stays as it is. A
trigger with period 2000 and `NR10 = 0x01` turns the channel off at once.

### 2. Channel 3: the wave channel

Channel 3 plays wave RAM (section 3): the divider every 2 T-cycles, the 32
samples, the output level shift, the `NR30` DAC, and a 256-tick length.
`NR52` bit 2 reports it.

**Acceptance:** with wave RAM filled with `0x01 0x23 ... 0xEF`, the output at
level 1 walks 0, 1, 2 … 15, 0, 1 … one sample per `2 × (2048 - period)`
T-cycles. At level 2 the same sample
15 outputs 7, at level 3 it outputs 3, at level 0 it outputs 0. `NR31 = 255`
with length enabled turns the channel off on the first length clock.

### 3. Channel 4: the noise channel

Channel 4 runs the LFSR (section 4) at the rate `NR43` gives, with the
envelope and length of the pulse channels. `NR52` bit 3 reports it.

**Acceptance:** after a trigger, the first LFSR clocks give the register
values `0x4000`, `0x6000`, `0x7000` in 15-bit mode, and `0x4040`, `0x6060`,
`0x7070` in 7-bit mode. In 7-bit mode the bit
sequence repeats every 127 clocks, and in 15-bit mode every 32767. With
`NR43 = 0x00`, the LFSR clocks every 8 T-cycles; with `NR43 = 0x21` (shift 2,
divider 1), every 64. Shift 14 stops it.

### 4. The mixer and stereo

The four DAC outputs go through `NR51`, `NR50` and the high-pass filter
(sections 6 and 7) into interleaved stereo samples (section 8). `write_wav`
writes 2 channels. README: the 17B and 17C rows in the steps table, and the
line on `--audio` says stereo and all four channels.

**Acceptance:** one second gives 96000 values. A channel routed only left
gives 0 on the right. `NR50 = 0x07` scales the left side by 1/8. With all
DACs off the output is exactly 0. A constant DC input decays below 1% of its
start within 0.1 s (4800 samples). `--frame 1800` on Tetris writes a stereo
WAV with the melody, the bass and the drums.

---

## Hints

- Each channel's divider is the same loop you wrote in 17B with a different
  unit: 4 T-cycles for channels 1 and 2, 2 for channel 3, `base << shift`
  T-cycles for channel 4. A shared helper that takes the cycles per tick can
  serve all four.
- A channel that is off does not need its divider. Skipping it saves time,
  and four dividers per instruction will cost frames per second: 56 fps
  before this step, less after.
- The NR52 bits read straight from each channel's `enabled`. If a bit sticks
  at 1, the channel is missing one of the three ways to turn off.
- If channel 1 sweeps the wrong way, check the direction bit. Bit 3 set means
  the period goes down, and so does the pitch.
- If the sweep keeps sliding after the channel turns off, the overflow check
  turns off the channel but the next clock runs anyway. Check `enabled` first.
- If channel 3 plays an octave too high, its divider runs every 4 T-cycles
  instead of 2 and the wave has 32 steps. An octave too low is the other way
  round.
- If channel 4 is silent, print the LFSR after a few clocks. Stuck at 0 means
  the XNOR is an XOR: with every bit 0, XOR feeds 0 forever.
- If the WAV still jumps each time a channel starts, the filter is off, or
  `charge` is the per-T-cycle value, 0.999958, used once per sample. That
  makes the filter 87 times slower than it should be.
- Changing the buffer to stereo breaks the 17B tests that count samples.
  Update them to count values, or to divide by 2.
- Pan Docs: <https://gbdev.io/pandocs/Audio_Registers.html> and
  <https://gbdev.io/pandocs/Audio_details.html>.

---

## Acceptance criteria

- [ ] Channels 1 and 2 share one pulse implementation
- [ ] Channel 1's sweep, with overflow turning it off, on sequencer steps 2 and 6
- [ ] Channel 3 plays wave RAM with its four output levels and a 256-tick length
- [ ] Channel 4 runs the LFSR in 15- and 7-bit modes at the rate `NR43` sets
- [ ] `NR52` bits 3-0 report all four channels
- [ ] `NR51` routing, `NR50` volume and a high-pass filter per side
- [ ] Interleaved stereo samples and a 2-channel WAV
- [ ] Tetris's title demo plays its melody, bass and drums
- [ ] Tests, README rows; `pytest`, `ruff check`, `ruff format --check` and
      `mypy` clean

---

## Questions to ask yourself before moving on

1. Channel 3's output level is a shift, so 25% of sample 15 is 3, not 3.75.
   What happens to quiet waves with small sample values at level 3?
2. The LFSR in 7-bit mode sounds like a note. Which property of the sequence
   gives it a pitch, and how would you compute that pitch from `NR43`?
3. The filter's `capacitor` is a `float`, and the sample accumulator in 17B had
   to be an `int`. What is the difference between the two that makes one safe
   and the other not?
4. Every channel now ticks on every instruction. Which of them could tick less
   often without changing the samples, and how would the APU know when it can
   skip work?
