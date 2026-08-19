# Step 06 — Jumps, calls and the stack

## Goal

Give the CPU control flow. Until now a program is a straight line: `step()`
advances `PC` by the length of whatever it just ran, forever. After this step the
CPU can go somewhere else, and — the part that matters — it can go somewhere else
*and come back*.

Roughly 40 opcodes. They are the last big structural piece of the CPU: after this
the only things missing are the CB-prefixed bit operations (Step 07) and the
interrupt machinery (Step 08), and the interrupt machinery is built entirely out
of what you write today.

Concretely, on Tetris, the `0x20` that stopped you at `0x0216` is `JR NZ, e8`
jumping back to `0x0214`, and the three instructions

```
0214  32  LD (HL-), A
0215  05  DEC B
0216  20  JR NZ, -3     -> 0214
```

become a loop that clears memory downwards. `B` starts at `0x00`, so `DEC B` runs
256 times before `Z` is set; `C` starts at `0x10`, and there is an outer loop
around this one that decrements it. 16 × 256 = 4096 iterations before the ROM
moves on to anything new. Your trace goes from nine lines to thousands, and that
is the observable result of this step.

> **Visual companion:** the stack draws well — a column of memory with `SP`
> walking down it through a `CALL` and back up through a `RET`. Ask if the
> push/pop ordering does not click from the text.

---

## Theory

### 1. Three ways to change `PC`, and why there are three

Every instruction in this step ends by writing `PC`. They differ in where the new
value comes from and what they do on the way.

| Family | New `PC` comes from | Remembers where it was |
| --- | --- | --- |
| `JR` | current `PC` plus a signed 8-bit offset | no |
| `JP` | a 16-bit immediate, or `HL` | no |
| `CALL` / `RST` | a 16-bit immediate, or a fixed address | **yes, on the stack** |
| `RET` | the stack | — |

`JP` and `JR` do the same job, and `JR` exists purely as an optimisation: one
operand byte instead of two, and 12 cycles instead of 16. Most jumps in real code
are short — a loop back a few instructions, an `if` skipping a few — so the
8-bit form is what a compiler or a careful assembly programmer reaches for first.
This is the same economy as `LDH` versus `LD (a16), A` in Step 05: a smaller
address space that covers the common case.

`CALL` and `RET` are the pair that makes subroutines possible, and the whole
mechanism is one idea: **before jumping, write down where you were.** The place
it writes to is the stack.

### 2. The stack is a convention, not a structure

The SM83 has no stack memory, no stack segment and no bounds. It has `SP`, a
16-bit register, and four instructions that agree on how to use it:

- **Push**: subtract 2 from `SP`, then write a 16-bit value at the new `SP`.
- **Pop**: read a 16-bit value at `SP`, then add 2 to `SP`.

That is the entire specification. `SP` points at the *last thing pushed*, the
stack **grows downwards**, and the two operations are exact mirror images.

Two consequences worth internalising, because both produce bugs that look like
hardware faults:

**Nothing checks anything.** Push more than you pop and `SP` walks down through
HRAM, through the I/O registers, through OAM, and starts overwriting video
memory. There is no fault, no trap, no error — the game just corrupts its own
graphics. `RET` with no matching `CALL` pops whatever two bytes happen to be at
`SP` and jumps there. Your emulator must reproduce this faithfully, which
conveniently means: do not add checks. A `ValueError` here would be *less*
accurate, not more.

**Downwards is a layout decision.** `SP` is initialised to `0xFFFE`, the top of
HRAM, and grows down towards the code and data that live at low addresses. The
stack and the heap growing towards each other from opposite ends of memory is the
same arrangement you know from every process on your machine, and it is here for
the same reason: neither region has to know how big the other will get.

**Order within the pair.** A push writes the high byte at the higher address and
the low byte at the lower address, which is exactly little-endian layout, which
is exactly what `Bus.write16` already does. So:

