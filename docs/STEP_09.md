# Step 09 — The timer, the divider, and the first interrupt that fires by itself

## Goal

Step 08 ended on a sentence that has been true ever since:

> After this step, nothing in your emulator will ever set a bit in `IF`.

This is the step where that stops being true.

Four registers join the map:

| Address | Name | What it is |
| --- | --- | --- |
| `0xFF04` | `DIV` | the divider. Free-running, never stops, cannot be turned off |
| `0xFF05` | `TIMA` | the timer counter. Counts at a rate you choose |
| `0xFF06` | `TMA` | the timer modulo. What `TIMA` reloads to when it overflows |
| `0xFF07` | `TAC` | the timer control. On/off, and which of four rates |

And one loop — the loop `PLAN.md` opened with, the reason every instruction has
been reporting a cycle count since Step 04:

```
while running:
    cycles = cpu.step()
    timer.tick(cycles)
```

Until now that number was summed and printed at the end of a trace. Nothing
*consumed* it. After this step it drives a device, and the device drives an
interrupt, and the interrupt reaches the dispatch you wrote last step without a
test having to fake it.

Three things become observable that were not before:

- `DIV` counting on its own, in a register the ROM never wrote
- a `HALT` that wakes up because time passed, which is what `HALT` is *for*
- Blargg's `instr_timing` ROM saying, in words, whether your cycle counts are
  right — because a 15-line serial stub turns the emulator into something that
  can report on itself

> **Visual companion:** the falling-edge detector draws well — the 16-bit
> counter as a row of bits, one of them tapped, the `AND` with the enable bit,
> and `TIMA` clocked off the falling edge. Ask if section 4 does not click; it
> is the one idea in this step that is genuinely easier as a picture.

---

## Theory

### 1. What "time" means in this emulator

Real hardware runs the CPU, the timer and the PPU in parallel off one 4.194304
MHz crystal. You are not going to do that. What you do instead is the bargain
`PLAN.md` described: run the CPU for exactly one instruction, ask how long that
took, and hand every other component that same number of cycles to catch up.

The consequence is that **the CPU's cycle count is the only clock in the
machine**. There is no wall clock, no `time.monotonic()`, nothing derived from
how fast Python runs. If `LD A, (HL)` reports 8 when it should report 12, the
timer runs slow by exactly that error, forever, and no amount of correct timer
code fixes it.

That is why Blargg's `instr_timing` exists, and why it is a *timer* test even
though what it checks is the CPU: the only way a ROM can measure how long an
instruction took is to look at a counter that advanced while it ran. You are
about to build the instrument that measures your own CPU.

An instruction gives you its cycles all at once — 4, 8, 12, 16, 20, 24. Inside
those cycles the real machine did things in a particular order: the timer ticked
between the memory accesses, not after them. Ignoring that is called
**instruction-stepped** emulation and it is what you are doing. It is wrong at
a granularity finer than one instruction, and right at every boundary between
two. Almost everything cares only about the boundaries.

### 2. The divider is not a counter of its own

The naive model of `DIV`: a byte that increments every 256 cycles.

The real thing: there is **one 16-bit counter** inside the chip, incremented
once per T-cycle, and `DIV` is a *window onto its top byte*.

```
internal counter:  15 14 13 12 11 10  9  8 | 7  6  5  4  3  2  1  0
                   └────── DIV reads these ──────┘
```

Increment the counter 256 times and bit 8 flips, which is `DIV` bit 0. So `DIV`
increments at 4194304 / 256 = **16384 Hz**, and nothing you can write makes it
stop.

Two facts follow from "`DIV` is a view, not a variable":

**Writing to `DIV` writes zero, whatever you wrote.** `LD A, 0x42` / `LDH
(0xFF04), A` sets `DIV` to `0x00`, not `0x42`. There is no register to store
`0x42` in. The write is a *reset line* on the counter that happens to be wired
to an address.

**Writing to `DIV` clears all sixteen bits, not just the top eight.** That
distinction looks academic and it is the whole of section 4.

`DIV` is also the machine's only free source of entropy. A game that wants a
random number and has no other clock reads `DIV` at the moment a button was
pressed. An emulator whose `DIV` always reads `0x00` makes those games
deterministic in a way the real console is not, and the symptom — "the pieces
always come in the same order" — looks nothing like a timer bug.

