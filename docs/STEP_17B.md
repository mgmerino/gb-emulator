# Step 17B — The APU: registers, channel 2, the frame sequencer

## Goal

Move the pieces of 17A into the core. The emulator gets an APU (audio
processing unit) that answers the sound registers, runs channel 2 from the CPU's
clock, and turns its output into 48000 samples a second. The CLI writes those
samples to a WAV file.

At the end, `--frame 1800 --audio out.wav` on Tetris writes about 30 seconds of
audio. From 8.6 seconds on you hear the top voice of the title demo's music,
played by the same register writes the game makes on hardware.

---

## Map: the sound registers

The APU owns 48 bytes of the I/O page, `0xFF10`–`0xFF3F`. The first 23 are
registers, then nine unused bytes, then 16 bytes of wave RAM.

```
   0xFF10 ┌──────┬──────┬──────┬──────┬──────┐
          │ NR10 │ NR11 │ NR12 │ NR13 │ NR14 │  channel 1   pulse with sweep (17C)
   0xFF15 ├──────┼──────┼──────┼──────┼──────┤
          │  --  │ NR21 │ NR22 │ NR23 │ NR24 │  channel 2   pulse            (this step)
   0xFF1A ├──────┼──────┼──────┼──────┼──────┤
          │ NR30 │ NR31 │ NR32 │ NR33 │ NR34 │  channel 3   wave             (17C)
   0xFF1F ├──────┼──────┼──────┼──────┼──────┤
          │  --  │ NR41 │ NR42 │ NR43 │ NR44 │  channel 4   noise            (17C)
   0xFF24 ├──────┼──────┼──────┼──────┴──────┘
          │ NR50 │ NR51 │ NR52 │                 control      volume, panning, power
   0xFF27 ├──────┴──────┴──────┴────────────────┐
          │ unused, reads 0xFF                  │  0xFF27–0xFF2F
   0xFF30 ├─────────────────────────────────────┤
          │ wave RAM, 16 bytes                  │  0xFF30–0xFF3F, channel 3's samples
   0xFF40 └─────────────────────────────────────┘
            NRx0   NRx1   NRx2   NRx3   NRx4
            other  length volume period period high,
                   (duty) env.   low    trigger
```

Each row is one channel, and each column has the same job in every row. The
`x` in `NRx2` is the channel number. Channel 2 has no `NR20` because it has no
sweep, so `0xFF15` is a hole. The same goes for `0xFF1F`.

This step implements every register as storage, and channel 2 as sound. Channels
1, 3 and 4 accept writes and read back, but make no sound until 17C.

---

## Theory

### 1. Write-only bits read as 1

Many bits in these registers can be written but not read. `NR23`, the low byte
of channel 2's period, reads `0xFF` whatever was written to it. A write-only bit
has no wire back to the data bus, and an unwired line on the DMG's bus reads
high. You saw the same in `IF` (bits 7-5) and `TAC` (bits 7-3).

So each register has a read mask: the bits that always read 1. A read is the
stored value OR the mask.

```
   address  reg    mask       address  reg    mask
   0xFF10   NR10   0x80       0xFF1A   NR30   0x7F
   0xFF11   NR11   0x3F       0xFF1B   NR31   0xFF
   0xFF12   NR12   0x00       0xFF1C   NR32   0x9F
   0xFF13   NR13   0xFF       0xFF1D   NR33   0xFF
   0xFF14   NR14   0xBF       0xFF1E   NR34   0xBF
   0xFF15   --     0xFF       0xFF1F   --     0xFF
   0xFF16   NR21   0x3F       0xFF20   NR41   0xFF
   0xFF17   NR22   0x00       0xFF21   NR42   0x00
   0xFF18   NR23   0xFF       0xFF22   NR43   0x00
   0xFF19   NR24   0xBF       0xFF23   NR44   0xBF
                              0xFF24   NR50   0x00
                              0xFF25   NR51   0x00
                              0xFF26   NR52   0x70
                              0xFF27–0xFF2F   0xFF
```