```
push:  SP = SP - 2 ; write16(SP, value)
pop:   value = read16(SP) ; SP = SP + 2
```

In Step 05 the document argued for not widening the `MemoryDevice` protocol
beyond `read`/`write`. You widened it anyway, to get `write16` for
`LD (a16), SP`. That call pays off here: push and pop are two lines each, and
their mirror-image property is guaranteed by the bus rather than by two
instruction bodies independently agreeing on byte order. It is worth noticing
*why* it pays off — the protocol got wider, but the number of places that know
about endianness stayed at one.

### 3. Signed offsets, and why your `PC` is already in the right place

`JR` takes one operand byte, `e8`, interpreted as **two's complement signed**:
`0x00`–`0x7F` are 0 to +127, `0x80`–`0xFF` are −128 to −1. So `0xFC` is −4 and
`0xFE` is −2.

The question that trips everyone: relative to *what*?

The offset is relative to the address of the instruction **after** the `JR`. And
because of the decision you made in Step 04 — `fetch_u8` advances `PC` before the
instruction body runs — by the time a `JR` body has fetched its operand, `PC`
already holds that address. So the body is:

```
offset = to_signed8(fetch_u8())
PC = u16(PC + offset)
```

with no correction term. Worked example, the Tetris loop from the goal section:
the `JR` is at `0x0216`, its operand at `0x0217`, so after the fetch `PC` is
`0x0218`. Operand `0xFC` is −4. `0x0218 − 4 = 0x0214`, the `LD (HL-), A`. Correct,
with no adjustment.

If you had chosen "advance `PC` after execution", every jump in this step would
carry a `+1` or `+2` fudge factor and one of them would be wrong. This is the
second time that decision has paid off (`CALL` in section 5 is the third), and it
is worth writing down as the general lesson: **the cheapest bugs are the ones a
representation makes unspellable.**

**The Python mechanics.** Three ways to turn `0xFC` into `−4`:

```python
value - 0x100 if value & 0x80 else value  # arithmetic
int.from_bytes(bytes([value]), signed=True)  # stdlib, honest about what it is
struct.unpack("b", bytes([value]))[0]  # the C-ish one
```

You already took the first, back in Step 01: `bits.to_signed8`. It is one
expression, it needs no allocation, and `bits.py` is the module whose entire job
is "what does this byte mean". Ruby's equivalent is
`[value].pack("C").unpack1("c")`, which is worse than all three.

Note the asymmetry in `bits.py`: `u8` and `u16` answer "how does this value fit
in n bits", `to_signed8` answers "how is this byte to be read". Both are width
questions, so both belong there. What matters is that no instruction body
contains `- 0x100`.

### 4. Conditions are a two-bit field, and four families share it

Four flavours of conditional exist, and all four encode the condition in bits 4
and 3:

| `cc` | Mnemonic | Test |
| --- | --- | --- |
| `00` | `NZ` | `Z` is clear |
| `01` | `Z` | `Z` is set |
| `10` | `NC` | `C` is clear |
| `11` | `C` | `C` is set |

Only `Z` and `C` can be branched on. `N` and `H` exist for `DAA` and nothing
else, exactly as Step 05's flag table said.

The four families:

| Pattern | Family | Opcodes |
| --- | --- | --- |
| `001 cc 000` | `JR cc, e8` | `0x20` `0x28` `0x30` `0x38` |
| `110 cc 010` | `JP cc, a16` | `0xC2` `0xCA` `0xD2` `0xDA` |
| `110 cc 100` | `CALL cc, a16` | `0xC4` `0xCC` `0xD4` `0xDC` |
| `110 cc 000` | `RET cc` | `0xC0` `0xC8` `0xD0` `0xD8` |

