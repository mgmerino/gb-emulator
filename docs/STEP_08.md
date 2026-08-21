# Step 08 — Interrupts, `HALT` and the master flag

## Goal

Five opcodes and one mechanism that no opcode asks for.

`OPCODES` currently holds 239 entries. After this step it holds **244**, and the
accounting closes for good:

```
244 entries + 0xCB + 11 illegal = 256
```

There is nothing else. Every byte in the base table is either an instruction you
implemented or a value that locks a real Game Boy solid.

The five that join:

| Opcode | Instruction | Cycles |
| --- | --- | --- |
| `0xF3` | `DI` | 4 |
| `0xFB` | `EI` | 4 |
| `0xD9` | `RETI` | 16 |
| `0x76` | `HALT` | 4 |
| `0x10` | `STOP` | 4 |

And the mechanism: when something outside the CPU wants attention, the hardware
**inserts a `CALL` that the program never wrote**. It pushes `PC` and jumps to a
fixed address, in the middle of whatever was running.

Concretely, Tetris stops today at `0xF3` after 12328 instructions. `DI` is the
first thing it does once its memory is cleared — disable interrupts, then
configure hardware in peace. After this step it walks past that line and keeps
going.

> **Visual companion:** the dispatch draws well — `IF` and `IE` as two rows of
> five bits, the AND between them, `IME` as a gate on the result, and an arrow
> into the vector table. Ask if the three-way condition does not click.

---

## Theory

### 1. An interrupt is a `CALL` nobody wrote

The CPU is executing a program. Meanwhile the screen finishes drawing a frame,
or a timer overflows, or somebody presses a button. The program needs to react.

The naive answer is polling: check a flag every so often, in a loop. That works
and it is what your emulator does today for nothing at all, because nothing can
signal it yet. The problems are that polling costs cycles even when nothing
happened, and that the response time depends on where in the loop you were.

The hardware answer: the peripheral sets a bit. Between two instructions, the
CPU notices, and pushes `PC` and jumps to a fixed address without any
instruction telling it to. The handler runs, does its work, and executes `RETI`,
which pops the address back and resumes where the interrupted code was.

You already built that mechanism in Step 06. `push16` and `pop16` are both reused
unchanged, and `RETI` is `_ret` with one extra line. Those two functions are what
the last question in the Step 06 document was pointing at.

The stack discipline you wrote for subroutines is what makes interrupts possible
at all. A handler can run between any two instructions because "where I was" is a
value that lives in memory rather than in the CPU.

### 2. Three pieces of state, and only one of them is a register

| Name | What it is | Where it lives |
| --- | --- | --- |
| `IME` | Interrupt Master Enable | inside the CPU. Not addressable, not readable |
| `IE` | Interrupt Enable | `0xFFFF`, one bit per source |
| `IF` | Interrupt Flag | `0xFF0F`, one bit per source |

An interrupt is serviced when **all three** agree:

```
IME is set   AND   (IE & IF & 0x1F) != 0
```

`IF` means *"this happened"*. The hardware sets those bits. `IE` means *"I care
about this"*. The program sets those bits. `IME` is the program saying *"not
right now"* to all five at once.

**`IME` is not a flag register bit and not a memory address.** There is no
instruction that reads it. `DI`, `EI` and `RETI` write it and nothing can observe
it directly, which is why a program that wants to disable interrupts *and know
whether they were enabled* has to track that itself. In your code it is a plain
`bool` on the CPU.

**`IE` and `IF` are just memory**, so the program manipulates them with the
instructions you already have. And this is where Step 07 pays off: a handler that
wants to acknowledge only the VBlank interrupt writes

```
LD   HL, 0xFF0F
RES  0, (HL)
```

Every ROM you disassemble from here on is full of `BIT`, `RES` and `SET` against
`0xFF0F` and `0xFFFF`. Those 192 opcodes were not an academic exercise; they are
how this machine talks to itself.

Your bus already stores `IE` in a dedicated field, and `IF` at `0xFF0F` falls
inside the generic `IO` array. Whether `IF` deserves a named home of its own is a
small decision this step will make you take.

**The upper three bits of `IF` read as `1`, always.** Only five interrupts exist, so bits 5 to 7 are not wired to anything, and
an unwired bit on this bus reads high. A program that does `LD A, (0xFF0F)` sees
`0xE0` when nothing is pending, not `0x00`. Blargg checks this.

### 3. Five sources, five vectors, and a priority order

