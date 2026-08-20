# Step 07 — CB-prefixed opcodes: rotates, shifts and bit operations

## Goal

Finish the instruction set.

Right now `OPCODES` holds 235 entries. After this step it holds 240, plus a
second table of 256. The five that join the base table are `0x07`, `0x0F`,
`0x17`, `0x1F` — the four accumulator rotates Step 05 deliberately postponed —
and `0xCB`, which is not an instruction at all but a door into the other table.

The accounting afterwards is worth writing down, because it is the first time
this project can state exactly what is left:

| Opcodes | Count | Status after this step |
| --- | --- | --- |
| Base table, implemented | 240 | done |
| CB table | 256 | done |
| `0x10` `0x76` `0xD9` `0xF3` `0xFB` | 5 | Step 08 (`STOP`, `HALT`, `RETI`, `DI`, `EI`) |
| `0xD3` `0xDB` `0xDD` `0xE3` `0xE4` `0xEB` `0xEC` `0xED` `0xF4` `0xFC` `0xFD` | 11 | illegal, no instruction exists |

240 + 5 + 11 = 256. There is nothing else. Every remaining `UnknownOpcodeError`
after today is either a Step 08 opcode or a jump that went somewhere wrong, and
knowing which of the two you are looking at is most of the debugging you will do
in Step 10.

It is also the first step whose block cannot be written out by hand. Step 06's
40 instructions were, and that was the right call — the tests are green and the
cycle counts are right. 256 is a different regime, not because it is tedious but
because nobody audits 256 functions by reading them, so a generator becomes the
only form in which the block can be checked at all. Theory section 2 draws that
line explicitly, and says where Step 06 falls on it.

> **Visual companion:** the eight rotate and shift operations animate well — one
> byte, the carry bit beside it, and the bits walking. Ask if the difference
> between `RLC` and `RL` does not land from the diagrams below.

---

## Theory

### 1. A prefix byte is an escape character

An opcode is one byte. One byte is 256 values. The SM83's base table uses 245 of
them and leaves 11 unused, so there is no room for the 256 bit operations the
designers also wanted.

The way out is the same trick every instruction set has reached for: pick one
byte and declare that it means *"the opcode is in the next byte, read from a
different table."* On the SM83 that byte is `0xCB`. On the Z80 it inherited from
there are four such bytes (`CB`, `DD`, `ED`, `FD`); on x86 it is `0F`; in UTF-8
it is the high bit of a lead byte. The mechanism is a prefix code, and the design
question is always the same one: which operations are common enough to deserve a
one-byte encoding, and which can afford to pay for two.

The cost is exact and it is not an abstraction. A prefixed instruction performs
**two opcode fetches**, so it costs 4 T-cycles more than the same work would in
the base table. That single fact explains the whole shape of this step:

- `RLC A` is a CB opcode (`0xCB 0x07`) and costs 8 cycles.
- `RLCA` is a base opcode (`0x07`) and costs 4.

They do almost the same thing. The base table spent one of its precious slots on
a duplicate because rotating the accumulator is what you do in the inner loop of
a multiplication routine, and the inner loop is where 4 cycles are worth a slot.
Section 4 is about the "almost".

**What this means for `step()`.** The decode becomes two-stage:

```
opcode = fetch_u8()
if opcode == 0xCB:
    opcode = fetch_u8()
    look it up in CB_OPCODES
else:
    look it up in OPCODES
```

Two shapes are available and only one is cheap:

| Shape | How | Problem |
| --- | --- | --- |
| A. `step()` special-cases `0xCB` | four lines choosing a table before the lookup | none |
| B. `0xCB` is an `Instruction` whose body fetches and dispatches | fits the existing table | the body has to report the *total* cycles, and bodies return `bool \| None` |

Prefer **A**. B looks tidier — one more entry, no special case — but the cycle
count is the thing that breaks it: the inner instruction's cost has to reach
`step()`'s return value, and the only channel a body has is the `bool | None` you
added in Step 06 for a different purpose. You would end up either widening that
return type again or storing the count on the CPU, and both are a worse trade
than four lines of `if`.

With A, the CB entries carry their *full* cost, prefix fetch included: 8 for a
register form, not 4. Write that in a comment above `CB_OPCODES`, because "8"
next to `RLC B` looks wrong to anyone who remembers the 4-cycle law and has
forgotten about the prefix.