Wave RAM has no mask: it reads back what was written.

### 2. The control registers

```
   NR52 0xFF26   │ 7 │ 6  5  4 │ 3   2   1   0 │
                 │ on│ unused  │ ch4 ch3 ch2 ch1│
                   R/W           read-only: is the channel playing?

   NR51 0xFF25   │ 7   6   5   4 │ 3   2   1   0 │
                 │ ch4 ch3 ch2 ch1 left │ ch4 ch3 ch2 ch1 right │

   NR50 0xFF24   │ 7 │ 6  5  4 │ 3 │ 2  1  0 │
                 │VIN│ left vol│VIN│right vol│
```

**NR52** is the APU's power switch. Clearing bit 7 turns the APU off. That clears
every register from `0xFF10` to `0xFF25`, and until bit 7 is set again, writes to
them are ignored. Wave RAM is not touched. Bits 3-0 report which channels are
playing. Writing them does nothing, because a channel starts and stops by its
own rules, in sections 5 and 7.

**NR51** routes each channel to the left output, the right output, both or
neither. **NR50** sets the volume of each side, 0 to 7. VIN is an audio input
from the cartridge that no licensed game uses. Both registers belong to the mixer,
which is 17C. In this step they are storage, and the output is mono.

### 3. Channel 2's registers

These are the settings you passed as arguments in 17A, in the bit positions the
game writes them to.

```
   NR21 0xFF16   │ 7  6 │ 5  4  3  2  1  0 │
                 │ duty │ initial length   │   duty: 0-3, the four patterns of 17A
                   R/W     write-only

   NR22 0xFF17   │ 7  6  5  4 │ 3 │ 2  1  0 │
                 │ init volume│dir│  pace   │   dir 1 = up; pace 0 = envelope off
                   R/W

   NR23 0xFF18   │ period, bits 7-0          │
                   write-only

   NR24 0xFF19   │ 7 │ 6 │ 5  4  3 │ 2  1  0 │
                 │ T │ L │ unused  │ period, │   T: trigger; L: length enable
                   W   R/W           bits 10-8
                                     write-only
```

The period is 11 bits split across two registers, the same 0 to 2047 value as
in 17A section 8.

Tetris writes channel 2 like this during the title demo. `NR21` is always `0x80`
(duty 2, length 0). `NR22` is `0xC3` or `0xC5` (volume 12, down, pace 3 or 5).
`NR24` is `0x86` or `0x87`: trigger, no length, and the period's top bits. A
write of `0x89` to `NR23` and `0x86` to `NR24` is period `0x689` = 1673, which is
`131072 / (2048 - 1673)` = 349.53 Hz, an F4.

### 4. The period divider

In 17A, the phase came from the sample index and the frequency in hertz. The
hardware has no hertz. It has a counter, which Pan Docs calls the period
divider:

```
   every 4 T-cycles (1048576 Hz):
       divider += 1
       if divider passed 2047:
           divider = period              from NR23/NR24
           duty step = (duty step + 1) % 8
```

The divider takes `2048 - period` ticks to overflow, so one duty step lasts
`2048 - period` ticks and a full wave `8 × (2048 - period)`. That is the
`131072 / (2048 - period)` formula of 17A, produced by counting.

You do not need to count one tick at a time. Keep how many ticks remain until
the next step, and subtract the instruction's ticks from it:

```
   ticks left: 375 ── instruction, 12 T-cycles = 3 ticks ──► 372
   ...
   ticks left:   2 ── instruction, 16 T-cycles = 4 ticks ──►  -2
                      overflow: step + 1, ticks left += 2048 - period ──► 373
```

A write to `NR23` or `NR24` changes the period, but the divider only reads it
when it reloads. A note change takes effect at the end of the current duty step.

### 5. Trigger, and the DAC