Sixteen opcodes, four bodies, one condition test. This is the same shape as the
`_PAIR_FAMILIES` table you refactored the 16-bit block into: a tuple of
(base opcode, name template, cycles, maker) and one loop over it. Reuse that
shape rather than inventing a second one — a reader who has understood one
generator in `cpu.py` should not have to understand a different mechanism to
read the next.

**The trap in this whole section**, and it is the single most common bug of this
step:

> The operand is fetched whether or not the branch is taken.

`JP NZ, 0x1234` with `Z` set does not jump — but it still consumed three bytes,
and `PC` must end up past both operand bytes. A body written as

```python
if not condition(cpu):
    return  # <- PC is now pointing at 0x34, which is not an opcode
address = cpu.fetch_u16()
```

decodes garbage on the very next step. Fetch first, test second. On real hardware
this is not a rule anyone had to decide: the bytes go past the CPU either way.

### 5. `CALL` and `RET`, and the free return address

`CALL a16` is:

```
address = fetch_u16()
push(PC)          # PC now points just past the CALL instruction
PC = address
```

`RET` is `PC = pop()`.

Look at the middle line again. The return address is not computed. Nothing adds a
length to anything. `PC` already holds the address of the next instruction,
because the operand fetch moved it there — the same property that made `JR` free
of fudge factors. `CALL` is three lines and none of them is arithmetic.

The mental model to carry forward: **the CPU has no concept of a function.** It
has a `PC` and a stack discipline. "Subroutine", "call frame", "return address"
are names we give to a convention that the hardware only supports and never
enforces. This is why buffer overflows that overwrite a return address work at
all, on this machine and on every machine since — the return address lives in
writable memory next to the data.

`RETI` (`0xD9`) is `RET` plus "re-enable interrupts". It is deferred to Step 08,
along with `HALT` (`0x76`), `DI` (`0xF3`) and `EI` (`0xFB`), because all four
manipulate the interrupt master enable flag, which does not exist yet. A ROM that
reaches one of them raises `UnknownOpcodeError`, which is correct: your emulator
genuinely cannot model what happens next. Do not stub them to `NOP` — a `DI` that
silently does nothing is a bug that hides until Step 08 and then looks like an
interrupt bug.

### 6. `RST`: eight one-byte calls

`RST` is `CALL` to one of eight fixed addresses, encoded `11 ttt 111`:

| Opcode | Target | Opcode | Target |
| --- | --- | --- | --- |
| `0xC7` | `0x0000` | `0xE7` | `0x0020` |
| `0xCF` | `0x0008` | `0xEF` | `0x0028` |
| `0xD7` | `0x0010` | `0xF7` | `0x0030` |
| `0xDF` | `0x0018` | `0xFF` | `0x0038` |

Target is `ttt × 8`. One byte instead of three, so a routine called from hundreds
of places costs a third of the ROM space — which is why cartridge code puts its
hottest helpers in the first 64 bytes of the address space, and why the first
page of a ROM is usually a table of eight jumps rather than real code.

Do not confuse the `RST` targets (`0x00`–`0x38`) with the interrupt vectors
(`0x40`, `0x48`, `0x50`, `0x58`, `0x60`) from Step 08. They are different tables
that happen to live near each other, and both are entered by a push-and-jump.

`0xFF` being `RST 0x38` has a practical consequence you will meet: reading
unmapped memory returns `0xFF`, so a CPU that jumps into empty space executes
`RST 0x38` repeatedly, pushing two bytes each time, until the stack eats
everything. A trace that turns into an endless `RST 38` is not a bug in `RST`; it
is the evidence that a jump went somewhere wrong several instructions earlier.

### 7. `PUSH` and `POP`, and the field that changed meaning

`PUSH rr` is `11 pp 0101`, `POP rr` is `11 pp 0001`:

| Opcodes | Instruction | Cycles |
| --- | --- | --- |
| `0xC5` `0xD5` `0xE5` `0xF5` | `PUSH BC/DE/HL/AF` | 16 |
| `0xC1` `0xD1` `0xE1` `0xF1` | `POP BC/DE/HL/AF` | 12 |

