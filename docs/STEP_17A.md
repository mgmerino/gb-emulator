# Step 17A — Sound from numbers

## Goal

Generate sound in software from nothing but arithmetic, and write it to a WAV
file you can play. No emulator yet: this step is a script in `experiments/`.

Every piece built here is one the Game Boy's sound hardware has. You end with a
two-voice melody made of square waves with the DMG's four duty cycles, its
sixteen volume levels, its volume envelope and its way of encoding pitch. Step
17B moves the same pieces into the core, clocked by the CPU instead of by a
sample counter.

---

## Map of step 17

Step 17 is four docs. Each ends with something you can hear.

| Doc | What it builds | You hear |
| --- | --- | --- |
| 17A | A square-wave synthesiser in `experiments/`, writing WAV files | A two-voice melody made of DMG parts |
| 17B | The APU registers, channel 2 and the frame sequencer, in the core | Tetris's lead voice, captured headless to a WAV |
| 17C | Channel 1 (sweep), channel 3 (wave), channel 4 (noise) and the mixer | All of Tetris's music in a WAV |
| 17D | Real-time output in the window: buffers, latency, keeping sound and frames in step | Tetris with sound |

17B starts with the address map of the sound registers, `0xFF10`–`0xFF3F`. This
doc does not touch memory.

---

## Theory

### 1. The path from a number to the speaker

```
   your script                     the OS and the hardware
   ───────────                     ───────────────────────
   sample 0:      0
   sample 1:   8000                ┌──────────┐   ┌─────┐   ┌─────────┐
   sample 2:   8000  ──► WAV ──►   │ sound    │──►│ DAC │──►│ speaker │
   ...                  file       │ card     │   └─────┘   └─────────┘
   sample 47999: -8000             └──────────┘
                                   48000 numbers   numbers     a voltage
                                   per second      to voltage  moves the cone
```

A speaker is a cone pushed back and forth by a voltage. The cone pushes the air,
and a pressure wave reaches your ear. The DAC (digital-to-analog converter)
turns each number into a voltage and holds it until the next one. So a list of
numbers, played at a fixed rate, becomes the cone's position over time.

The script's job is to produce that list. Everything else in the picture is
done by the operating system and the sound card.

### 2. What the ear hears

Three properties of the wave decide what you hear.

- **Frequency** is how many times per second the wave repeats, in hertz. It is
  the pitch. The A above middle C is 440 Hz. Doubling the frequency raises the
  note by an octave.
- **Amplitude** is how far the cone travels from rest. It is the loudness.
- **Shape** is the path the cone takes within one repetition. It is the timbre:
  a flute and a violin playing the same 440 Hz differ only in shape.

### 3. Sampling

The script cannot describe a continuous wave. It gives the cone's position at
regular instants, called samples. The number of samples per second is the
sample rate. This step uses 48000 Hz, the rate most sound cards run at
natively.

```
   amplitude
       ▲    ●  ●  ●  ●                    ●  ●  ●  ●
       │
     0 ┼──────────────────────────────────────────────────►  sample index
       │
       ▼                ●  ●  ●  ●  ●
            0  1  2  3  4  5  6  7  8 ...
            └─ 1 / 48000 s apart ─┘
```

Sample `i` describes the instant `t = i / 48000` seconds. That conversion is the
only link between the list and time.

A sample rate can describe frequencies up to half its value, 24000 Hz here. This
limit is called the Nyquist frequency. People hear up to about 20000 Hz, so
48000 covers all of it.

### 4. One sample, as a number

Each sample is a 16-bit signed integer, from -32768 to 32767. This is the
format of CD audio and of most WAV files.

- **0** is the cone at rest.
- **Positive** pushes it out and **negative** pulls it in.
- The **bit depth**, 16 here, is how finely the position can be set: 65536
  steps.

The wave should swing around 0. A wave that swings between 0 and 16000 has the
same shape as one that swings between -8000 and 8000, but it holds the cone
pushed out for as long as it plays. That constant part is called a DC offset.
You do not hear it, but you hear a click when it starts and stops, and it uses
up half of the room before the samples overflow.

Full scale, 32767, is loud on headphones. This step uses 8000 as the peak of one
voice.