| Bit | Source | Vector | Fires when |
| --- | --- | --- | --- |
| 0 | VBlank | `0x0040` | the PPU finishes a frame |
| 1 | LCD STAT | `0x0048` | a configurable PPU condition |
| 2 | Timer | `0x0050` | the timer counter overflows |
| 3 | Serial | `0x0058` | a link-cable transfer completes |
| 4 | Joypad | `0x0060` | a button goes down |

The vector is `0x40 + bit * 8`. Eight bytes per handler, which is not much — in
practice the vector holds a `JP` to the real code, exactly like the `RST` page.

That arithmetic is the same shape as `RST`'s `ttt * 8`, and the two tables sit
near each other in memory. They are unrelated. `RST` targets run `0x00`–`0x38`
and are reached by an instruction; interrupt vectors run `0x40`–`0x60` and are
reached by the hardware. The Step 06 document flagged this and it is worth
re-reading the two tables side by side once.

**Priority is by bit number, lowest first.** If VBlank and Timer are both pending
and both enabled, VBlank wins. Only **one** interrupt is dispatched at a time;
the other stays pending in `IF` and is serviced after the handler returns.

So "find the interrupt to service" is: mask `IE & IF & 0x1F`, and take the
lowest set bit. There is a neat bit trick for that (`value & -value` isolates the
lowest set bit) and there is a loop over `range(5)`. Take the loop — you need the
index, not the mask, and five iterations of an obvious loop beat a clever
expression that needs a comment.

### 4. The dispatch, step by step

When the condition holds, between two instructions:

1. **`IME` is cleared**, and not saved anywhere. The handler runs with
   interrupts off unless it re-enables them itself.
2. **The source's bit in `IF` is cleared.** This is the acknowledgement. If the
   handler does not want to be re-entered for the same reason it does not have
   to do anything — the hardware already did it.
3. **`PC` is pushed**, exactly as `CALL` pushes it.
4. **`PC` is set to the vector.**

Total: **20 T-cycles.** Two internal machine cycles, two for the push, one to
load `PC`. Nothing is fetched and no instruction executes, so a dispatch is a
`step()` that costs 20 and runs nothing.

Clearing `IME` has three consequences:

- a handler cannot be interrupted unless it says so, so it does not need to be
  re-entrant
- a handler that never re-enables interrupts silently kills every interrupt in
  the machine from then on, and the symptom is "the game freezes after a while"
  rather than a crash
- `RETI` exists because "return and re-enable" is the overwhelmingly common
  ending, and doing it as `EI` then `RET` costs an extra byte and an extra
  instruction in a routine that runs sixty times a second

### 5. Where the check goes, and why it is before the fetch

`step()` today fetches, decodes, executes, returns a cycle count. The dispatch
has to happen **between** instructions, which in practice means at the top of
`step()`, before the fetch:

```
if halted: ...
if an interrupt is pending and IME: dispatch, return 20
opcode = fetch_u8()
...
```

An interrupt serviced after the fetch but before execution would push
a `PC` that points into the middle of an instruction, and the `RETI` would return
to an operand byte. That is the same class of bug as the Step 06 trap where a
not-taken conditional forgot to consume its operand, and it produces the same
symptom: garbage decoded as if it were code.

`step()` had one job until now. It gains three exits: dispatched an interrupt,
executed an instruction, or was halted and did nothing. All three return a cycle
count, because the only thing the caller needs to know is how much time passed.

**`step()` reports elapsed time rather than "an instruction ran".** Step 09's
timer and Step 11's PPU are driven by that number and do not care which of the
three happened.

### 6. `EI` is late by exactly one instruction

The trap of this step, and deliberate hardware behaviour.

`EI` does not set `IME` immediately. It sets it **after the instruction that
follows `EI` has executed**. `DI` is immediate. `RETI` is immediate.

The reason is the pattern it exists to protect:

```
EI
RET
```

If `EI` took effect at once, an interrupt could fire *between* `EI` and `RET`,
pushing a return address and running a handler while the current handler is still
on the stack. Repeat that a few times and the stack walks down through HRAM. The
one-instruction delay guarantees the `RET` executes first.

Model it with a flag that `EI` sets and `step()` promotes to `IME` at the *end*
of the following instruction. Getting that ordering right is the hard part:

```
pending_before = self.ime_pending      # captured before executing
... execute the instruction ...        # EI sets ime_pending here
if pending_before:
    self.ime = True
    self.ime_pending = False
```