Same two-bit pair index, in the same bit positions as the 16-bit arithmetic block
from Step 05 — with one difference:

> `pp = 0b11` means **`AF`** here, and `SP` there.

Which is obvious once stated and invisible when you are reusing an enum. Your
`RegisterPair` names `0b11` as `SP`, so it is wrong for this block. Two honest
options: a second `IntEnum` (`StackPair`, with `AF` at `0b11`), or a four-element
tuple local to the stack block. Prefer the enum, for symmetry with what is
already there and because `repr` naming the member is what makes a wrong table
entry visible.

The reason the hardware does this: `SP` is meaningless to push (`PUSH SP` would
push a value that the push itself just changed), and `AF` is essential — saving
and restoring the flags across a subroutine call is what makes subroutines usable
at all.

**The `POP AF` trap.** `F`'s low four bits do not exist in hardware; they read as
zero always. So `POP AF` of the value `0x1234` must leave `F` at `0x30`, not
`0x34`. Blargg's `cpu_instrs` has a test for exactly this.

Your `f` setter already reads only bits 7 to 4, and your `f` getter builds the
byte from four booleans, so both directions discard the low nibble and you get
this for free. That is not luck: it follows from having stored the flags as four
booleans rather than as a byte. Write the test anyway — the point of a test here
is to notice if someone later "optimises" `F` into an integer field.

### 8. `SP` arithmetic, and the strangest flags in the instruction set

| Opcode | Instruction | Cycles | Flags |
| --- | --- | --- | --- |
| `0xF9` | `LD SP, HL` | 8 | none |
| `0xE8` | `ADD SP, e8` | 16 | `Z=0`, `N=0`, `H` and `C` from the low byte |
| `0xF8` | `LD HL, SP+e8` | 12 | `Z=0`, `N=0`, `H` and `C` from the low byte |

`0xE8` and `0xF8` are the same arithmetic; one writes `SP`, the other writes `HL`
and leaves `SP` alone. Together they are how a program allocates and addresses
local variables: move `SP` down to make room, then use `LD HL, SP+n` to point at
a slot.

Their flags are genuinely odd and worth stating precisely, because every emulator
gets this wrong once:

- `Z` is **always cleared**, even when the result is zero. It is not a result
  flag here.
- `N` is always cleared.
- `H` and `C` are computed from the **unsigned low byte** of `SP` plus the
  **unsigned** operand byte, exactly as if this were an 8-bit `ADD`:

```
H = (SP & 0x0F) + (e & 0x0F) > 0x0F
C = (SP & 0xFF) + (e & 0xFF) > 0xFF
```

with `e` as the raw byte, *not* the sign-extended value. The address arithmetic
is signed and 16-bit; the flag arithmetic is unsigned and 8-bit. They disagree on
purpose: the flags describe the byte-level carry out of the low half, which is
what the hardware adder actually produced.

Note also that this is **not** `add16`. `ADD HL, rr` computes its half-carry at
bit 11; these two compute it at bit 3. Do not reach for the function you already
have — write the flag rule where it belongs and let the two stay separate.

### 9. Cycle counts are now conditional, and the table has to say so

Step 05 ended with the question: you have 180 instructions with a fixed `cycles`
field, and conditional jumps take one count when taken and another when not. What
is the smallest change that admits them?

The numbers, first:

| Instruction | Not taken | Taken |
| --- | --- | --- |
| `JR cc, e8` | 8 | 12 |
| `JP cc, a16` | 12 | 16 |
| `CALL cc, a16` | 12 | 24 |
| `RET cc` | 8 | 20 |

And the unconditional ones: `JR` 12, `JP a16` 16, `JP HL` 4, `CALL` 24, `RET` 16,
`RST` 16.