### 5. A square wave

A square wave has two levels and jumps between them. It is the simplest wave to
generate, and it is the one the DMG's channels 1 and 2 produce.

```
   +8000 ┤  ┌──────────┐          ┌──────────┐
         │  │          │          │          │
       0 ┼──┼──────────┼──────────┼──────────┼──────►  time
         │  │          │          │          │
   -8000 ┤──┘          └──────────┘          └───────
            └──────── one period ─┘
              1 / frequency seconds
```

To fill sample `i`, you need to know where in its period the wave is at time
`t = i / 48000`. The number of periods that have passed by then is
`t × frequency`. The whole part counts finished periods. The fractional part,
from 0 up to 1, is the position inside the current one. That position is called
the **phase**.

```
   t × frequency = 3.27
                   │ └── phase: 27% of the way through period 4
                   └──── three periods finished
```

The phase decides the level. For a wave that is high for the first half of each
period, the level is high when the phase is below 0.5.

At 440 Hz one period lasts 48000 / 440 = 109.09 samples. That is not a whole
number, so some periods get 109 samples and some get 110. Computing the phase
from `i` each time keeps the average exact. Adding `440 / 48000` to a running
total sample after sample adds a little floating-point error each time, and the
error grows the longer it plays.

### 6. Duty cycle

The **duty cycle** is the fraction of a period the wave spends high. At 50% the
wave is symmetric. At 12.5% it is a short spike followed by a long low. The
pitch does not change, because the period does not change. The timbre does: 50%
sounds hollow, and 12.5% thin and nasal.

The DMG does not compute the phase as a fraction. It splits each period into 8
steps and reads one bit per step from a fixed pattern. It has four patterns.

```
   duty   pattern        step 0 1 2 3 4 5 6 7
   ────   ────────       ──────────────────────
    0     12.5%          _ _ _ _ _ _ _ ‾
    1     25%            ‾ _ _ _ _ _ _ ‾
    2     50%            ‾ _ _ _ _ ‾ ‾ ‾
    3     75%            _ ‾ ‾ ‾ ‾ ‾ ‾ _
```

So the level for sample `i` comes from two lookups. The phase, times 8, gives
the step from 0 to 7, and the pattern gives the bit at that step.

The 75% pattern is the 25% pattern upside down. The ear is not sensitive to a
wave being inverted, so the two sound the same. Task 2 lets you check that.

### 7. Volume and the envelope

Each DMG channel has a 4-bit volume, 0 to 15. A sample's value is its level (+1
or -1) times the peak, scaled by `volume / 15`.

A fixed volume sounds like an organ. Most notes in a game fade instead, and the
DMG does that with a **volume envelope**. It has three settings:

- the starting volume, 0 to 15
- a direction, down or up
- a pace, 0 to 7

The envelope ticks 64 times per second. Every `pace` ticks it moves the volume
one step in its direction, and it stops at 0 or at 15. Pace 0 means the volume
never changes.

At 48000 Hz one envelope tick is 48000 / 64 = 750 samples. A note that starts at
15 and goes down with pace 1 loses one step every 750 samples and reaches 0
after 15 × 750 = 11250 samples, 0.234 seconds. With pace 7 it takes seven times
as long, 1.64 seconds.

```
   volume
     15 ┤▀▀▀▀▄
        │     ▀▀▀▀▄
        │          ▀▀▀▀▄               one step every pace × 750 samples
        │               ▀▀▀▀▄
      0 ┼────────────────────▀▀▀▀▀▀▀▀▀▀▀►  samples
```

Starting a note again resets the volume to its starting value. On the DMG that
is called a **trigger**.

### 8. Pitch, the way the DMG writes it

A DMG game does not write a frequency in hertz. It writes an 11-bit number, from
0 to 2047, called the period value. The frequency is

```
   frequency = 131072 / (2048 - period value)
```

The pulse channel has a counter clocked at 1048576 Hz, a quarter of the CPU
clock. The counter starts at the period value and counts up. When it passes
2047, the channel moves one duty step and the counter restarts at the period
value. So one step lasts `2048 - period value` ticks, and one period, 8 steps,
lasts `8 × (2048 - period value)` ticks. 1048576 / 8 is 131072.