Every channel ends in a DAC that turns its digital output (0 to 15) into a
voltage. Channel 2's DAC is on when any of `NR22` bits 7-3 is set. So `NR22 =
0x00` or `0x01` (volume 0, down) turns the DAC off. Volume 0 with direction up,
`0x08`, leaves it on, because the volume can still rise.

A channel plays when it is on, and it can only be on while its DAC is on.
Writing `NR24` with bit 7 set triggers it:

- the channel turns on, if the DAC is on
- the length timer is reloaded to 64 if it had run out (section 7)
- the period divider is reloaded from the period
- the volume goes back to `NR22`'s initial volume, and the envelope timer restarts

This is the trigger from 17A task 4, which gives each note its own attack. The duty
step does not restart on trigger. It restarts only when the APU is powered off.

Turning the DAC off turns the channel off. Turning it on again does not turn
the channel on; that takes a trigger. Tetris uses this for rests. The title demo
writes `NR22 = 0x01` 27 times in the first 2400 frames, each followed by a
trigger that leaves the channel silent.

### 6. The frame sequencer

The envelope and the length timer run at fixed rates, slower than the divider.
They are clocked by a counter Pan Docs calls DIV-APU. It steps each time bit 12
of the timer's 16-bit counter goes from 1 to 0. That is bit 4 of `DIV`.

```
   timer counter: │15│14│13│▒12▒│11│ ... │ 0│
                             └─ falls every 8192 T-cycles: 4194304 / 8192 = 512 Hz

   step     0     1     2     3     4     5     6     7
   length   ●           ●           ●           ●            256 Hz
   sweep                ●                       ●            128 Hz, channel 1 only
   envelope                                           ●       64 Hz
```

The 64 Hz envelope is the one from 17A section 7, now driven by the timer
instead of by 750 samples. Because it hangs off the timer's counter, a write to
`DIV` resets it. If bit 12 was set, that reset is a falling edge, and the
sequencer steps early. The timer of step 09 works the same way.

### 7. The length timer

The length timer cuts a note short without the game writing anything else.
`NR21` bits 5-0 set it: it counts `64 - value` length clocks, at 256 Hz, and
only while `NR24` bit 6 is set. When it reaches 0 the channel turns off.

```
   NR21 bits 5-0     ticks     duration
   0                 64        250 ms
   32                32        125 ms
   63                1         3.9 ms
```

Tetris's channel 2 never sets bit 6, so it never uses the length timer. Channel 4
does, in 17C. Implement it here anyway. It is small, and channel 2 is the
simplest place to test it.

### 8. From the channel to samples

Channel 2's digital output is `duty bit × volume`, a number from 0 to 15. The
DAC maps it to the range -1 to 1. Pan Docs gives the slope as negative:

```
   digital    0     7.5     15
   analog    +1      0      -1        DAC off: 0
```

Inverting a wave does not change how it sounds (17A, duties 1 and 3), so the
sign matters only to match the documentation. Scale the analog value by a peak,
8000 as in 17A, so that four channels fit in 16 bits in 17C.

Two things change from 17A. A channel at volume 0 is not at 0: it is at +1, the
top of the range. A DMG with a channel on and silent outputs a constant level,
and the real console removes it with a capacitor, a high-pass filter. That
filter belongs to the mixer in 17C. Until then, expect a step in the WAV
wherever a channel turns on or off.

The other change is time. The APU runs at 4194304 Hz and the WAV wants 48000
samples a second, one every 87.38 T-cycles. That is not a whole number, so
keep the remainder in integers:

```
   after each instruction:
       acc += cycles × 48000
       while acc >= 4194304:
           acc -= 4194304
           take one sample of the channel's current output