One observation before choosing a shape. Step 05's "4 T-cycles per memory
access" law still holds, but it stops being the *whole* story here, because these
instructions do work that touches no memory. `POP` is fetch plus two reads and
costs exactly 12, as the law predicts. `PUSH` makes the same three accesses and
costs 16: the extra machine cycle is the 16-bit decrement of `SP`. `CALL` makes
five accesses and costs 24, for the same reason. And `RET cc` costs 20 taken
against `RET`'s 16 with identical accesses — that one is the condition test
itself.

So the general rule is *machine cycles = memory accesses + internal cycles*, and
`count_cycles` from Step 05 only knows the first term. Do not extend it. These
numbers are written by hand from the table above, the way the 16-bit block was.

Now the shape. Three candidates:

| Shape | Taken cost lives in | Cost |
| --- | --- | --- |
| A. Body returns the total cycle count, or `None` for "use the table" | the instruction body | timing split across two places |
| B. Body returns `True` when it branched; table gains a second count | the table | one extra field, `None` by default |
| C. `cycles` becomes a callable taking the CPU | the table, as code | every entry pays for four entries' problem |

Prefer **B**:

```python
@dataclass(frozen=True, slots=True)
class Instruction:
    name: str
    cycles: int  # the not-taken cost
    execute: Callable[["CPU"], bool | None]
    cycles_when_taken: int | None = None
```

Three properties make it the cheap one:

1. **All 180 existing entries keep working untouched.** The new field has a
   default and goes last, so every positional `Instruction(name, cycles, body)`
   still constructs.
2. **All 180 existing bodies keep their `-> None` signature.** A function typed
   `-> None` satisfies `Callable[[CPU], bool | None]` — return types are
   covariant, `None` is a subtype of `bool | None`, and mypy accepts it with no
   changes anywhere. Verify that yourself before writing forty instructions on
   the assumption; it is a two-line file and `uv run mypy` answers in a second.
3. **Both timings stay declarative**, next to the mnemonic, where a test can
   assert them without executing anything.

`step()` then decides:

```python
taken = instruction.execute(self)
if taken and instruction.cycles_when_taken is not None:
    return instruction.cycles_when_taken
return instruction.cycles
```

The `is not None` is not defensive noise — it is what makes a body that wrongly
returns `True` degrade into a wrong cycle count rather than a `TypeError` three
components away in Step 09.

Ruby note: `bool | None` as a return type reads oddly if you are used to methods
that just return truthy or `nil`. The distinction is doing real work here — `None`
means "I am not a branch and have no opinion", `False` means "I am a branch and I
did not take it" — and both take the same path today only because the not-taken
cost is the default.

### 10. Your emulator can now run forever

This is the first step after which a bug does not raise, it *hangs*. `JR -2`
(`0x18 0xFE`) jumps to itself: two bytes of a legitimate, extremely common idiom
that ROMs use to wait. The boot ROM ends in one. Your trace loop is bounded by
`--trace N`, so the CLI is safe by construction — but your **tests** are not, and
`while True: cpu.step()` in a test is a hung pytest run with no output.

The rule to adopt now, before you need it: every test that runs a program runs it
a bounded number of steps.

```python
for _ in range(100):
    cpu.step()
```

not `while cpu.registers.pc != 0x0200`. If a jump is wrong, a bounded loop fails
an assertion and an unbounded one hangs CI in Step 10.

### 11. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| Return-type covariance in `Callable` | `-> None` bodies satisfy `-> bool \| None` | duck typing, unchecked |
| Two's complement conversion | `to_signed8` for `JR` offsets | `pack`/`unpack` |
| A second `IntEnum` over the same bit field | `StackPair` vs `RegisterPair` | two frozen hashes |
| Dataclass field defaults and ordering | adding `cycles_when_taken` without touching 180 entries | keyword args with defaults |
| Bounded iteration in tests | `for _ in range(n)` over `while` | same, but nobody enforces it |

---