Pitch is coarse at the top of the range, because one unit of period value
covers more and more hertz.

| Note | Wanted | Period value | You get |
| --- | --- | --- | --- |
| C4 | 261.63 Hz | 1547 | 261.62 Hz |
| A4 | 440.00 Hz | 1750 | 439.84 Hz |
| C5 | 523.25 Hz | 1798 | 524.29 Hz |

Each period value is the integer closest to `2048 - 131072 / frequency`. Step
17B replaces the formula with the counter itself. Here the formula feeds the
phase calculation you already have.

### 9. Mixing

Two notes at once are two waves added together, sample by sample. Their sum
moves the cone the way both would. The DMG mixes its four channels this way.

The sum can go past 32767. Two voices at 8000 peak add up to at most 16000,
which fits. Two voices at full scale add up to 65534, which does not. A sample
outside the range cannot be stored. If you clamp it to 32767 instead, every
sample past the limit is cut to the limit. On a smooth wave that flattens its
top, and you hear a harsh distortion called clipping. A square wave is already
flat, so clamping changes less. Two square voices at the same volume sum to
three levels, and clamping keeps the same three levels at a smaller scale. With
different volumes, clamping changes how loud one voice is against the other.
Either way, the fix is to leave room: pick the peak of each voice so that the
sum of all of them still fits.

### 10. The WAV file

A WAV file is a 44-byte header followed by the samples, written one after
another in little-endian order. The header records three things: the number of
channels, the bytes per sample and the sample rate. The rest is the list from
section 1.

Python's standard library writes the header for you with the `wave` module.
One second of mono 16-bit sound at 48000 Hz is 48000 × 2 = 96000 bytes of
samples, so the file is 96044 bytes.

To play a file:

```
pw-play out.wav
```

`aplay`, `paplay` and `ffplay` also work. Start with the system volume low.

### 11. Python concepts this step introduces

- **`/` and `//`.** In Python `7 / 2` is `3.5` and `7 // 2` is `3`. In Ruby
  `7 / 2` is `3`. The phase calculation needs `/`, and anything used as a list
  index needs an `int`.
- **`array.array`.** A list of Python `int`s is a list of objects, 28 bytes or
  more each. `array("h", ...)` stores C `short`s, 2 bytes each, and checks the
  range: a value outside -32768..32767 raises `OverflowError`. `.tobytes()`
  gives the raw bytes in the machine's byte order. Ruby does this in one step
  with `samples.pack("s<*")`.
- **`with`.** `wave.open(path, "wb")` returns an object to be used inside a
  `with` block, which closes the file when the block ends, even after an
  exception. It is Ruby's `File.open(path) do |f| ... end`.
- **`sys.byteorder`.** It is `"little"` on x86 and on ARM as most systems run
  it, which is the order WAV needs. `array.tobytes()` uses the machine's order,
  so on a big-endian machine the samples would come out byte-swapped.

---

## Tasks

All the code goes in one script, `experiments/square_wave.py`, and grows task by
task. Write each piece as a function that takes plain numbers and returns
samples, and keep the file writing apart from it. That way you can check a
function's output in the REPL without listening to it.

### 1. A tone in a file

Write one second of a 440 Hz square wave with a 50% duty cycle, at 48000 Hz,
16-bit, mono, peak 8000, to a WAV file.

The script takes the output path as an argument, and `--frequency` and
`--seconds` as options with those defaults.

**Acceptance:** the file is 96044 bytes, and `wave.open` reports 1 channel, 2
bytes per sample, 48000 Hz and 48000 frames. It plays a steady tone with no
clicks in the middle.

---

### 2. The four duty cycles

Replace the "high when the phase is below 0.5" rule with the DMG's four 8-step
patterns from section 6. Add a `--duty` option from 0 to 3, defaulting to 2.

Write the four patterns as data, one tuple of eight levels per duty. Each level
is 0 or 1, as in the diagram.

**Acceptance:** `--duty 2` sounds the same as task 1. The samples are not
identical: the DMG's 50% pattern is high on steps 5 to 0, not 0 to 3, so the
wave starts at a different point of its period. Question 3 asks why that is
inaudible. Duty 0 sounds thinner than duty 2. Duty 1 and duty 3 sound the same.