**One consequence to notice now.** `0xCB` is never in `OPCODES`, so an
`UnknownOpcodeError` can never name it after this step. And because the CB table
is *dense* — all 256 defined, no gaps, no illegal entries — no CB opcode can ever
be unknown either. `len(CB_OPCODES) == 256` is a real test, and it is the only
place in this project where a table's completeness is a provable property rather
than a hope.

### 2. When generation earns its place, and when it does not

Every CB opcode decodes the same way. The low three bits are always an operand,
the same `Operand` enum the `LD` block and the `ALU` block already use, in the
same positions:

| Range | Bits | Family |
| --- | --- | --- |
| `0x00`–`0x3F` | `00 ooo rrr` | eight rotate/shift operations × eight operands |
| `0x40`–`0x7F` | `01 bbb rrr` | `BIT b, r` |
| `0x80`–`0xBF` | `10 bbb rrr` | `RES b, r` |
| `0xC0`–`0xFF` | `11 bbb rrr` | `SET b, r` |

Three bit fields, no exceptions, no holes. This block is going to be generated,
and it is worth being precise about *why* — because `cpu.py` already contains
both shapes and the split between them should be a rule rather than a mood.

| Generated | Written out |
| --- | --- |
| `_ld_block`, `_alu_block`, `_alu_immediate_block`, `_inc_dec_block`, `_pair_block` | the accumulator loads, the flag oddities, and all 40 instructions of Step 06 |

The rule is not "how many" on its own. It is a ratio: **entries produced,
divided by makers required.** A generator is a level of indirection, and
indirection is paid for once per *reader*, every time anyone asks "what does this
opcode do". It has to buy enough to cover that.

Run the test on Step 06. The four conditional families look uniform from the
outside, but their bodies genuinely differ:

- `JR cc` fetches one signed byte and adds it to `PC`
- `JP cc` fetches two bytes and assigns
- `CALL cc` fetches two bytes, pushes, then assigns
- `RET cc` fetches nothing and pops

So a generator needs four makers, not one, plus a table associating them with
base opcodes and cycle pairs. Forty hand-written bodies collapse to roughly six
makers and two tables — call it **6:1** — and in exchange, "what does `0xC4` do"
goes from *read one function* to *find the family, decode `(0xC4 >> 3) & 0b11`,
resolve the `Condition` member, read the maker*. One step becomes four.

Now run it on the CB block: 256 entries, three makers, one eight-element tuple.
Roughly **85:1**, and the bodies really are one shape with a parameter —
`read_operand`, transform, `write_operand`, apply flags — with no family-by-family
variation at all.

Same rule, opposite answers. That is what makes it a rule rather than a
preference, and it is why this document generates the CB block and leaves Step 06
alone.

Two costs of generation worth naming, because they vanish from view when line
count is the only thing being counted:

- **Symbol names disappear.** `_call_nz_a16` identifies itself in a traceback, in
  a profile and in a `git grep`. A closure named `execute` inside
  `_make_conditional` gives you one name for sixteen instructions. In Step 10 you
  will be reading failures out of a test ROM, which is exactly when you want the
  frame to name the instruction.
- **Irregularities become special cases inside a loop**, where they are harder to
  see than they were as one odd function among forty. `RET cc` taking no operand,
  and `StackPair` disagreeing with `RegisterPair` at `0b11`, are both this.

Past a few hundred entries the argument changes character rather than degree.
Nobody audits 256 functions by reading them, so "I can see that it is right"
stops being available, and the generator is not a compression of something
already checked — it is the only form in which the block *can* be checked.
Sections 4 through 7 are written on that assumption.

### 3. The eight rotates and shifts

`0x00`–`0x3F`, `00 ooo rrr`, operation in bits 5–3:

| `ooo` | Mnemonic | Diagram | `C` gets |
| --- | --- | --- | --- |
| `000` | `RLC` | `C <- [7 <- 0] <- 7` | old bit 7 |
| `001` | `RRC` | `0 -> [7 -> 0] -> C` | old bit 0 |
| `010` | `RL` | `C <- [7 <- 0] <- C` | old bit 7 |
| `011` | `RR` | `C -> [7 -> 0] -> C` | old bit 0 |
| `100` | `SLA` | `C <- [7 <- 0] <- 0` | old bit 7 |
| `101` | `SRA` | `[7] -> [7 -> 0] -> C` | old bit 0 |
| `110` | `SWAP` | `[7654] <-> [3210]` | `0` |
| `111` | `SRL` | `0 -> [7 -> 0] -> C` | old bit 0 |