## Tasks

### 1. `bits.to_signed8` — already done in Step 01

`to_signed8` exists and its four boundary cases are already covered:
`0x00 -> 0`, `0x7F -> 127`, `0x80 -> -128`, `0xFF -> -1`. Nothing to write.

Two additions worth the two lines, both about `JR` rather than about the
function:

- `to_signed8(0xFC) == -4`. The four existing cases prove the sign boundary; this
  one is the value you will actually meet, in the Tetris loop and in most
  backward jumps.
- The property that makes `JR` need no correction term:
  `u16(0x0218 + to_signed8(0xFC)) == 0x0214`. Assert it once. It is the claim
  every jump in this step rests on, and it is the only place in the suite where
  `bits` and the jump arithmetic are checked together.

**Acceptance:** `bits.py` still imports nothing. (It does. Step 01 got this
right and nothing since has been tempted to break it.)

---

### 2. The stack primitives

Two methods on `CPU`, next to `fetch_u8`/`fetch_u16`:

```python
def push16(self, value: int) -> None: ...
def pop16(self) -> int: ...
```

Per theory section 2: push subtracts 2 then writes, pop reads then adds 2, both
wrapping `SP` with `u16`.

Do these before any instruction that uses them, and test them directly:

- push then pop returns the same value and leaves `SP` where it started
- pushing `0x1234` at `SP = 0xFFFE` writes `0x34` at `0xFFFC` and `0x12` at
  `0xFFFD` — assert the individual bytes, not just the round trip, or a
  consistently byte-swapped pair passes both directions
- two pushes and two pops come back in reverse order

**Acceptance:** the round-trip test does not construct a single `Instruction`.

---

### 3. `Condition` and the condition test

An `IntEnum` with the four members from theory section 4, and:

```python
def condition_met(cpu: CPU, condition: Condition) -> bool: ...
```

A `match`, for the same reason Step 05's operand accessors use one: exhaustive,
and mypy checks it.

---

### 4. The variable cycle count

Widen `Instruction` and `step()` per theory section 9, **before** writing any
conditional instruction. Two things to verify immediately after:

- `uv run mypy` is clean with zero changes to existing instruction bodies
- `uv run pytest` is green with zero changes to existing tests

If either is false, the shape is wrong and it is much cheaper to find that out
now than after forty entries.

---

### 5. Jumps

| Opcodes | Instruction | Cycles |
| --- | --- | --- |
| `0x18` | `JR e8` | 12 |
| `0x20` `0x28` `0x30` `0x38` | `JR cc, e8` | 12 / 8 |
| `0xC3` | `JP a16` | 16 (already in the table) |
| `0xC2` `0xCA` `0xD2` `0xDA` | `JP cc, a16` | 16 / 12 |
| `0xE9` | `JP HL` | 4 |

Generate the two conditional families from the patterns in theory section 4.

`JP HL` deserves a sentence. Many opcode tables print it as `JP (HL)`, and that
mnemonic is a lie: it does not read memory. It sets `PC` to the *value* of `HL`.
The 4-cycle cost is the proof — one fetch, no access. Name it `JP HL` in your
table. It exists because it is how you implement a jump table: compute an index
into `HL`, then `JP HL`.

**Acceptance:** a `JR` with a negative offset lands on the right address; a
not-taken `JP cc` leaves `PC` past both operand bytes.

---

### 6. `CALL`, `RET`, `RST`

| Opcodes | Instruction | Cycles |
| --- | --- | --- |
| `0xCD` | `CALL a16` | 24 |
| `0xC4` `0xCC` `0xD4` `0xDC` | `CALL cc, a16` | 24 / 12 |
| `0xC9` | `RET` | 16 |
| `0xC0` `0xC8` `0xD0` `0xD8` | `RET cc` | 20 / 8 |
| `0xC7` … `0xFF` | `RST 0x00` … `0x38` | 16 |