### 3. `TIMA`, `TMA`, `TAC`, and the four rates

`DIV` is free but fixed. `TIMA` is the programmable one:

- it counts up at one of four rates
- when it overflows past `0xFF`, it reloads from `TMA` and **requests the timer
  interrupt** — bit 2 of `IF`, vector `0x0050`, the one you wired last step
- `TAC` bit 2 turns it on and off; `TAC` bits 1-0 pick the rate

| `TAC` bits 1-0 | Rate | One tick every | Counter bit watched |
| --- | --- | --- | --- |
| `00` | 4096 Hz | 1024 T-cycles | 9 |
| `01` | 262144 Hz | 16 T-cycles | 3 |
| `10` | 65536 Hz | 64 T-cycles | 5 |
| `11` | 16384 Hz | 256 T-cycles | 7 |

Note the order: `01` is the *fastest*, and the table is not sorted. That is not
a documentation quirk, it is the encoding, and it is the first thing people get
wrong.

`TMA` is what makes the timer useful as a periodic tick. The interrupt fires
every `256 - TMA` counts, so `TMA = 0xFF` fires every single count and `TMA =
0x00` fires every 256. A game that wants an interrupt at some specific
frequency picks a rate with `TAC` and fine-tunes with `TMA`.

**Why the counter reloads from `TMA` instead of restarting at zero:** because
zero is one specific choice out of 256 and the hardware costs the same either
way. Restarting at zero is what you get by setting `TMA = 0`.

### 4. The one rule: a falling edge

Here is the part worth slowing down for. `TIMA` does not have its own counter,
and it does not have a "cycles since last tick" accumulator.

`TIMA` is incremented when a **single bit of the internal 16-bit counter, ANDed
with the `TAC` enable bit, goes from 1 to 0.**

```
        counter bit 9 (say) ──┐
                              ├── AND ──> falling edge? ──> TIMA += 1
        TAC bit 2 (enable) ───┘
```

That is the entire timer. One tap, one `AND` gate, one edge detector.

Convince yourself it produces the right rate. Bit 9 of a counter that increments
every T-cycle toggles every 2^9 = 512 T-cycles: up for 512, down for 512. It
*falls* once every 1024. Which is the `00` row of the table. Bit 3 toggles every
8 and falls every 16, which is the `01` row. The "watched bit" column and the
"one tick every" column are the same fact written twice.

Now the payoff. Every strange, much-blogged-about timer behaviour is a
consequence of this one rule, and you get all of them for free if you implement
the rule instead of the table:

**Writing `DIV` can increment `TIMA`.** The write clears all 16 bits. If the
watched bit happened to be 1 at that moment, it just became 0 — a falling edge —
and `TIMA` counts. A game that resets `DIV` in a tight loop can make its own
timer run at nearly double speed. (Mooneye's `rapid_toggle` test is exactly
this.)

**Changing `TAC`'s rate can increment `TIMA`.** Switching from bit 9 to bit 3
swaps which bit is watched. If bit 9 was 1 and bit 3 is 0, the `AND` output
falls, and `TIMA` counts, even though no time passed.

**Turning the timer *off* can increment `TIMA`.** Clearing the enable bit forces
the `AND` output to 0. If it was 1, that is a falling edge. Disabling a timer
ticks it one last time.

None of those are special cases in the hardware. They are special cases only in
an implementation that models "every N cycles, increment" instead of modelling
the gate. Write the gate.

The state this needs is one boolean: **what the `AND` output was last time you
looked.** Everything else is derived.

### 5. Ticking with a lumpy clock

`cpu.step()` hands you 4 to 24 cycles at once. The counter increments once per
cycle. So the obvious implementation is wrong:

```python
self.counter = (self.counter + cycles) & 0xFFFF  # then check the edge
```

Add 16 to a counter whose watched bit is bit 3 and the bit went 0 → 1 → 0 → 1 in
between. You sampled the ends and missed the transition.

The fix is to advance in steps small enough that no edge hides inside one. How
small? The fastest tap is bit 3, which toggles every 8 T-cycles, so a step of 8
would sample every stable interval at least once — but every instruction on this
CPU costs a multiple of 4, and 4 divides evenly into every rate. **Step by 4.**