```

Over one second exactly 48000 samples come out, with no drift. A frame of
70224 T-cycles gives 803.65 samples, so frames alternate between 803 and 804.

This is the simplest resampler. It takes whatever the channel outputs at that
instant, and it lets frequencies above 24000 Hz fold back into the audible range
(17A section 3). For square waves at musical pitches this is fine.

### 9. Where the APU sits

```
   Bus.read/write 0xFF10–0xFF3F ──► Apu.read / Apu.write
   Bus.tick(cycles)
     ├─► timer.tick     ── did counter bit 12 fall? ──► apu.frame_step()
     ├─► ppu.tick
     └─► apu.tick(cycles) ──► divider, duty step, samples
```

The bus is the only object that sees both the timer and the APU, so it detects
the falling edge: read bit 12 before `timer.tick`, read it after. An instruction
takes at most 24 T-cycles and the bit changes every 4096, so it can fall at most
once per call. A write to `DIV` goes through the bus too.

### 10. Python concepts this step introduces

- **`bytearray` and `bytes` as register files.** A `bytearray(0x20)` holds the
  registers, indexed by `address - 0xFF10`. The masks are a `bytes` constant,
  immutable like a frozen `String` of binary data in Ruby.
- **Slice assignment.** `regs[0:0x16] = bytes(0x16)` zeroes a range in place.
  Ruby's `regs[0, 0x16] = "\0" * 0x16` is the same idea.
- **The mutable default trap.** `def __init__(self, apu: Apu = Apu())` builds
  one `Apu` when the function is defined, and every `Bus` would share it. Use
  `apu: Apu | None = None` and build it inside. Ruby evaluates defaults on each
  call, so it does not have this problem.
- **Integer accumulators.** Floats drift: adding `87.38133` a million times does
  not land on a multiple of it. The accumulator of section 8 keeps everything in
  `int`, which in Python never overflows.

---

## Tasks

The code goes in a new module, `src/gameboy/apu.py`, and grows task by task.
Tests go in `tests/test_apu.py`.

### 1. The register file

An `Apu` that the bus routes `0xFF10`–`0xFF3F` to. It stores what is written and
reads it back through the masks of section 1. Wave RAM reads back as written.
`NR52` keeps its power bit, and clearing it clears `0xFF10`–`0xFF25` and ignores
writes there until it is set again. `NR52` bits 3-0 read 0 for now.

`Bus.post_boot` gives the APU the values the boot ROM leaves, from Pan Docs:
`NR10 = 0x80`, `NR11 = 0xBF`, `NR12 = 0xF3`, `NR14 = 0xBF`, `NR21 = 0x3F`,
`NR24 = 0xBF`, `NR30 = 0x7F`, `NR32 = 0x9F`, `NR34 = 0xBF`, `NR41 = 0xFF`,
`NR44 = 0xBF`, `NR50 = 0x77`, `NR51 = 0xF3`, `NR52 = 0xF1`.

**Acceptance:** after a write of `0x80` to `NR21`, it reads `0xBF`. `NR23` reads
`0xFF` after any write. `0xFF15` and `0xFF27` read `0xFF`. With power off, a
write to `NR22` is ignored and a write to wave RAM is not. After post-boot,
`NR50` reads `0x77` and `NR52` reads `0xF0`: the boot ROM leaves channel 1
playing, and channel 1 does not exist until 17C.

### 2. Channel 2's divider and duty

`Apu.tick(cycles)` advances channel 2's period divider (section 4). A write to
`NR24` with bit 7 set triggers it (section 5). The channel exposes its digital
output, 0 to 15, and `NR52` bit 1 reports whether it is on.

**Acceptance:** with period 1750 and duty 2, after a trigger, one duty step
takes 298 ticks, 1192 T-cycles, and a full wave 9536. With `NR22 = 0x01`, a
trigger leaves `NR52` bit 1 clear. Writing `NR22 = 0x00` to a playing channel
turns it off.

### 3. The frame sequencer

`Apu.frame_step()` advances the 8-step sequencer, clocking length on even steps
and the envelope on step 7. The bus calls it when bit 12 of the timer's counter
falls, after `timer.tick` and on a write to `DIV`.

**Acceptance:** on a fresh APU, with volume 15, down, pace 1, the volume reaches
0 after 15 envelope clocks, which is 120 calls to `frame_step`. With `NR21 = 63` and length enabled, the
channel turns off on the first length clock after the trigger. Running the bus
for 4194304 T-cycles gives 512 sequencer steps.

### 4. Samples

The APU fills a buffer of 16-bit samples at 48000 Hz using the accumulator of
section 8 and the DAC mapping, peak 8000 per channel.

**Acceptance:** 4194304 T-cycles give exactly 48000 samples, and 70224 give 803
or 804. A channel with its DAC off gives 0, and one with its DAC on and volume 0
gives +8000.

### 5. Audio from the CLI

`--audio PATH` with `--frame N` writes the samples of the run to a WAV file,
mono, 16-bit, 48000 Hz.

**Acceptance:** `--frame 1800` on Tetris writes about 30.3 seconds of audio.
From about 8.6 seconds on, it plays the top voice of the title demo's music.

### 6. Tests and docs

Tests for each task's acceptance. README: the 17B row in the steps table, and a
line on `--audio` where the CLI is described.

---

## Hints

- Keep the registers as raw bytes and decode fields when you need them, with a
  small property or a shift. Storing both a byte and its decoded fields means two
  copies that can disagree.
- The bus's `match` already has an `IO` case that catches `0xFF00`–`0xFF7F`. The
  APU's case has to come before it, or the writes land in `bus.io` and the APU
  never sees them.
- If the pitch is right but the notes change late, check that the divider reads
  the period when it reloads, not when the game writes it. If notes change late
  by a whole note, the trigger is not reloading the divider.
- If the WAV is silent but `NR52` bit 1 reads 1, the DAC check is reading the
  wrong bits of `NR22`.
- If the sequencer runs at twice or half its rate, you are watching bit 11 or
  bit 13. `DIV` is the high byte of the counter, so `DIV` bit 4 is counter bit
  12.
- A run of 1800 frames takes around 45 seconds. Use `python -O`, as with the
  window, and a shorter run while debugging.
- Pan Docs: <https://gbdev.io/pandocs/Audio.html>,
  <https://gbdev.io/pandocs/Audio_Registers.html> and
  <https://gbdev.io/pandocs/Audio_details.html>.

---

## Acceptance criteria

- [ ] `Apu` in `src/gameboy/apu.py`, routed from the bus for `0xFF10`–`0xFF3F`
- [ ] Reads apply the masks; wave RAM reads back as written
- [ ] `NR52` power off clears `0xFF10`–`0xFF25` and blocks writes to them
- [ ] Channel 2's divider, duty, trigger and DAC as in sections 4 and 5
- [ ] The frame sequencer is clocked by bit 12 of the timer's counter, including
      on `DIV` writes
- [ ] Length and envelope on their sequencer steps
- [ ] 48000 samples per 4194304 T-cycles, with no drift
- [ ] `--audio` writes a WAV, and Tetris's title demo plays its top voice in it
- [ ] Tests, README row; `pytest`, `ruff check`, `ruff format --check` and
      `mypy` clean

---

## Questions to ask yourself before moving on

1. In 17A the envelope counted samples, and here it counts falling edges of a
   timer bit. If you wrote a ROM that writes `DIV` in a tight loop, what would
   happen to its notes' envelopes?
2. The resampler takes the channel's output at one instant every 87.38 cycles
   and ignores what happened in between. Which notes would that lose detail on:
   high ones or low ones?
3. Channel 2 sitting at volume 0 is at +1, not at 0. What does a game hear when
   all four channels are on and silent, and why does nobody notice on hardware?
4. The bus detects the frame sequencer's edge because it sees both devices. What
   else in the emulator would break if a device ticked itself instead of being
   ticked by the bus?