`RST` generates from `11 ttt 111` with target `ttt × 8`. Name them with the
target in hex — `RST 0x38`, not `RST 7` — because the trace is what you will read
when a ROM falls into `0xFF` territory and you need to recognise it instantly.

`RETI` is deliberately absent; see theory section 5.

---

### 7. `PUSH` and `POP`

Per theory section 7, including the `StackPair` enum where `0b11` is `AF`.

**Acceptance:** `POP AF` with `0x1234` on the stack leaves `A = 0x12` and
`F = 0x30`, and `PUSH AF` / `POP AF` round-trips the flags exactly.

---

### 8. `SP` arithmetic

`0xF9`, `0xE8`, `0xF8`, with the flag rule from theory section 8. The flag
computation is shared by `0xE8` and `0xF8`, so it is one helper — and since it is
pure arithmetic over integers, it belongs in `alu.py` with the rest, not in
`cpu.py`.

**Acceptance:** `ADD SP, e8` with `SP = 0x000F` and `e8 = 0x01` sets `H` and
clears `Z`; with `SP = 0x00FF` and `e8 = 0x01` sets both `H` and `C`; with
`SP = 0xFFFF` and `e8 = 0x01` the result is `0x0000` and `Z` is still **clear**.

---

### 9. Tests

The new thing this step can test, which no previous step could: **programs that
do something over time.**

**Unit level, in `tests/test_cpu.py`:**

- the four conditions, each tested both ways: with the flag set and clear
- a not-taken conditional consumes its operand bytes (the section 4 trap) —
  assert on `PC`, not on the jump target
- cycle counts: `step()` returns 12 for a taken `JR NZ` and 8 for a not-taken one
- generation sanity, as in Step 05: a couple of specific opcodes decode to the
  right condition, and two entries from the same generated family behave
  differently, which is the minimum that catches a closure capture bug

**Program level, the payoff tests:**

A loop that terminates:

```python
# LD B, 3 ; (loop) DEC B ; JR NZ, -3 ; ...
cpu = cpu_running(0x06, 0x03, 0x05, 0x20, 0xFD)
```

Step it a bounded number of times and assert `B` reached `0x00` and `PC` is past
the `JR`. Count the steps it took and assert that too — the count is the proof
the loop ran three times rather than once or forever.

A subroutine:

```python
# CALL 0x0110 ; (at 0x0110) INC A ; RET
```

Assert `A` changed, `PC` came back to the instruction after the `CALL`, and `SP`
is exactly where it started. That last assertion is the one that catches an
off-by-two in push/pop, and it is worth making after *every* program test from
now on: **a balanced program leaves `SP` untouched.**

Nested calls, two deep, for the same reason a single one is not enough: one level
of `CALL`/`RET` passes even if push and pop are both wrong in the same direction.

---

### 10. Run a real ROM

`--trace 40` now shows the clear loop turning instead of stopping at `0x0216`.
Read it once, line by line, and confirm `HL` walks down by one per iteration and
`B` down by one per iteration.

Then find where it stops now:

```
uv run python -m gameboy rom.gb --trace 100000 | tail -20
```

It will stop on an opcode from Step 07 or Step 08 — the CB prefix, or `DI`, or
`HALT`. Whichever it is, that is the correct outcome and worth reporting when you
ping me: which opcode, at which address, after how many instructions.

Two small CLI additions that pay for themselves immediately:

- When the trace stops, print a summary line: instructions executed, total
  cycles, and why it stopped. Cycles are the clock for Steps 09 onwards and you
  are already summing them one step at a time.
- `NAME_WIDTH` needs to be 12 now (`LD HL, SP+e8` and `CALL NZ, a16` are both 12
  characters). The comment above it names the current widest mnemonic; keep it
  accurate.

A one-liner worth keeping for the rest of the project — the loop shape, without
reading 4096 lines:

```
uv run python -m gameboy rom.gb --trace 5000 | awk '{print $1}' | uniq -c | head -30
```

Consecutive runs of the same address collapse into a count, so a loop shows up as
a short repeating block of addresses instead of a wall of text.

---

## Hints

- If a jump lands two bytes short, the operand fetch happened after the jump
  rather than before. If it lands one byte short, `PC` was read before the
  operand fetch instead of after. Both are one-line fixes and they look
  identical in a trace, so check the body rather than staring at addresses.
- `u16(pc + offset)` needs no special case for a negative offset. Python's `&`
  on a negative integer operates on its two's-complement representation, which is
  infinite to the left, so masking a negative gives the right positive. Same fact
  as `bits.u8(-1) == 0xFF` from Step 05.
- A `RET` that jumps to `0x0000` almost always means `pop16` read from the wrong
  side of `SP`, not that the ROM did something clever.
- If the trace turns into an endless `RST 0x38`, the jump that went wrong is
  several instructions *earlier* than where you are looking. Trace, find the last
  line whose address makes sense, and dump around it.
- `cpu_running` writes its program at `0x0100` in flat memory, and `Registers()`
  starts `SP` at `0`. A push from there wraps `SP` to `0xFFFE`, which is
  legitimate — but if you would rather test against realistic values, set
  `cpu.registers.sp = 0xFFFE` in the test. Consider whether the fixture should do
  it for you, and whether that would hide anything.
- Cross-check every cycle count in this document against
  <https://gbdev.io/gb-opcodes/optables/> before you write it. The conditional
  ones are listed as `12/8` style pairs, taken first.
- When you find yourself writing the third `CALL` variant by hand, stop and go
  back to the family table.

---

## Acceptance criteria

- [ ] `uv run python -m gameboy rom.gb --trace 40` shows the clear loop turning,
      with `HL` decreasing by one per iteration.
- [ ] The same ROM with a large `--trace` stops on a Step 07 or Step 08 opcode,
      not on anything from this step.
- [ ] A not-taken conditional jump leaves `PC` past all of its operand bytes.
- [ ] `step()` returns 12 for a taken `JR NZ, e8` and 8 for a not-taken one.
- [ ] A `CALL`/`RET` pair leaves `SP` exactly where it started, and so does a
      two-deep nesting of them.
- [ ] `POP AF` leaves the low nibble of `F` clear.
- [ ] `ADD SP, e8` clears `Z` even when the result is `0x0000`, and computes `H`
      and `C` at bits 3 and 7 rather than 11 and 15.
- [ ] `JP HL` costs 4 cycles and reads no memory.
- [ ] `RETI`, `HALT`, `DI` and `EI` are still absent from the table.
- [ ] No test runs an unbounded loop.
- [ ] `alu.py` still imports nothing from `cpu.py`.
- [ ] `uv run pytest` is green, `uv run ruff check .`,
      `uv run ruff format --check .` and `uv run mypy` are clean.

---

## Questions to ask yourself before moving on

1. `CALL` never computes a return address. Which decision from Step 04 made that
   true, and what would the three `CALL` bodies look like if that decision had
   gone the other way?
2. Your emulator can now hang. What is the smallest change that would let you
   tell "stuck in `JR -2`" from "making progress" without reading the trace?
3. `RET` with no matching `CALL` jumps somewhere arbitrary and your emulator
   allows it. Name one thing that would break if you added a check, and say
   whether the check would have caught any bug you have actually had.
4. `RegisterPair` says `0b11` is `SP` and `StackPair` says it is `AF`. Is having
   two enums over the same two bits a duplication worth removing, or is it the
   encoding telling you they are two different fields that happen to share a
   position?
5. Step 08's interrupt dispatch is a `CALL` that no instruction asked for: the
   hardware pushes `PC` and jumps to a vector. Which of the functions you wrote
   today will it reuse unchanged, and which will it need a variant of?