All eight set `Z` from the result, clear `N`, clear `H`, and write `C` as above.
`SWAP` is the only one that clears `C` unconditionally, because it moves no bit
out of the byte.

Four distinctions inside that table are worth having as vocabulary, because
every one of them is a real bug someone has shipped.

**Rotate versus rotate-through-carry (`RLC` versus `RL`).** `RLC` is an 8-bit
rotation: bit 7 wraps around to bit 0, and `C` gets a *copy* of it. `RL` is a
**9-bit** rotation: the carry flag is the ninth bit of the register. Bit 7 goes
into `C`, and the *old* `C` comes into bit 0.

The reason the hardware has both is multi-byte arithmetic. To shift a 16-bit
value held in `H` and `L` one place left:

```
SLA L      ; low byte shifts, its bit 7 falls into C
RL  H      ; high byte shifts, C arrives as its bit 0
```

The carry is the wire between the two registers. This is the only mechanism the
SM83 has for values wider than eight bits, and it is why `RL` exists as a
separate operation rather than as a special case of `RLC`. Right-shifting a
16-bit value is the mirror: `SRL H` then `RR L`, high byte first.

**Arithmetic versus logical right shift (`SRA` versus `SRL`).** `SRL` puts a zero
into bit 7: dividing an unsigned byte by two. `SRA` copies bit 7 onto itself:
dividing a *signed* byte by two, preserving the sign. The SM83 has no divide
instruction, so these two shifts are how a program divides, and picking the wrong
one is how a negative value becomes a large positive one.

`SRA` on `0xFF` (−1) gives `0xFF` (−1), not `0x00`. Arithmetic right shift rounds
towards negative infinity, not towards zero, so it is not the same as C's `/ 2`
on a negative number. Not a bug, but a fact to have met before a test ROM asks.

**The Python trap in exactly this spot.** Python's `>>` on an `int` is
*arithmetic*, over an infinitely sign-extended two's complement representation.
For a value you have already masked to 8 bits — always non-negative — that means
`value >> 1` behaves as a **logical** shift, because there is no sign bit to
extend. So:

```python
srl = value >> 1                       # correct: bit 7 becomes 0
sra = (value >> 1) | (value & 0x80)    # you re-inject bit 7 yourself
```

In C the distinction lives in the *type*; in Python it lives in the sign of the
value, and every value here is unsigned by construction. So `SRA` is the one that
needs writing out. Ruby behaves the same way, for the same reason: `Integer#>>`
is arithmetic and its integers are unbounded.

**`SWAP` is not a rotate.** It exchanges the two nibbles. It exists because
nibbles are the unit that matters in BCD (see `DAA` in Step 05) and in every
packed hardware register, and because it is `>> 4` and `<< 4` at once for a cost
of one instruction. It is the only one of the eight where the carry is *cleared*
rather than *set from something*, which is the kind of asymmetry a
`Flags(c=False)` states and a `Flags()` silently gets wrong.

**Where these functions live.** `alu.py`, with the rest. They are pure functions
from an integer to `(int, Flags)`, they need no CPU, and they are the easiest
things in the project to test exhaustively — 256 inputs each, and the properties
in Task 8 check all of them.

### 4. The four accumulator rotates, and one flag that lies

`0x07`, `0x0F`, `0x17`, `0x1F` in the base table:

| Opcode | Mnemonic | Same as | Cycles | `Z` |
| --- | --- | --- | --- | --- |
| `0x07` | `RLCA` | `RLC A` | 4 (vs 8) | **always 0** |
| `0x0F` | `RRCA` | `RRC A` | 4 | **always 0** |
| `0x17` | `RLA` | `RL A` | 4 | **always 0** |
| `0x1F` | `RRA` | `RR A` | 4 | **always 0** |

Identical arithmetic, identical `C`, `N` and `H`. The only difference is `Z`: the
CB forms set it from the result, these four clear it even when `A` ends up
`0x00`.

Do not rationalise this into a rule — it is a quirk carried over from the 8080,
where the flags register was updated by a narrower set of wires. What matters is
the practical consequence: **the flag lies, so nothing may branch on it.** Code
after `RLA` branches on the carry, which is the whole point of `RLA`, and code
that wants to know whether `A` is zero does `OR A` afterwards. If you implement
these four as `Z`-from-result, no test of yours will fail, no ROM will crash
immediately, and Blargg's `cpu_instrs` will report a mismatch several thousand
instructions later with no indication of which instruction produced it.