Run `EI` through it. During `EI`'s own step, `pending_before` is `False`, so
nothing is promoted, and `EI` sets `ime_pending`. During the *next* instruction's
step, `pending_before` is `True`, and `IME` comes on after that instruction
finishes. Correct, and it needs no counter.

Skip it and you write `EI` as a direct assignment to `IME`. Nothing fails
immediately, and then a ROM that uses the `EI`/`RET` idiom corrupts its own stack
after a few thousand interrupts.

### 7. `HALT`, and the three cases

`HALT` stops the CPU until something happens. It exists to save power: the Game
Boy runs off batteries, and a game that has finished its work for this frame should
not spin in a loop until the next VBlank. The idiomatic main loop is *do the
frame's work, then `HALT` until the VBlank interrupt wakes you.*

While halted the CPU fetches nothing, but everything else keeps running: the
timer counts, the PPU draws. So a halted step still has to return a cycle count,
or time stops for the whole machine and Step 09 never advances.

Three cases, and they differ in what wakes the CPU and what happens next:

| `IME` | `IE & IF` at the moment of `HALT` | Behaviour |
| --- | --- | --- |
| 1 | anything | halt; when a bit becomes pending, wake **and dispatch** |
| 0 | zero | halt; when a bit becomes pending, wake and **do not dispatch** |
| 0 | non-zero | **does not halt at all** — see section 8 |

In the middle case, with `IME` clear, the interrupt cannot be serviced but can
still *wake* the CPU. So `HALT` with interrupts
disabled is "sleep until something happens, then carry on with the next
instruction" — a way to wait without spending cycles and without giving up
control.

### 8. The `HALT` bug

The famous one, and Blargg's `cpu_instrs` tests it directly.

If `HALT` executes while `IME` is clear **and** an interrupt is already pending
(`IE & IF & 0x1F` is non-zero), the CPU does not halt. Instead:

> The byte after the `HALT` is fetched twice. `PC` fails to increment on that
> fetch.

So a one-byte instruction sitting after `HALT` executes **twice**. If a
multi-byte instruction sits there, its opcode is read, then read again as if it
were a fresh instruction, and the decode goes sideways from there.

Nobody defends this as a design decision; it is a hardware race that shipped.
Real games work around it, which means real games *depend* on the workaround, so
an emulator that "fixes" the bug can break a ROM that avoids it.

Your emulator must reproduce it. Concretely, that means a piece of CPU state that
says "the next fetch does not advance `PC`", set when the bug condition is met and
consumed by the following fetch.

Do not implement this before the rest of the step works. It is the last thing,
and it is easier to reason about once `HALT`'s normal cases are solid.

### 9. `STOP`, and being honest about what is not modelled

`0x10` is `STOP`, and it is two bytes: `0x10` followed by a byte that is
conventionally `0x00` and is otherwise ignored. That second byte exists because
of a hardware quirk in how the instruction was decoded, not because it means
anything.

On a DMG, `STOP` halts the CPU **and the LCD** until a button is pressed. On a
CGB it doubles as the speed-switch instruction. Its exact behaviour depends on
the joypad register, on whether interrupts are pending, and on a handful of
edge cases that are genuinely hard to get right.

**What to implement:** consume both bytes, treat it as `HALT`, and leave a
comment saying what is not modelled. The stub gets the byte count and the cycle
count right, which is as much as it can honestly claim.

Even that much is worth having. A ROM that reaches `STOP` and raises
`UnknownOpcodeError` tells you nothing, while one that keeps going tells you the
ROM expected to sleep here. Most games never execute it; the
ones that do usually use it for a real pause.

### 10. Nothing fires yet, and how to test anyway

Read the "fires when" column of section 3 again. VBlank needs the PPU, which is
Step 11. Timer needs the timer, which is Step 09. Serial and joypad need hardware
that does not exist.

**So after this step, nothing in your emulator will ever set a bit in `IF`.**

The mechanism has to exist before the things that use it, so that is the plan
working rather than a gap. It does change how you test. The dispatch cannot
be observed by running a ROM and waiting — it has to be triggered by writing `IF`
yourself:

```python
cpu.bus.write(0xFF0F, 0x01)  # pretend the PPU finished a frame
cpu.bus.write(0xFFFF, 0x01)  # and that the program cares
cpu.ime = True
```

Then one `step()` should dispatch: `PC` at `0x0040`, the old `PC` on the stack,
`IF` bit 0 cleared, `IME` clear, 20 cycles returned.

Every part of the mechanism is reachable from a unit test with three writes and
no timing, which is a much better place to get it right than inside a running PPU
in Step 11.