```python
for _ in range(0, cycles, 4):
    ...advance 4, check the edge...
```

Four T-cycles is also the machine's real granularity: one M-cycle, the unit in
which the SM83 actually does anything. Stepping by 4 is not an approximation you
are getting away with, it is the correct grain.

*(A per-T-cycle loop would also be correct and four times slower, in a language
that is already slow. This is the one place in the project where the
accuracy/speed trade-off has an obviously right answer.)*

### 6. Overflow, and a delay you are not going to implement yet

The simple story: `TIMA` goes from `0xFF` to `0x00`, so it reloads from `TMA`
and sets `IF` bit 2.

The real story: for **4 T-cycles after the overflow, `TIMA` reads `0x00`** — not
`TMA` — and neither the reload nor the interrupt has happened yet. During that
window:

- writing to `TIMA` cancels the reload entirely and the interrupt never fires
- writing to `TMA` makes the reload use the *new* value

**Implement the simple version.** Reload and request in the same tick. Then write
a comment above it saying what is not modelled, in the same spirit as the `STOP`
comment you wrote last step.

Two reasons this is the honest call and not laziness. First, no ROM you will run
in the next five steps depends on it: Blargg's `cpu_instrs` and `instr_timing`
both pass without it; the tests that fail are Mooneye's `tima_reload` and
`tima_write_reloading`, which are the *acceptance-test suite for this exact
quirk*. Second, getting it right requires the timer to know about the CPU's
memory accesses within an instruction, which your instruction-stepped loop
structurally cannot express. Modelling it properly is a Step 16-and-later
project, and pretending otherwise with a hack would be worse than the comment.

Know that it exists. It is the reason a search for "gameboy timer" returns
arguments.

### 7. Where the timer lives, and who ticks it

A decision, and the first one in this project about *structure* rather than about
a register.

The timer needs two things that pull in opposite directions:

- the CPU must be able to read and write `0xFF04`-`0xFF07`, which means the
  **bus** has to route to it
- something must call `tick(cycles)` after every instruction, which means
  something that sees the **CPU's return value** has to hold it

Three shapes are available:

**(a) The bus owns it and grows a `tick`.** `Bus.__init__` creates a `Timer`;
reads and writes to the four addresses route to it like every other region; and
`Bus.tick(cycles)` forwards to it. The caller's loop is
`bus.tick(cpu.step())`.

**(b) A new `Machine` class owns cartridge, bus, CPU and timer**, and runs the
loop. The bus still needs a reference for routing, so the timer ends up
constructed by the machine and passed in.

**(c) The CPU owns it**, and `step()` ticks it before returning.

Take **(a)**. The argument for it is the sentence from `PLAN.md` that has been
load-bearing all along: *everything the CPU talks to is memory-mapped*. On real
hardware these devices literally hang off the bus. The routing has to be there
anyway, and the PPU in Step 11 and the joypad in Step 14 arrive the same way —
one more `case` in the `match`, one more line in `tick`.

The argument against (c) is stronger than it looks: `CPU` is typed against
`MemoryDevice`, a protocol with four methods, and the whole reason `cpu.py` and
`memory.py` do not import each other is that neither knows what the other
concretely is. A CPU that ticks a timer knows there is a timer. Keep the CPU
ignorant.

(b) is not wrong, it is early. A `Machine` class earns its place in Step 13,
when there is a frontend, a frame budget and a `run_frame()` that has to stop at
70224 cycles. Building it now gives you a class with one method that forwards to
another class.

**One consequence you should notice before you hit it:** `trace()` in
`__main__.py` takes `bus: MemoryDevice`, and `MemoryDevice` has no `tick`. The
protocol you wrote in Step 03 to describe "a thing the CPU can read and write"
now does not describe "a thing that also experiences time". You can widen the
protocol, define a second one, or type `trace()` against `Bus` concretely. All
three are defensible; pick one and be able to say why. This is what structural
typing feels like when the structure moves.

### 8. Who is allowed to write `IF`

The timer needs to set bit 2 of `0xFF0F`. `interrupts.py` currently has `pending`
— a pure function that takes a bus and reads. Its counterpart is the obvious
place for this:

```python
def request(bus: MemoryDevice, interrupt: Interrupt) -> None: ...
```