Step 05 postponed these four here for exactly this reason. Implement the rotation
**once**, in `alu.py`, and let the four base-table bodies override `Z` at the
call site:

```python
from dataclasses import replace

result, flags = rlc(cpu.registers.a)
cpu.registers.apply(replace(flags, z=False))
cpu.registers.a = result
```

`dataclasses.replace` builds a new instance of a frozen dataclass with some
fields changed — the functional-update operation that `frozen=True` otherwise
denies you. Ruby has no direct equivalent for a `Struct`; the nearest is
`dup`-then-mutate on a non-frozen copy, or `with` on a `Data` object in 3.2+,
which is precisely this.

The alternative is a `zero_flag: bool` parameter on each of the four `alu`
functions. It works, and it is worse: it puts the exception inside the rule, so
252 correct callers carry a parameter that exists for four wrong ones. Keep the
exception at the four sites that *are* the exception.

### 5. `BIT b, r`, the instruction that writes nothing

`0x40`–`0x7F`, `01 bbb rrr`. Bit index in bits 5–3, operand in bits 2–0.

```
Z = NOT bit b of r      N = 0      H = 1      C = unchanged
```

Four separate things to get right, and all four are cheap to get wrong.

**It writes no register.** `BIT` is `AND` with a one-bit mask and the result
thrown away — the same relationship `CP` has to `SUB`. Your `AluOperation` type
already names this: `writes_result=False`. This block does not go through
`AluOperation`, but the precedent is the shape to copy.

**`Z` is inverted.** The bit being *clear* sets `Z`. This reads backwards until
you read it together with the branch that always follows:

```
BIT 7, (HL)
JR  Z, somewhere     ; "jump if bit 7 was clear"
```

`Z` means "the tested bit was zero", which is exactly what `Z` has always
meant — the AND produced zero — and the inversion is only in the naming.