### 11. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| State that is not a register | `ime`, `halted` on `CPU`, not `Registers` | plain attributes |
| A function with several exits returning one meaning | `step()` returns elapsed time three ways | same |
| Deferred effect across calls | `EI`'s one-instruction delay | an instance flag |
| Isolating the lowest set bit | interrupt priority | `value & -value`, same trick |
| Deliberately reproducing a bug | the `HALT` bug | — |

---

## Tasks

### 1. The new state, and where it lives

Three pieces:

```python
ime: bool  # the master flag
ime_pending: bool  # EI fired, promote after the next instruction
halted: bool  # HALT is in effect
```

**The decision:** `Registers` or `CPU`?

`Registers` models the programmer-visible register file — the things `AF`, `BC`,
`DE`, `HL`, `SP` and `PC` name, plus the four flags that live in `F`. None of
these three is addressable, none appears in `F`, and none has a post-boot value
the hardware manual lists alongside the registers.

Prefer `CPU`. `Registers` stays the thing a trace line prints.

`CPU` is a plain `@dataclass` with two required fields today, so the new ones
need defaults and go last.

**Acceptance:** `Registers.post_boot()` is unchanged, and `trace_line` still
compiles without knowing any of this exists.

---

### 2. `DI`, `EI`, `RETI`

| Opcode | Effect | Cycles |
| --- | --- | --- |
| `0xF3` | `IME = 0`, immediately | 4 |
| `0xFB` | `IME = 1` **after the next instruction** | 4 |
| `0xD9` | `PC = pop()`, `IME = 1` immediately | 16 |

`RETI` reuses `pop16` untouched, and is `_ret` plus one line.

Per theory section 6, `EI` sets the pending flag and `step()` promotes it. Write
the promotion in `step()` in the same commit as `EI`, not later — an `EI` that
sets `IME` directly passes every test you would think to write.

**Acceptance:** after `EI`, `IME` is still clear at the end of that `step()`, and
set at the end of the next one.

---

### 3. The interrupt table

Five sources. An `IntEnum` whose value is the bit index gives you the vector by
arithmetic and the name for free in a trace:

```python
class Interrupt(IntEnum):
    VBLANK = 0
    LCD_STAT = 1
    TIMER = 2
    SERIAL = 3
    JOYPAD = 4

    @property
    def vector(self) -> int: ...
```

Same shape as `Operand.assembly_name`. Put the two addresses in `memory_map.py`
with the rest of the map — `IF` at `0xFF0F` currently has no name, and `IE`
already does.

Then the pending check: mask `IE & IF & 0x1F`, return the lowest set bit as an
`Interrupt`, or `None`. That function is pure, takes a bus, and is worth testing
on its own before anything dispatches.

**Acceptance:** with `IE = 0x1F` and `IF = 0x14`, the answer is `TIMER`, not
`JOYPAD`.

---

### 4. The dispatch

Per theory section 4, in `step()`, before the fetch.

Clear `IME`, clear the source's `IF` bit, push `PC`, jump to the vector, return
20.

**Acceptance:** a `step()` that dispatches executes no instruction. Assert that
`A` is untouched and that the byte at the old `PC` was never decoded.

---

### 5. `HALT`, normal cases

`0x76`, 4 cycles. Sets `halted`.

`step()` gains its third exit: if halted, return 4 without fetching. Waking is
the same condition as dispatching minus `IME` — `IE & IF & 0x1F` non-zero — and
whether the interrupt is then *serviced* depends on `IME`, per the table in
section 7.

**Acceptance:** a halted CPU stepped a hundred times leaves `PC` where it was and
returns 4 each time; writing a byte into `IF` wakes it on the next step.

---

### 6. The `HALT` bug

Per theory section 8, and last.

State that says "the next fetch does not advance `PC`", set when `HALT` runs with
`IME` clear and something already pending.

**Acceptance:** the program `HALT` / `INC A` with `IME = 0`, `IE = 0x01`,
`IF = 0x01` and `A = 0` leaves `A = 2` after enough steps, and `PC` past the
`INC A` exactly once.

---

### 7. `STOP`

`0x10`, two bytes, 4 cycles. Consume the operand byte. Behave as `HALT`.

Write the comment from theory section 9 above it: what is not modelled, and why
that is acceptable today.

---

### 8. Tests

**Unit level:**