Read `IF`, set the bit, write it back. Two lines, and from here on it is *the*
way any device announces itself: the PPU calls it with `VBLANK` in Step 11, the
joypad with `JOYPAD` in Step 14.

Which raises the question of whether `Timer` should call it. It should not.
Keep `Timer` a leaf module with no package imports at all, in the same way `alu.py`
and `bits.py` are leaves: `tick` returns whether it overflowed, and the bus —
which already holds both — turns that into a `request`. A timer you can test with
no bus, no CPU and no interrupt table is a timer you will actually test.

```python
if self.timer.tick(cycles):
    interrupts.request(self, Interrupt.TIMER)
```

### 9. Unused bits read as 1, and the `IF` debt from last step

The Step 08 document said this and it is still not true in your code:

> The upper three bits of `IF` read as `1`, always.

`IF` lives at `0xFF0F`, which falls inside the generic `IO` bytearray, so
`bus.read(0xFF0F)` returns exactly what was last written. Nothing has cared yet
because nothing but your own tests ever wrote it. Now hardware writes it, and a
ROM that reads it back gets a byte with three bits wrong.

`TAC` has the same shape: only bits 2-0 exist, so it reads as `value | 0xF8`.

The general rule on this bus is that **an unwired bit reads as 1**, because the
data lines float high when nothing drives them. It is not a convention, it is
what happens when you don't connect a wire. You will meet it again on almost
every I/O register in Step 11 — `STAT`'s bit 7, `NR52`'s middle bits, the joypad's
top two.

Where the mask goes is a small decision with a real trade-off: masking on read
inside the device is local and obvious; masking in the bus's `read` keeps devices
storing exactly what they were given. Both work. Pick the one you would rather
debug at 1 a.m.

### 10. The state the boot ROM left behind

`Registers.post_boot()` exists because the DMG boot ROM runs for a while before
handing control to `0x0100`, and the register values at that moment are
documented. The same is true of the I/O registers:

| Register | Post-boot value |
| --- | --- |
| `DIV` | `0xAB` |
| `TIMA` | `0x00` |
| `TMA` | `0x00` |
| `TAC` | `0xF8` |

`DIV` is `0xAB` for a reason worth appreciating: the boot ROM took `0xABCC`
T-cycles to run, and `0xAB` is the top byte of that count. It is not a magic
constant, it is a stopwatch reading. Some emulators seed the internal counter to
`0xABCC` for exactly that reason, and that is the value to use, because setting
`DIV` to `0xAB` and the low byte to zero puts the falling-edge detector in a
slightly different place than the real machine.

`TAC = 0xF8` is `0x00` with the five unused bits reading high — the timer is
*off* after boot, which means a ROM that wants it must turn it on.

Give `Timer` a `post_boot()` classmethod, next to `Registers.post_boot()`.
Whether the bus constructs one by default, or the caller passes it in the way
`trace()` passes `Registers.post_boot()`, is a consistency question worth thirty
seconds of thought — you have one component doing it each way by the end of this
step unless you decide otherwise.

### 11. The serial port, and why 15 lines of it now

Two registers:

| Address | Name | What it is |
| --- | --- | --- |
| `0xFF01` | `SB` | serial transfer data — one byte in, one byte out |
| `0xFF02` | `SC` | serial control — bit 7 starts a transfer, bit 0 picks the clock |

A ROM sends a byte by writing it to `SB` and then writing `0x81` to `SC`: bit 7
"start", bit 0 "use my own clock". The hardware shifts eight bits out over the
link cable, clears bit 7 when it is done, and requests the serial interrupt.

**Every Blargg test ROM writes its results to the serial port**, character by
character, in addition to drawing them on a screen you do not have. That is the
whole reason this is in Step 09 and not later: your emulator has no display, and
a test suite that cannot tell you its verdict is not a test suite. Fifteen lines
buy you the ability to run the standard correctness suite for the next six steps.

The stub: on a write to `SC` with bit 7 set, take the byte in `SB`, hand it to
whoever is collecting output, and clear bit 7 immediately. That is a lie about
timing — a real transfer takes 8 × 512 = 4096 T-cycles — and it is the right lie,
because there is nothing on the other end of the cable to be slow.

Two honest limits to write into the comment:

- a real DMG with no cable attached clocks in `0xFF`, so `SB` should read `0xFF`
  after a transfer, not the byte you sent
- do **not** request the serial interrupt. Blargg's ROMs poll `SC` rather than
  waiting for it, and firing an interrupt for a transfer that took zero time is a
  bigger lie than the one you are already telling. If a ROM ever hangs waiting on
  a serial interrupt, this is the line to revisit, and the comment should say so.

Keep the collected output in the device as a `bytearray`, and let the CLI decide
whether to print it. Design constraint 1 from `PLAN.md`: no I/O inside
`gameboy/`. A device that calls `print()` is a device you cannot test.

### 12. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| A computed attribute over hidden state | `DIV` is a window on `counter`, not a field | `def div; @counter >> 8; end` |
| A property whose setter ignores its argument | writing `DIV` writes zero | `attr_writer` you override |
| A leaf module with no package imports | `Timer` needs no bus to be tested | same discipline |
| Stepping a loop by a constant | `range(0, cycles, 4)` | `0.step(cycles - 1, 4)` |
| A protocol that stops describing reality | `MemoryDevice` has no `tick` | duck typing, but the type checker notices |
| Returning a fact instead of causing an effect | `tick() -> bool` rather than writing `IF` | same |

---

## Tasks

### 1. `timer.py`, the state and the two views

A new leaf module. The state is smaller than the register list suggests:

```python
@dataclass(slots=True)
class Timer:
    counter: int = 0  # the internal 16-bit counter. DIV is its top byte
    tima: int = 0
    tma: int = 0
    tac: int = 0
    last_and: bool = False  # what the edge detector saw last
```

`DIV` is a property over `counter`. `TAC` reads with its unused bits set.

Add `post_boot()` per theory section 10, and put the four addresses in
`memory_map.py` with the rest of the map.

**Acceptance:** `Timer.post_boot().div == 0xAB`, and there is no `div` field
anywhere — grep for it and find only the property.

---

### 2. The four registers, read and write

| Address | Read | Write |
| --- | --- | --- |
| `0xFF04` | top byte of `counter` | `counter = 0`, **whatever the value** |
| `0xFF05` | `tima` | `tima` |
| `0xFF06` | `tma` | `tma` |
| `0xFF07` | `tac` with bits 7-3 set | `tac` |

Do not wire the falling-edge consequences of the `DIV` and `TAC` writes yet.
Task 3 builds the detector; task 4 routes the writes through it. Getting this
plumbing green first means task 4's failures are about edges and nothing else.

**Acceptance:** writing `0x42` to `0xFF04` and reading it back gives `0x00`.

---

### 3. `tick`, and the edge detector

Per theory sections 4 and 5.

```python
def tick(self, cycles: int) -> bool:
    """Advance the timer. Returns True if TIMA overflowed."""
```

For each 4-cycle step: advance `counter` (wrapping at 16 bits), compute the
`AND` of the watched bit and the enable bit, and if it fell from `True` to
`False`, increment `TIMA`. On overflow past `0xFF`, reload from `TMA` and record
that it happened.

The watched bit is a lookup from `TAC` bits 1-0 to `[9, 3, 5, 7]`. A tuple
indexed by `tac & 0b11` is clearer here than a `match`; this is a mapping, not a
branch.

An overflow returns `True` **once**, even if `tick` is called with enough cycles
for two — which cannot happen at these rates with a 24-cycle instruction, but say
so in the return type by returning `bool` rather than a count, and let the
assertion live in a test.

**Acceptance:** `TAC = 0b101` (enabled, 262144 Hz), `TIMA = 0`, then `tick(16)`
leaves `TIMA = 1`. Sixteen calls of `tick(1024)` with `TAC = 0b100` leave
`TIMA = 16`.

---

### 4. The three free quirks

Now route the writes from task 2 through the detector, per theory section 4:
writing `DIV`, and writing `TAC`, both change the `AND` output without any time
passing, and a fall is a fall.

The clean shape is one private method that sets the new counter or `TAC` value
and then runs the same edge check `tick` runs, so there is exactly one place in
the file that knows what an edge means.

**Acceptance:** with `TAC` enabled at 4096 Hz and the counter at `0x0200` (bit 9
set), writing anything to `0xFF04` increments `TIMA`. With the counter at
`0x0000`, it does not.