**`H` is set, always.** Not computed, not preserved: `1`. It is a leftover from
the AND implementation (Step 05's `and_` sets `H` too, for the same reason).

**`C` is untouched.** This is the one to write a test for. `Flags(c=None)` means
"leave it alone" and `Flags(c=False)` means "clear it", the two differ by one
token, and a test that happens to run with `C` already clear passes either way.
Set the carry, run `BIT`, assert it survived. `INC`/`DEC` had the same property
in Step 05 and this is the second and last block that needs it.

**And the cycle irregularity.** `BIT b, (HL)` costs **12**, not 16, because it
reads memory and never writes back. It is the only exception in the whole CB
table, and section 7 makes it fall out of the existing rule rather than being
special-cased.

### 6. `RES` and `SET`, and the first callers of two Step 01 functions

`0x80`–`0xBF` is `RES b, r` (clear bit `b`), `0xC0`–`0xFF` is `SET b, r`. Both
write the result back. **Neither touches any flag** — not `Z`, not anything. A
`Flags()` with all four `None` is the correct thing to apply, or better, apply
nothing at all.

`bits.set_bit` and `bits.clear_bit` were written in Step 01 and have had no
callers since. They get 128 of them here, which is worth noticing as a small
vindication: the primitives were written before the thing that needed them, and
they needed no changes when it arrived.

One Python detail inside `clear_bit`: `~(1 << b)` is a *negative* integer —
`~1 == -2` — and `value & -2` works correctly because Python's integers are
two's complement with infinite sign extension to the left. The result for a
non-negative `value` is non-negative, which matters because `Registers.__setattr__`
raises on anything outside `0..0xFF`. Same fact as `u8(-1) == 0xFF` from Step 05,
arriving from the other direction.

**Why a third of the instruction set is single-bit access.** The Game Boy has no
boolean type and no byte to spare. `LCDC`, `STAT`, `IE`, `IF`, the joypad
register — every hardware interface is a bitfield, and talking to hardware means
reading and writing one bit at a time. From Step 08 onwards you will be reading
emulator code and ROM code full of `BIT 0, A` and `RES 2, (HL)`, and they will be
about interrupts, not about arithmetic. These 192 opcodes are the Game Boy's I/O
layer.

### 7. Cycles, and the smallest change to `count_cycles`

| Form | register operand | `(HL)` |
| --- | --- | --- |
| `RLC`…`SRL`, `RES`, `SET` | 8 | 16 |
| `BIT` | 8 | 12 |

Derive them rather than memorising them. Step 05's law — 4 T-cycles per memory
access — still holds, and a prefixed instruction simply has one more access:

- prefix fetch + opcode fetch = 2 accesses = 8. That is every register form.
- plus a read of `(HL)` and a write back = 4 accesses = 16.
- `BIT` reads and does not write = 3 accesses = 12.

`count_cycles` already counts one access for the fetch, one per immediate byte,
and one per `Operand.HL_POINTER` in its arguments. It needs exactly one more
thing: a way to say "there were two opcode bytes".

```python
def count_cycles(
    *accesses: Operand, immediates: int = 0, data_accesses: int = 0,
    prefixed: bool = False,
) -> int:
```

Then, with `operand` being the decoded `Operand`:

| Call | register | `(HL)` |
| --- | --- | --- |
| `count_cycles(operand, operand, prefixed=True)` | 8 | 16 |
| `count_cycles(operand, prefixed=True)` | 8 | 12 |

Read-modify-write passes the operand twice — once for the read, once for the
write — exactly as `_inc_dec_block` already does. `BIT` passes it once. The
12-cycle irregularity of section 5 is then not an irregularity at all: it is what
"reads but does not write" costs, and the table says so without a single literal
number in the CB block.

Resist adding a `cycles=` literal anywhere in this block. If a number disagrees
with <https://gbdev.io/gb-opcodes/optables/>, the fix belongs in the rule.

### 8. The `(HL)` forms are read-modify-write, and that will matter later

48 of the 256 CB opcodes have `rrr == 0b110` and operate on memory. Your
`read_operand`/`write_operand` pair already handles that transparently, so
nothing in this step needs to know — which is the payoff of the `Operand` enum
having included `HL_POINTER` since Step 05.

Two things to bank for later. On hardware the read and the write are separate bus
accesses several cycles apart, and from Step 11 onwards there are windows in
which the PPU owns VRAM and a write from the CPU is silently dropped. A
read-modify-write straddling that boundary is one of the ways a real game
produces a glitched tile. Nothing to do now; the point is that "read then write"
is not one operation and your code should not come to assume it is.

And `BIT b, (HL)` must not write. If you generate all three families through one
maker with a `writes_back` flag, that flag is the same fact as the 12-cycle count
from section 7 — one property of `BIT`, showing up in two places. Consider
whether it should be one thing in your code.

### 9. The eleven illegal opcodes

`0xD3` `0xDB` `0xDD` `0xE3` `0xE4` `0xEB` `0xEC` `0xED` `0xF4` `0xFC` `0xFD`.

No instruction exists. On real hardware they hang the CPU completely — not an
exception, not a reset: the machine stops fetching and only a power cycle
recovers it. They are what is left over after the base table was filled, and the
Z80 used most of them as *its* prefix bytes, which is why they cluster at the
addresses they do.

Leave them out of the table. `UnknownOpcodeError` is the honest response and
"hang forever" would be a worse emulator to debug. What changes today is what the
error *means*: before this step it meant "not implemented yet", and after it, it
means one of exactly three things —

1. a Step 08 opcode (`0x10`, `0x76`, `0xD9`, `0xF3`, `0xFB`),
2. one of the eleven above, which means execution went somewhere that is not code,
3. a bug.

Being able to tell those apart from the opcode alone is worth the thirty seconds
it takes to put the two lists in a comment above `OPCODES`.

### 10. Testing 256 instructions without writing 256 tests

The blocks in this step are generated, so test the generator, not the entries —
the pattern `test_cpu.py` already uses for `LD` and `ALU`. What is new is that
the operations underneath are *pure and cheap*, which unlocks a kind of test the
project has not used yet: over all 256 possible inputs.

Not "assert `RLC(v)` equals `((v << 1) | (v >> 7)) & 0xFF`" — that restates the
implementation in the test and passes whenever both are wrong the same way.
Assert **properties**, the things that would be true of a correct implementation
however it was written:

| Property | Over |
| --- | --- |
| `RRC(RLC(v)) == v` | all 256 `v` |
| `RLC` moves old bit 7 into `C`, and `C` equals new bit 0 | all 256 `v` |
| `RR` after `RL` restores `v` *and* the original carry | all 256 `v` × both carries |
| `SRL(v) < 0x80` | all 256 `v` |
| `SRA(v)` keeps bit 7 equal to `v`'s bit 7 | all 256 `v` |
| `SWAP(SWAP(v)) == v` | all 256 `v` |
| `SET b` then `BIT b` leaves `Z` clear; `RES b` then `BIT b` sets it | 256 × 8 |

Seven tests, no hand-written expected values, and each one fails for a reason you
can name. `RL`/`RR` round-tripping *with* the carry is the one that catches the
classic bug of section 3 — implementing `RL` as `RLC` — because as an 8-bit
rotation `RL` still round-trips against `RR`, and only the carry disagrees.

`pytest.mark.parametrize("value", range(0x100))` gives 256 named cases; a `for`
loop inside one test gives one case and a worse failure message. Prefer the
parametrize for the small sets and the loop for the 2048-case ones, and be aware
that is a judgement call about failure output, not about correctness.

### 11. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| `dataclasses.replace` | the `Z=0` override on four accumulator rotates | `Data#with` (3.2+) |
| A second dispatch table, chosen at decode time | `CB_OPCODES` beside `OPCODES` | two frozen hashes |
| Keyword-only-ish defaults extending a helper without touching callers | `count_cycles(prefixed=...)` | optional keyword args |
| Exhaustive parametrization over a small domain | 256 inputs per operation | `each` in a spec, but generated |
| Property-based assertions over hand-picked ones | round-trips instead of expected values | same idea, no library |
| Arithmetic vs logical shift on unbounded ints | `SRA` needs bit 7 re-injected | identical semantics |

---

## Tasks

### 1. The eight operations in `alu.py`

`rlc`, `rrc`, `rl`, `rr`, `sla`, `sra`, `swap`, `srl`, each
`(value: int) -> tuple[int, Flags]`, except `rl` and `rr` which also take the
incoming carry — the same signature shape `adc` and `sbc` already have.

Flags per theory section 3: `Z` from the result, `N=0`, `H=0`, `C` per the table.

**Acceptance:** `alu.py` still imports nothing from `cpu.py`, and the properties
in Task 8 pass over all 256 inputs.

---

### 2. `count_cycles(prefixed=...)`

One parameter, one added term, per theory section 7. Do it before the blocks so
that no cycle literal is ever written in them.

**Acceptance:** every existing call site is untouched and every existing cycle
test still passes.

---

### 3. The CB dispatch

`CB_OPCODES: Final[dict[int, Instruction]]`, empty for now, and the two-stage
decode in `step()` per theory section 1.

Do this before the blocks and check it with a single test: `0xCB 0x00` raises
`UnknownOpcodeError`. Then check the address in the message. `step()` currently
reports `pc - 1`, which is right for a one-byte opcode and one short for a
prefixed one. Decide what the message should say — the address of the `0xCB`, or
of the byte after it — and make it say that deliberately. Once the table is full
this error becomes unreachable, so this is the only moment you can test it.

---

### 4. The rotate/shift block, `0x00`–`0x3F`

A tuple of eight `(name, function)` pairs indexed by `(opcode >> 3) & 0b111`, and
one maker. `_ALU_OPERATIONS` is the precedent, including the `lambda` wrappers
that make the signatures uniform — `rl` and `rr` need the carry, the other six do
not, and the tuple is where that difference gets absorbed.

Names in the trace read `RLC B`, `SWAP (HL)`, `SRL A`.

---

### 5. `BIT`, `RES`, `SET`, `0x40`–`0xFF`

Three families, one loop each, `Operand(opcode & 0b111)` and
`(opcode >> 3) & 0b111` for the bit index. Names read `BIT 7, (HL)`,
`RES 0, A`, `SET 3, B`.

`BIT` writes no operand and no `C`; `RES` and `SET` write no flags at all.

**Acceptance:** `len(CB_OPCODES) == 256`, and `BIT 7, (HL)` reports 12 cycles
while `SET 7, (HL)` reports 16.

---

### 6. The four accumulator rotates

`0x07`, `0x0F`, `0x17`, `0x1F` in the base table, 4 cycles each, reusing the
`alu` functions from Task 1 with `Z` overridden per theory section 4.

**Acceptance:** `RLCA` with `A = 0x00` leaves `Z` **clear**, and `CB 07`
(`RLC A`) with the same input sets it. That pair of assertions, next to each
other in the file, is the whole point of having postponed these four.

---

### 7. The tracer has to learn about the prefix

`__main__.trace` does `OPCODES[opcode]` after stepping. Feed it a ROM containing
a `0xCB` and it raises `KeyError` — the comment above that line explains why the
subscript is safe, and the reasoning stops holding today.

Fix it by teaching the tracer to decode a prefixed instruction: read the byte at
`address`, and if it is `0xCB`, read the next one and look it up in `CB_OPCODES`.
Print both bytes (`CB 7E`) so the trace stays honest about how many bytes the
instruction occupied.

Two things worth noticing while you are in there:

- The opcode column is 2 characters wide and now needs 5. `NAME_WIDTH` stays at
  12: the longest CB mnemonic is `BIT 7, (HL)` at 11, still shorter than
  `LD HL, SP+e8`.
- What you are writing is a `decode(bus, address) -> (name, length)` function,
  and that is the first half of the disassembler from Step 16. Put it in
  `cpu.py`, not in `__main__.py`, and let the tracer call it. Instruction
  decoding is not a property of the CLI.

Also add the summary line Step 06 suggested and that is still missing: when the
trace ends, print instructions executed, total T-cycles, and why it stopped.
Cycles are the clock from Step 09 onwards and you are already summing them.

---

### 8. Tests

**In `tests/test_alu.py`**, per theory section 10: the seven property tests over
all 256 inputs. No CPU in this file, as before.

**In `tests/test_cpu.py`:**

- table completeness: `len(CB_OPCODES) == 256`, and every key in `range(0x100)`
- spot-checks that decoding is right: `0xCB 0x00` is `RLC B`, `0xCB 0x36` is
  `SWAP (HL)`, `0xCB 0x7E` is `BIT 7, (HL)`, `0xCB 0xFF` is `SET 7, A`
- the closure trap, as in every generated block: two entries from the same
  family behave differently
- cycles: 8 for a register form, 16 for a `(HL)` form, 12 for `BIT b, (HL)`
- `BIT` preserves `C`: set it, run `BIT`, assert it is still set
- `RES`/`SET` touch no flags: set all four, run one, assert all four survive
- the `Z` asymmetry from Task 6, both directions
- one `(HL)` form end to end: memory changed, `HL` unchanged

**A program test**, the payoff. Something that uses the block the way ROM code
does — a 16-bit shift across two registers, per theory section 3:

```
; HL = 0x1234, shift left once -> 0x2468
SLA L
RL  H
```

Assemble it into `cpu_running`, step it twice, assert `HL`. It is three
instructions' worth of bytes and it tests the carry-as-a-wire behaviour that no
single-instruction test can.

Bounded loops only, as established in Step 06.

---

### 9. Run a real ROM

```
uv run python -m gameboy rom.gb --trace 200000 | tail -20
```

It cannot stop on a CB opcode any more, and it cannot stop on a rotate. What is
left is one of the five Step 08 opcodes or one of the eleven illegal ones, and
which one it is tells you something different in each case:

- `0xF3` (`DI`) or `0x76` (`HALT`): expected. The ROM is setting up interrupts,
  which is Step 08, and you have got as far as this step can take you.
- one of the eleven: execution left the code. Find the last trace line whose
  address looks like real code and work forward from there.

Report which one, at which address, after how many instructions and how many
cycles. The cycle count is a number worth writing down — from Step 09 it becomes
comparable against real hardware, where one frame is 70,224 T-cycles.

The loop-shape one-liner from Step 06 is still the fastest way to read the trace:

```
uv run python -m gameboy rom.gb --trace 200000 | awk '{print $1}' | uniq -c | head -40
```

---

### 10. Docs

`README.md`'s step table needs `06` marked done and `07` added. If the trace
example in it now runs further than three instructions, it is worth refreshing.

---

### Optional: two warts in the Step 06 block

Neither of these is the generator argument from section 2. They are two specific
things that are wrong on their own terms, whichever shape you prefer.

**`PUSH`/`POP` dispatch through a `match` to reach a constant.** `_push_bc` is:

```python
value = read_stack_pair(cpu, StackPair.BC)
cpu.push16(value)
```

`read_stack_pair` is a four-way `match`, and its argument is a literal constant
at every one of its eight call sites. That function exists to serve *generated*
code, where the pair is a variable. In a hand-written body it is indirection with
nobody paying for it, and `cpu.push16(cpu.registers.bc)` says the same thing in
one line and one attribute access.

Going fully explicit there lets `read_stack_pair` and `write_stack_pair` be
deleted outright — nothing else calls them, including the tests — and leaves
`StackPair` as what it actually is: documentation of the encoding, and the thing
that keeps `0b11 == AF` from being a bare `3` in a comment.

Keep the helpers if you would rather. But then those eight bodies are the
generated shape *without* the generator, which is the one combination nothing
argues for.

**The `RST` bodies are out of numeric order.** `cpu.py:1003` onwards runs `0x00`,
`0x10`, `0x08`, `0x18`, `0x20`, … The table entries are in order and the
functions are not. One reorder, and it is the kind of thing that is free to fix
now and irritating later.

---

## Hints

- If `RL` round-trips against `RR` but a test ROM disagrees, you implemented `RL`
  as `RLC`. The two differ only in where bit 0 comes from, and only the carry
  test catches it.
- If every CB instruction is 4 cycles short, the prefix fetch is missing from the
  count. If exactly the `(HL)` forms are short, the operand is being passed once
  where it should be passed twice.
- A `BIT` that clears the carry will not fail any test that does not set the
  carry first. Write that test before you write the block.
- `SRA` is the only one of the eight where Python's `>>` is not already the right
  answer. If you find yourself needing a mask on any of the other seven's shift
  direction, check whether you have masked to 8 bits *after* shifting left rather
  than before.
- `Registers.__setattr__` raising `does not fit in register` from inside a CB
  instruction means a shift produced a 9-bit value: mask with `u8` after
  shifting left.
- The `0xCB` handling in `step()` is four lines. If it is growing, the shape has
  drifted towards option B from theory section 1.
- Cross-check the cycle table against <https://gbdev.io/gb-opcodes/optables/>.
  The CB page lists register forms as 8 and `(HL)` forms as 16, with `BIT`'s 12
  as the only exception, exactly as section 7 derives.

---

## Acceptance criteria

- [ ] `len(OPCODES) == 240` and `len(CB_OPCODES) == 256`.
- [ ] Every opcode in `range(0x100)` is either in `OPCODES`, in the Step 08 list
      (`0x10` `0x76` `0xD9` `0xF3` `0xFB`), or in the illegal list.
- [ ] No cycle count is written as a literal anywhere in the CB block.
- [ ] `BIT b, (HL)` costs 12; every other `(HL)` CB form costs 16; every register
      form costs 8.
- [ ] `BIT` leaves `C` unchanged; `RES` and `SET` leave all four flags unchanged.
- [ ] `RLCA` clears `Z` on a zero result and `RLC A` sets it.
- [ ] `SRA` preserves bit 7 and `SRL` clears it, over all 256 inputs.
- [ ] `SLA L` / `RL H` shifts `HL` left as a 16-bit value.
- [ ] `--trace` prints prefixed instructions with both opcode bytes and a
      readable mnemonic, and prints a summary line when it stops.
- [ ] The ROM trace stops on a Step 08 opcode, not on anything from this step.
- [ ] `alu.py` still imports nothing from `cpu.py`; `bits.py` still imports
      nothing.
- [ ] No test runs an unbounded loop.
- [ ] `uv run pytest` is green, `uv run ruff check .`,
      `uv run ruff format --check .` and `uv run mypy` are clean.

---

## Questions to ask yourself before moving on

1. Section 2's ratio test generates at 85:1 and declines at 6:1. Where between
   those two does your own line sit, and which input actually moves it — the
   ratio, the absolute entry count, or how much you trust the tests to catch a
   copy-paste slip? Steps 11 and 12 have the same decision waiting in the PPU,
   and it will be easier if you have already named the number.
2. `BIT` costs 12 cycles on `(HL)` and writes nothing back. Those are two
   statements of one fact. Did they end up as one thing in your code or two, and
   what would go wrong if someone changed one of them?
3. The four accumulator rotates are duplicates of four CB instructions with one
   flag difference. The hardware designers spent four of 256 base-table slots on
   them. What does that tell you about what ROM code spends its time doing, and
   which other instruction in the base table is there for the same reason?
4. You now have two dispatch tables and a decode that picks between them. Step 08
   adds interrupt dispatch, which is a `CALL` that no opcode asked for. Where in
   `step()` does that go, and does it happen before or after the fetch?
5. `UnknownOpcodeError` now means one of three things. Which of the three is the
   one you will actually hit in Step 10, and is the message enough to tell you
   which one you are looking at?