- the pending check, including the priority case from task 3
- each of `DI`, `EI`, `RETI` on `IME`, with `EI`'s delay asserted across two steps
- a dispatch, asserting all five effects: `PC`, the stack, `IF`, `IME`, 20 cycles
- a dispatch does not happen when `IME` is clear, when `IE` is clear, or when
  `IF` is clear — three separate tests, because one `and` with three terms fails
  three different ways
- the vector of each of the five sources
- `HALT`'s three cases from the section 7 table
- the `HALT` bug

**Program level:**

The payoff test. It is the first program in this project that gets interrupted:

```
; at 0x0100:  EI ; LD A, 1 ; LD A, 2 ; ...
; at 0x0040:  INC B ; RETI
```

Set `IE` and `IF` by hand, step, and assert the handler ran, `B` changed, the
main program resumed at the right instruction, and `SP` came back to where it
started. That last one is the same assertion every program test has made since
Step 06, and here it is checking hardware rather than code.

Bounded loops, as always — a halted CPU with nothing pending never wakes.

---

### 9. Run a real ROM

```
uv run python -m gameboy rom.gb --trace 200000 | tail -20
```

Tetris stops at `0xF3` today after 12328 instructions. It will now execute that
`DI` and keep going. Report where it gets to, how many instructions and how many
cycles — and expect it to end up somewhere it waits forever, because the thing
it is waiting for is the PPU.

A trace that turns into an endless `HALT`, or an endless `JR -2`, is the correct
outcome. It means the ROM has finished setting up and is waiting for a VBlank
that will not arrive until Step 11.

The loop-shape one-liner is the fastest way to see it:

```
uv run python -m gameboy rom.gb --trace 200000 | awk '{print $1}' | uniq -c | tail -20
```

---

### 10. Docs

`README.md`'s step table, and the sentence about the instruction set being
complete except for five opcodes — which stops being true here.

---

## Hints

- If `EI` seems to work, check it with two instructions after it rather than one.
  The wrong implementation and the right one agree on everything except the exact
  instruction boundary where `IME` turns on.
- If a dispatch returns to the wrong place, print `SP` before and after. A
  dispatch pushes two bytes and the matching `RETI` pops two; anything else means
  the push happened at the wrong point in `step()`.
- If the CPU dispatches forever into the same vector, the handler is not clearing
  `IF` and neither are you. Step 4 says the hardware clears the bit on dispatch —
  if you skipped that, the condition is still true on the next step.
- `IF`'s upper three bits read as `1`. If a test compares a whole byte read from
  `0xFF0F` against `0x01`, it will fail for a reason that has nothing to do with
  interrupts.
- A halted CPU in an unbounded test loop is a hung pytest run with no output.
  Same rule as Step 06: `for _ in range(n)`.
- Cross-check the cycle counts against <https://gbdev.io/pandocs/Interrupts.html>
  before writing them. The 20 for a dispatch is the one people guess wrong.

---

## Acceptance criteria

- [ ] `len(OPCODES) == 244`, and `244 + 1 + 11 == 256` still holds as a test
- [ ] `EI` leaves `IME` clear for exactly one more instruction; `DI` and `RETI`
      are immediate
- [ ] A dispatch clears `IME`, clears one `IF` bit, pushes `PC`, jumps to the
      vector and costs 20 — asserted separately
- [ ] With two interrupts pending, the lower bit number wins and the other stays
      set in `IF`
- [ ] `HALT`'s three cases behave per the section 7 table
- [ ] The `HALT` bug executes the following byte twice
- [ ] `STOP` consumes two bytes
- [ ] `step()` returns a cycle count on all three of its exits
- [ ] A handler runs, `RETI` returns, and `SP` ends where it started
- [ ] No test runs an unbounded loop
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. The dispatch pushes `PC` using the same `push16` a `CALL` uses. What would
   have had to be different about `push16` for that reuse *not* to work, and does
   that tell you anything about where else the stack discipline shows up?
2. `IME` is cleared on dispatch and nothing saves it. A handler that runs `EI`
   early can be interrupted by itself. Is that a bug in the hardware, a feature,
   or a thing the programmer is expected to not do — and how would you find out?
3. Your `step()` now has three exits and all three return a cycle count. Name the
   component in Step 09 that would break if one of them returned zero, and say
   what the symptom would look like.
4. You implemented a hardware bug on purpose. What is the test that would tell
   you a future refactor had accidentally fixed it?
5. Nothing sets `IF` yet. When Step 09's timer does, which of the tests you wrote
   today will still be testing something, and which were really testing your own
   test setup?