---

### 5. `interrupts.request`, and the bus wiring

Per theory sections 7 and 8:

- `request(bus, interrupt)` in `interrupts.py`, next to `pending`
- `Bus` constructs a `Timer`, routes the four addresses to it, and grows
  `tick(cycles)` that forwards and calls `request` on an overflow
- the `IF` and `TAC` unused-bit masks from theory section 9

Resolve the `MemoryDevice` question here rather than letting `# type: ignore`
resolve it for you.

**Acceptance:** a bus with `TAC` enabled, ticked enough times to overflow
`TIMA`, has bit 2 of `IF` set — read through `bus.read(0xFF0F)`, which now also
returns its top three bits set.

---

### 6. The serial stub

Per theory section 11. `serial.py`, `SB` and `SC`, output collected in a
`bytearray` the caller can read. Route `0xFF01` and `0xFF02` on the bus.

Write the comment about what is not modelled: the instant transfer, the `0xFF`
that a real unconnected port reads back, and the interrupt you are deliberately
not requesting.

**Acceptance:** writing `0x41` to `0xFF01` then `0x81` to `0xFF02` appends `A`
to the output, and reading `0xFF02` back has bit 7 clear.

---

### 7. The loop, in both places

`trace()` currently calls `cpu.step()` and throws the elapsed time at the
summary line. Now it ticks the machine with it.

Then add the CLI mode this step exists for. Tracing a Blargg ROM means millions
of lines nobody will read:

```
uv run python -m gameboy rom.gb --run 5000000
```

Runs without per-instruction output, prints whatever arrived on the serial port,
and ends with the same summary line `--trace` prints. The two modes must drive
*the same loop* — extract it if you have to, because two loops that tick
differently is a bug you will chase for an hour in Step 11.

**Acceptance:** `--trace 3` prints what it printed before this step, and its
summary cycle count is unchanged.

---

### 8. Tests

**Unit level, `Timer` alone, no bus:**

- `DIV` increments once per 256 cycles and wraps `0xFF` → `0x00`
- writing `DIV` zeroes it, and zeroes the low half too — assert through a
  behaviour, since the low half has no address: set the counter to `0x00FF`,
  write `DIV`, tick 4, and check that `DIV` did not immediately increment
- each of the four `TAC` rates produces the documented period. This is a table
  test: four rows, `(tac, cycles, expected_tima)`
- disabled `TAC` never increments `TIMA`, however many cycles pass
- overflow reloads from `TMA` and returns `True`, and the value is `TMA`, not `0`
- the three quirks from task 4, one test each

**Bus level:**

- the four addresses route to the timer, and `0xFF0F` bit 2 is set on overflow
- `TAC` and `IF` read their unused bits as 1

**Program level, and this is the one that matters:**

The first program in this project whose interrupt is not faked. Something like:

```
; at 0x0100:  LD A, 0xFF ; LDH (0xFF06), A   ; TMA = 0xFF, fire every tick
;             LD A, 0x05 ; LDH (0xFF07), A   ; TAC = enabled, 262144 Hz
;             LD A, 0x04 ; LDH (0xFFFF), A   ; IE = timer only
;             EI ; HALT
; at 0x0050:  INC B ; RETI
```

Step it in a bounded loop and assert that `B` incremented, that `PC` came back
past the `HALT`, and that `SP` is where it started. Nothing in the test writes
`0xFF0F`. That is the difference between this and every interrupt test you have
written so far.

**Acceptance:** that test fails if you comment out the `tick` call in the loop.
Check that it does — a timer test that passes with the timer unplugged is
testing your fixture.

---

### 9. Run the real thing

Two ROMs, in this order.

**Your game.** It has been spinning on `LY` at `0x0233` since Step 08. It still
will, because `LY` still does not move — but now check whether it reached that
loop through a timer interrupt on the way, and whether `DIV` reads non-zero when
you dump it. Report where it ends up and how the numbers changed.

**Blargg's `instr_timing`.** From
<https://github.com/retrio/gb-test-roms>, `instr_timing/instr_timing.gb`.

```
uv run python -m gameboy instr_timing.gb --run 5000000
```