---

### 3. Volume and the envelope

Add a 4-bit volume and the envelope from section 7, with options for the
starting volume, the direction and the pace. Defaults: volume 15, direction down,
pace 0, which gives the same tone as before.

The envelope counts in ticks of 750 samples. Work out the volume for each sample
from how many ticks have passed, or keep a counter as you go. Either works.

**Acceptance:** with volume 15, direction down, pace 1, every sample from index
11250 on is 0 and sample 11249 is not. With pace 7 the first silent sample is
78750. With direction up from volume 0, the tone fades in and then holds at 15.

---

### 4. Pitch as a period value

Write a function from an 11-bit period value to hertz, and a melody given as a
list of `(period value, length in samples)` notes. Each note is a trigger: its
envelope starts again from the starting volume.

Pick four notes of your own, or use C4, E4, G4, C5: period values 1547, 1650,
1714, 1798. Give each note the same length, about a quarter of a second, and an
envelope going down with pace 1 or 2.

**Acceptance:** period value 1750 gives 439.84 Hz. The melody plays as four
separate notes, each with its own attack.

---

### 5. Two voices

Play two melodies at the same time by adding their samples, as in section 9.

Then try what section 9 warns about. Set both peaks to 32767 and write the file.
Say what happens with `array("h")`, and decide whether the script should raise
or clamp. Keep the peaks at 8000 in the version you commit.

**Acceptance:** a file with two voices, both clearly audible. At full scale, the
script either raises `OverflowError` before writing or clamps. If it clamps, a
comment says what clamping does to two square voices.

---

### 6. Docs

Give the script a docstring like the other experiments: the question it answers,
how to run it, a sample run. Add its row to `experiments/README.md`.

---

## Hints

- If the tone is a click and then silence, every sample is the same value. The
  phase is always 0, which usually means it is computed with `//` somewhere.
- If the pitch is an octave too high or too low, the factor between the phase and
  the duty step is off by two.
- If you hear a click every second or so, the wave jumps at a joint. Look for
  phase computed from something that restarts, such as the index within one
  note, when the note did not restart.
- If the file plays at the wrong pitch and speed, the rate passed to
  `setframerate` is not the one the samples were made for.
- If the envelope never reaches 0, the tick length is wrong: it is 750 samples
  per tick, and `pace` ticks per volume step.
- If the file is twice as long as expected, or sounds like noise, check
  `setsampwidth(2)` and `setnchannels(1)`. The frame count is per channel.
- Pan Docs describes the DMG's pulse channels at
  <https://gbdev.io/pandocs/Audio_Registers.html>. Read it after this step: 17B
  starts from it.

---

## Acceptance criteria

- [ ] `experiments/square_wave.py` writes a 16-bit mono WAV at 48000 Hz
- [ ] One second at the defaults is 96044 bytes and plays a steady 440 Hz tone
- [ ] The four duties are data, one tuple each, taken from section 6
- [ ] The envelope reaches 0 at sample 11250 with volume 15, down, pace 1
- [ ] Period value 1750 gives 439.84 Hz
- [ ] A melody of at least four triggered notes, and a second voice mixed with it
- [ ] Full-scale mixing either raises or clamps, and the script says which
- [ ] Docstring and README row in place; `ruff check` and `ruff format --check`
      clean

---

## Questions to ask yourself before moving on

1. In this script, time is a sample index. In the emulator, time is CPU cycles.
   The emulator runs 4194304 cycles per second and the sound card wants 48000
   samples. How many cycles go by between two samples, and is it a whole
   number?
2. The phase calculation needs a frequency in hertz. The DMG has no hertz
   anywhere, only the counter from section 8. What would generating a sample
   look like if you kept that counter instead of the phase?
3. A note that starts at a random phase and one that starts at phase 0 sound the
   same. Why does it not matter where in its period a wave starts?
4. Your WAV file was written all at once, after every sample existed. A game
   decides its next note while it runs. What changes when the samples have to
   reach the sound card while the game is still running, and which side waits
   for which?