It prints its own name, then either `Passed` or a numbered failure. Expect a
failure the first time; that is the point of running it. A failure means at
least one entry in your `OPCODES` table disagrees with hardware about its cycle
count, and the fix is a careful pass over the table against
<https://gbdev.io/gb-opcodes/optables/> — start with the conditionals and the
`(HL)` forms, which are where the counting rule is easiest to get wrong.

If it hangs with no output at all, the problem is upstream of timing: the ROM
never got far enough to write a character, and the trace of the first few
thousand instructions will say why.

---

### 10. Docs

`README.md`'s step table, and its closing paragraph — "Interrupts work, but
nothing raises one" stops being true, and the `--run` mode wants a line with
example output.

`PLAN.md`'s Step 09 row promises Blargg's timer ROMs. Note in the row, or in
Step 10's, where `cpu_instrs` actually lands now that serial arrived early.

---

## Hints

- If `TIMA` runs at exactly half or exactly double the rate you expect, you are
  counting both edges, or counting the rising one. The rate table and the bit
  table only agree on the *falling* edge.
- If `TIMA` never increments, print `TAC`. `0x04` is enabled-at-4096Hz and `0x05`
  is enabled-at-262144Hz, and a `TAC` of `0x00` or `0x01` is a timer that is
  switched off — the enable bit is bit 2, not bit 0.
- If the timer interrupt fires once and never again, the handler is not clearing
  `IF` and neither is the dispatch — except the dispatch does clear it, so look
  instead at whether `TIMA` is stuck at `0x00` because your overflow reloads zero
  rather than `TMA`.
- If a `HALT` never wakes, tick the timer *outside* the CPU. A halted `step()`
  returns 4 and fetches nothing; if your loop only ticks when an instruction
  executed, a halted machine freezes time and waits forever for a counter that
  cannot advance.
- If `instr_timing` fails, suspect the conditionals first. `cycles_when_taken`
  exists precisely for those, and an instruction that reports its taken cost when
  it was not taken is invisible to every unit test that only checks registers.
- `range(0, cycles, 4)` iterates `cycles // 4` times. If you write
  `range(cycles // 4)` you get the same count; if you write `range(cycles)` your
  timer runs four times fast and every ROM behaves as if it were on a CGB in
  double-speed mode.
- Cross-check every number in this document against
  <https://gbdev.io/pandocs/Timer_and_Divider_Registers.html> before writing it
  down. The `TAC` encoding order is the one people copy wrong.

---

## Acceptance criteria

- [ ] `DIV` is a view over a 16-bit counter, and no `div` field exists
- [ ] Writing any value to `0xFF04` produces `DIV == 0x00`
- [ ] All four `TAC` rates produce the documented period, asserted as a table
- [ ] `TIMA` increments on a falling edge, and the three quirks in task 4 follow
      from that rule without a special case in the code
- [ ] Overflow reloads `TMA` and sets `IF` bit 2 through `interrupts.request`
- [ ] `Timer` imports nothing from the package and is tested without a bus
- [ ] `TAC` reads its unused bits as 1; so does `IF`
- [ ] `Timer.post_boot()` matches the table in theory section 10
- [ ] The serial stub collects bytes and does not print, and a comment states
      what it does not model
- [ ] `--trace` and `--run` drive one loop, and `--trace 3` is byte-identical to
      before this step
- [ ] A program-level test drives an interrupt end to end without writing `IF`
- [ ] `instr_timing.gb` produces readable output on the serial port, and either
      passes or fails for a reason you can name
- [ ] No test runs an unbounded loop
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. The hardware taps a bit of the divider instead of giving `TIMA` its own
   counter. What does that save in gates, and what does it force on a programmer
   who wants to change the timer rate mid-frame?
2. You stepped the timer in units of 4. What is the largest step that is still
   correct today, and what would the answer be if `TAC` could select bit 0?
3. `Timer.tick` returns a `bool` instead of writing `IF` itself. Step 11's PPU
   raises two different interrupts under conditions the timer never has. Does
   the same shape still work, and what would it return?
4. Your serial port transmits instantly. Describe a ROM that would break on it,
   and say whether you think any real game does that.
5. Before this step, `pending()` was called on every `step()` and always returned
   `None`. Which line of your Step 08 dispatch has now executed outside a test
   for the first time — and if it had been wrong, would any test you wrote last
   step have caught it?
