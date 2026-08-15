# Step 05 — Loads, the ALU and the flags

## Goal

Teach the CPU to move bytes around and do arithmetic on them. By the end of this
step the opcode table grows from two entries to roughly 180, the four flags stop
being decoration, and a real ROM runs its first nine instructions before hitting
something that belongs to Step 06.

Concretely, on Tetris:

```
0100  00  NOP
0101  C3  JP a16      -> 0150
0150  C3  JP a16      -> 020C
020C  AF  XOR A       -> A = 0x00, Z set
020D  21  LD HL,d16   -> HL = 0xDFFF
0210  0E  LD C,d8     -> C = 0x10
0212  06  LD B,d8     -> B = 0x00
0214  32  LD (HL-),A  -> writes 0x00 at 0xDFFF, HL = 0xDFFE
0215  05  DEC B       -> B = 0xFF, Z clear, N set, H set
0216  20  unknown opcode
```

That is the game clearing 8 KiB of work RAM before it does anything else, and
`0x20` is `JR NZ, e8`, the first instruction of Step 06. Stopping there is the
success condition, not a failure.

> **Visual companion:** ask for one if the half-carry rules or the opcode bit
> patterns stay fuzzy after a read. Both draw well.

---

## Theory

### 1. What actually makes this step big

180 opcodes sounds like a wall. It is not, because they are not 180 different
things. They are five behaviours applied over eight operands:

| Behaviour | Opcodes | Distinct logic to write |
| --- | --- | --- |
| Copy a byte from somewhere to somewhere | ~90 | one |
| Eight ALU operations on `A` | 72 | eight |
| Increment or decrement a byte | 16 | two |
| 16-bit loads and 16-bit arithmetic | 13 | four |
| Flag and accumulator oddities (`DAA`, `CPL`, `SCF`, `CCF`) | 4 | four |

So the work is: about twenty small functions, plus the machinery that maps 180
byte values onto them. The machinery is the interesting part and it is what
sections 2 and 3 are about.

The other half of the step is flags. Every ALU operation writes some subset of
`Z`, `N`, `H` and `C`, each with its own rule, and the rules are exactly the kind
of thing that is easy to get 90% right. A 90%-right carry flag is an emulator
that runs Tetris and fails Zelda for reasons you cannot trace. Blargg's
`cpu_instrs` in Step 10 exists to catch precisely this, but do not rely on it as
the first line of defence. Write the rules once, in one place, and test them
directly.

### 2. The opcode map is a bit pattern, not a list

The SM83's designers laid the instruction set out on a grid. Look at the byte in
binary and the fields fall out.

Three-bit operand index, used everywhere:

| Index | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Operand | `B` | `C` | `D` | `E` | `H` | `L` | `(HL)` | `A` |

**The load block, `0x40` to `0x7F`.** The bits read `01 ddd sss`: destination in
bits 5 to 3, source in bits 2 to 0.

```
0x47 = 0100 0111 = 01 000 111  ->  LD B, A
0x7E = 0111 1110 = 01 111 110  ->  LD A, (HL)
```

64 opcodes, one rule. One hole: `0x76` would be `LD (HL), (HL)`, which is
meaningless, so the hardware uses that encoding for `HALT`. Leave it out of the
table and it raises `UnknownOpcodeError` until Step 08, which is accurate: a ROM
that halts today has done something your emulator cannot yet model.

**The ALU block, `0x80` to `0xBF`.** The bits read `10 ooo sss`: operation in
bits 5 to 3, source in bits 2 to 0. The destination is always `A`, which is why
it is called the accumulator.

| Index | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Operation | `ADD` | `ADC` | `SUB` | `SBC` | `AND` | `XOR` | `OR` | `CP` |

**The immediate ALU opcodes.** The same eight operations against a byte that
follows the opcode, encoded `11 ooo 110`: `0xC6` `ADD A,d8`, `0xCE` `ADC A,d8`,
and so on to `0xFE` `CP d8`. Same operation index, different source.

**`INC` and `DEC`.** `00 rrr 100` is `INC r`, `00 rrr 101` is `DEC r`, with the
same operand index. `LD r, d8` is `00 rrr 110`.

Everything below `0x40` that is not one of those three columns is irregular, and
you write those by hand. That is fine: there are about twenty of them.

**The consequence for your code.** You generate the regular blocks with loops
over the index, and you type out the irregular ones. Typing 180 dict entries by
hand is not just tedious, it is untestable: a transposed pair of letters in the
middle of the load block produces an emulator that is wrong in one instruction
out of 64 and looks completely fine.

### 3. Index 6 is memory, not a register

`(HL)` in the operand table means "the byte at the address in `HL`". It occupies
a slot in a table of registers, and it is not a register. Three consequences:

- Reading it is a bus read, writing it is a bus write.
- It costs 4 extra T-cycles, because the bus access takes a machine cycle.
  `LD B, C` is 4; `LD B, (HL)` is 8; `LD (HL), B` is 8. `INC B` is 4;
  `INC (HL)` is 12, because that one reads *and* writes.
- `LD (HL), (HL)` cannot exist, which is the `HALT` hole from section 2.

This is the one place where the neat grid leaks. Either you give operand access a
single pair of functions that handle all eight indexes (including the bus access
for index 6), or you write the special case 90 times. The first option is the
reason to have the operand index be a first-class concept in your code rather
than something you decode inline in each instruction body.

Cycle counts need the same treatment: a generated instruction's cost depends on
how many bus accesses it makes, which the operand indexes tell you. Compute it
while you are generating the entry, from the indexes you already have in hand.
Note that "how many accesses" is not "how many operands are index 6" — `INC (HL)`
has one such operand and makes two accesses. Task 3 has the rule.

### 4. Half-carry, stated precisely

A nibble is four bits. The half-carry flag `H` records whether a carry crossed
from the low nibble into the high nibble, meaning out of bit 3 into bit 4. `C`
records the same event at the top of the byte, out of bit 7.

For addition, `H` is set when the low nibbles alone overflow:

```
(a & 0x0F) + (b & 0x0F) > 0x0F
```

For subtraction, `H` is set when the low nibble of the left operand is too small
and has to borrow:

```
(a & 0x0F) < (b & 0x0F)
```

For `ADC` and `SBC` the incoming carry participates in the nibble arithmetic too,
so it is added on the right-hand side of both formulas. This is a genuine
hardware behaviour and a classic emulator bug: an `ADC` whose half-carry ignores
the carry bit is wrong only when the carry is set and the nibbles sum to exactly
`0x0F`, which is rare enough to survive months of testing.

`C` for addition is "the 9-bit sum exceeded `0xFF`". For subtraction it is "the
left operand was smaller than the right", a borrow.

`H` and `N` exist for `DAA` and nothing else reads them. That does not make them
optional: `DAA` reads them, games use `DAA` for scores, and a wrong `H` shows up
as a scoreboard displaying `0x1A` points.

### 5. The flag rules, per family

This table is the specification. Everything else in this step is plumbing.

| Operation | Z | N | H | C |
| --- | --- | --- | --- | --- |
| `ADD A,n` / `ADC A,n` | result is 0 | 0 | nibble carry | byte carry |
| `SUB n` / `SBC A,n` | result is 0 | 1 | nibble borrow | byte borrow |
| `CP n` | result is 0 | 1 | nibble borrow | byte borrow |
| `AND n` | result is 0 | 0 | **1** | 0 |
| `OR n` / `XOR n` | result is 0 | 0 | 0 | 0 |
| `INC r` | result is 0 | 0 | low nibble was `0xF` | **unchanged** |
| `DEC r` | result is 0 | 1 | low nibble was `0x0` | **unchanged** |
| `ADD HL,rr` | **unchanged** | 0 | carry out of bit 11 | carry out of bit 15 |
| `INC rr` / `DEC rr` | unchanged | unchanged | unchanged | unchanged |
| `CPL` | unchanged | 1 | 1 | unchanged |
| `SCF` | unchanged | 0 | 0 | 1 |
| `CCF` | unchanged | 0 | 0 | inverted |
| `DAA` | result is 0 | unchanged | 0 | see section 7 |

Four entries in that table are the ones that bite:

**`AND` sets `H`.** It has nothing to do with a carry. The flag is set because
the hardware sets it, and `OR` and `XOR` clear it. Do not look for a reason.

**`INC` and `DEC` leave `C` alone.** This is not an oversight in the hardware, it
is what makes 16-bit arithmetic possible on an 8-bit machine: you can increment a
loop counter in the middle of a multi-byte addition without destroying the carry
you are propagating. Every emulator author writes `INC` as `ADD 1` once, and
every one of them finds it later.

**`CP` is `SUB` with the result thrown away.** It sets the flags and does not
touch `A`. It exists so that Step 06's conditional jumps have something to branch
on. It is also, in a sense, the whole reason the flag register exists.

**`ADD HL,rr` leaves `Z` alone** and computes its half-carry at bit 11, not bit
3. A 16-bit value is four nibbles, and its "half" is the boundary between the
low twelve bits and the top four. The formula:

```
(hl & 0x0FFF) + (rr & 0x0FFF) > 0x0FFF
```

`INC rr` and `DEC rr` touch no flags at all, unlike their 8-bit namesakes.

### 6. The "unchanged" column is a design requirement

Three rows in that table leave a flag unchanged, and one of them
(`INC`/`DEC` leaving `C`) is on an instruction you will implement sixteen times.
So whatever shape you choose for "the flags an operation produces" has to be able
to say *nothing* about a flag, distinctly from saying `False`.

The two candidate shapes:

| Shape | "Leave `C` alone" is | Cost |
| --- | --- | --- |
| The operation mutates the CPU's flags directly | not writing to it | flag logic needs a CPU to test |
| The operation returns a record of what changed | a field set to `None` | one extra type, testable without a CPU |

The second one is worth the extra type here. The flag rules are the part of this
step most likely to be subtly wrong, and pure functions from two integers to a
result and four flags are the easiest thing in this entire project to test
exhaustively. `Optional[bool]`, spelled `bool | None`, gives you three states:
`True`, `False`, and "this operation does not write this flag".

Ruby note: `nil` doubles as false in a boolean context, so this distinction is
awkward to express there without a sentinel. Python's `None` is not `False` and
`if flag is None` is a different test from `if not flag`. Use `is None`
explicitly and mypy will keep you honest, because `bool | None` does not narrow
to `bool` without it.

### 7. `DAA`, once, so it never has to be thought about again

Some games store numbers as **binary-coded decimal**: one decimal digit per
nibble, so the byte `0x37` means thirty-seven, not fifty-five. Scores and timers
are usually BCD, because printing them means splitting nibbles rather than
dividing by ten, and division is expensive on a CPU with no divide instruction.

The problem: the ALU adds in binary. `0x37 + 0x05` is `0x3C`, and `0x3C` is not
a BCD number at all. The correct answer is `0x42`.

`DAA` (decimal adjust accumulator) fixes `A` after the fact. It reads `N` to know
whether the last operation was an addition or a subtraction, and reads `H` and
`C` to know whether either nibble overflowed. The rule:

- If the last operation was an addition (`N` is 0): add `0x06` when `H` is set or
  the low nibble exceeds 9; add `0x60` when `C` is set or `A` exceeds `0x99`, and
  set `C` when you do.
- If the last operation was a subtraction (`N` is 1): subtract `0x06` when `H` is
  set, subtract `0x60` when `C` is set. `C` keeps whatever value it had.

Then `Z` comes from the adjusted `A`, `H` is cleared, and `N` is untouched.

Note the asymmetry: the addition branch inspects the value of `A`, the
subtraction branch only inspects flags. That is not a simplification, it is what
the hardware does, and it is why `DAA` cannot be written as one symmetric
expression. Write the two branches out.

`0x06` and `0x60` are "the gap between binary and decimal" at each nibble: 16
minus 10.

### 8. Your registers reject; the ALU must mask

Step 04's document suggested that register setters mask with `u8` and `u16`. You
built something else: a `__setattr__` guard that raises `ValueError` when a value
does not fit. That was a defensible call and it caught nothing so far, because
nothing in Step 04 produced an out-of-range value.

Step 05 produces them constantly. `0xFF + 1` is `0x100` in Python and `0x00` on
the hardware. `0x00 - 1` is `-1` in Python and `0xFF` on the hardware. So every
arithmetic result has to pass through `bits.u8` or `bits.u16` before it reaches a
register, and now the placement of that call is load-bearing rather than
belt-and-braces.

The rule to adopt: **a function that computes a value returns it already
masked.** The ALU helpers do the wrapping, at the point where they also compute
the carry that the wrap discarded, which is the only place with enough
information to do both. The `__setattr__` guard then stops being a safety net and
becomes an assertion: any `ValueError` out of it is a masking bug in the ALU, in
the one call site that forgot.

That is a better arrangement than masking setters, which would have silently
swallowed the same bug. It is worth noticing that you get the better property
because the guard is strict, not in spite of it.

The guard is inside `if __debug__`, so `python -O` drops it. Leave it that way.

### 9. Generating instructions, and the trap waiting there

The regular blocks come from loops. In Python a loop that builds functions has a
sharp edge that Ruby does not have.

Ruby's block parameters are fresh bindings per iteration, so this works:

```ruby
(0..7).map { |i| -> { i } }.map(&:call)  # => [0, 1, 2, ..., 7]
```

Python's `for` target is one binding in the enclosing scope, and a closure
captures the *variable*, not its value at capture time:

```python
makers = [lambda: i for i in range(8)]
[m() for m in makers]  # [7, 7, 7, 7, 7, 7, 7, 7]
```

Every generated instruction would execute with the last operand index. In this
step that means an opcode table where all 64 loads write to `A`, and a test suite
that passes for `LD A, A` and fails for everything else in the same way.

Two fixes, and both are idiomatic:

- Bind the value as a default argument: `lambda cpu, src=src: ...`. Defaults are
  evaluated once, when the lambda is created, which is exactly the capture you
  want.
- Use `functools.partial(_load, dest, src)`, which stores the arguments in the
  object. This reads better for anything longer than one line, and it gives the
  resulting object a useful `repr`. Ruby's nearest equivalent is
  `method(:load).curry[dest][src]`.

Prefer `partial` and a named module-level function over lambdas here. The body of
a generated instruction is real logic and deserves a name, a signature and a
docstring.

Note also that `Instruction.execute` is typed `Callable[[CPU], None]`, and
`partial(_load, dest, src)` has that type only if `_load`'s CPU parameter comes
*last*. Order the parameters so the bound ones come first. mypy checks this.

### 10. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| `functools.partial` | bind operand indexes into a generic instruction body | `method(:f).curry` |
| Closure late binding | the loop trap in section 9 | no equivalent; Ruby blocks bind per iteration |
| `bool \| None` and `is None` | "this operation does not write this flag" | awkward, `nil` is falsy |
| `enum.IntEnum` | naming the eight operand indexes without losing `int`-ness | a module of constants, or a frozen hash |
| Tuple return and unpacking | `result, flags = alu.add(a, b)` | multiple return values, same idea |
| `operator` module | `operator.and_` / `or_` / `xor` for the three bitwise ops | `:&.to_proc` |
| `pytest.mark.parametrize` stacking | two stacked decorators give you the cross product | `each` over two arrays |

`IntEnum` is worth a sentence. A member of an `IntEnum` *is* an `int`: it indexes
lists, compares to integers, and shifts. So `Operand.HL_MEM` can name index 6
without forcing conversions at every use, while `repr` still prints the name when
you are debugging a generated table.

---

## Tasks

### 1. `src/gameboy/alu.py`: the flag record and the 8-bit operations

**What this module is.** Pure arithmetic. It imports `bits` and nothing else. It
does not know what a CPU is, has no access to the bus, and never touches a
register. Every function in it takes integers and returns integers.

Keeping it separate is what makes section 5's table testable line by line: a test
for the half-carry of `SBC` is three integers in and four booleans out, with no
machine to construct.

**The flag record.** A frozen dataclass with four fields typed `bool | None`,
where `None` means the operation leaves that flag alone. Give the fields defaults
of `None` so that an operation only names the flags it writes.

**The operations.** One function per ALU operation, each returning the 8-bit
result and the flags:

```
add(a, b)            adc(a, b, carry)
sub(a, b)            sbc(a, b, carry)
and_(a, b)           or_(a, b)          xor(a, b)
inc(value)           dec(value)
```

`CP` needs no function of its own: it is `sub` with the result discarded by the
caller.

Results must come back already masked to 8 bits, per theory section 8.

`and_` and `or_` have trailing underscores because `and` and `or` are Python
keywords. This is the same convention as `operator.and_` in the standard library,
so it will look familiar to anyone reading it.

**Acceptance for this task:** every row of the table in theory section 5 that
concerns an 8-bit operation has a test, and none of those tests import `CPU`.

---

### Start here: the decisions tasks 2 to 6 assume

#### Decision 1: how a `Flags` record reaches the registers

Nothing in `cpu.py` can consume what the ALU returns yet. Every instruction in
the ALU block would otherwise end with the same four `if ... is not None` lines,
so that belongs in one place:

```python
def apply(self, flags: Flags) -> None: ...  # a method on Registers
```

It writes only the fields that are not `None`, which is the whole point of the
`None` from theory section 6: `INC B` leaves `C` alone without any instruction
having to remember to preserve it.

This is the import that makes `cpu.py` depend on `alu.py`. **One direction, for
the rest of the project.** `alu.py` importing from `cpu.py` is a cycle, and it is
also the thing that would stop the ALU tests from running without a machine.

Do this first. It is about six lines, everything downstream needs it, and it has a
clean test: apply `Flags(z=True)` to registers whose `c_flag` is already set, and
assert `c_flag` is still set.

#### Decision 2: where the operand accessors live

The accessors in task 2 need the register file *and* the bus. Only `CPU` has
both, so `CPU` is the home — either as methods or as free functions in `cpu.py`.
There is no import cycle either way; methods read better at the call site, since
`cpu.read_operand(src)` is what a free function's first argument makes it anyway.

Note what this rules out. Writing them in `alu.py` needs `from gameboy.cpu import
CPU` there, and decision 1 just pointed the arrow the other way.

> A Python 3.14 detail that will hide this from you: annotations are now
> evaluated lazily (PEP 649), so a function annotated with an undefined `CPU`
> defines fine and only fails when something asks for its type hints. Under 3.13
> the same file raised `NameError` on import. `mypy` still catches it; the
> interpreter no longer does.

#### Decision 3: how eight ALU operations get one call signature

This is the snag that makes task 5 look worse than it is. `add(a, b)`,
`adc(a, b, carry)` and `and_(a, b)` have three different shapes, and a generating
loop needs one.

Three honest ways out:

- Give all eight the signature `(a, b, carry)` and let six ignore the third
  argument. Uniform, but the signatures now lie, and `add(a, b, carry)` invites a
  caller to believe the carry matters.
- Keep `alu.py` honest and adapt at the table, wrapping the six as
  `lambda a, b, _c: alu.add(a, b)`.
- Do not unify at all: one `match` on the operation index inside a single
  dispatch function.

Prefer the second. `alu.py` keeps signatures that describe what each operation
actually needs, and the adaptation happens at the boundary that requires the
uniformity.

`CP` then needs one more piece of information — it computes with `sub` but must
not write `A`. Rather than special-casing index 7 by name, let the table entry
carry it:

```python
@dataclass(frozen=True, slots=True)
class AluOperation:
    name: str
    apply: Callable[[int, int, bool], tuple[int, Flags]]
    writes_result: bool
```

Eight of those, indexed by `ooo` from theory section 2. Watch the order while you
type it: `4 AND, 5 XOR, 6 OR`. XOR comes before OR, which is not the order anyone
recites them in.

#### Then: one instruction by hand, before any loop

Once the three decisions are made, hand-write `LD B, C` (`0x41`) as a single
table entry. Not generated — typed out. Run it through `cpu.step()` and assert
`B` took `C`'s value.

Do not skip this. It separates *is my operand plumbing sound* from *is my bit
pattern arithmetic right*. Generate sixty-four opcodes first and you will be
debugging both at once, with nothing to tell you which one is lying. Delete the
hand-written entry when the loop in task 4 replaces it.

#### The order

1. `Registers.apply(flags)` — decision 1.
2. `Operand` and the accessors — decision 2, which is task 2 below.
3. The cycle helper — task 3.
4. `LD B, C` by hand.
5. Generate `0x40`–`0x7F` — task 4.
6. The ALU block — task 5, which reuses every piece above.
7. Irregular loads, 16-bit, and `DAA`/`CPL`/`SCF`/`CCF` — tasks 4 (second half), 6
   and 7.

### 2. Naming the operand indexes

**The hardware fact.** Theory section 2 has the table: three bits select one of
`B`, `C`, `D`, `E`, `H`, `L`, `(HL)`, `A`.

**What to write.** An `IntEnum` with those eight members. Index 6 needs a name
that does not read like a register, since it is a memory access: `HL_MEM` or
`HL_POINTER` rather than `HL`.

Then the pair of accessors that turn an index into a value:

```python
def read_operand(cpu: CPU, operand: Operand) -> int: ...
def write_operand(cpu: CPU, operand: Operand, value: int) -> None: ...
```

Index 6 goes through the bus using `cpu.registers.hl` as the address; the other
seven read or write a register field. `getattr`/`setattr` on the register name is
one way; an explicit `match` is another and is what mypy prefers, since `getattr`
returns `Any` and quietly disables type checking for everything downstream of it.
Take the `match`.

These two functions live in `cpu.py`, not in `alu.py`, because they touch the
bus.

**Acceptance:** reading index 6 returns the byte at `HL`, and writing index 6
writes there.

### 3. Cycle costs for generated instructions

**The hardware fact.** Every number in this step comes from one law:

> **4 T-cycles per memory access, opcode fetch included.**

Check it against the tables in tasks 4 and 6 before writing anything:

| Instruction | Accesses | Cycles |
| --- | --- | --- |
| `LD B, C` | fetch | 4 |
| `LD B, (HL)` | fetch, read | 8 |
| `LD r, d8` | fetch, immediate | 8 |
| `LD (HL), d8` | fetch, immediate, write | 12 |
| `LD (a16), A` | fetch, immediate low, immediate high, write | 16 |
| `ADD A, (HL)` | fetch, read | 8 |
| `INC (HL)` | fetch, read, write | 12 |

**What to write.** A small helper that answers "how many cycles does this
instruction cost", so the generating loops in tasks 4 to 6 call it instead of
embedding literals. Getting this from a rule rather than a table means you cannot
get 63 of the 64 loads right and miss one.

**Count accesses, not operands.** The last row above is the trap. `INC (HL)` has
one operand and two bus accesses, so a helper that asks "is any operand index 6"
returns 8 and is wrong by a machine cycle.

**The law stops at the 16-bit operations.** `INC BC` is 8 with a single fetch,
because a 16-bit increment runs on its own unit rather than through the ALU. That
is exactly why task 6 is written by hand and tasks 4 and 5 are generated: the
generated blocks are the region where the law holds without exception.

Do not skip this into "I will just write 4 or 8 inline". The rule is one line and
it is the difference between a cycle-count bug that a test catches and one that
Step 09 catches, from four steps away.

### 4. The load block

**Generate `0x40` to `0x7F`** by looping over destination and source indexes, in
the encoding from theory section 2, skipping `0x76`.

The instruction name should include the operands, so `LD B, (HL)` rather than
`LD r, r`. The trace output is about to become the main debugging tool for the
rest of the project, and a trace that says `LD r, r` on every line is useless.
Build the name from the enum member names while you have them in hand.

`NAME_WIDTH` in `__main__.py` is currently 9 and there is a comment on it telling
you to bump it when a longer mnemonic lands. `LD (HL), A` is 10.

**Then the irregular loads**, by hand:

| Opcodes | Instruction | Cycles |
| --- | --- | --- |
| `0x06` `0x0E` `0x16` `0x1E` `0x26` `0x2E` `0x3E` | `LD r, d8` | 8 |
| `0x36` | `LD (HL), d8` | 12 |
| `0x02` `0x12` | `LD (BC), A`, `LD (DE), A` | 8 |
| `0x0A` `0x1A` | `LD A, (BC)`, `LD A, (DE)` | 8 |
| `0x22` `0x32` | `LD (HL+), A`, `LD (HL-), A` | 8 |
| `0x2A` `0x3A` | `LD A, (HL+)`, `LD A, (HL-)` | 8 |
| `0xE0` `0xF0` | `LDH (a8), A`, `LDH A, (a8)` | 12 |
| `0xE2` `0xF2` | `LD (C), A`, `LD A, (C)` | 8 |
| `0xEA` `0xFA` | `LD (a16), A`, `LD A, (a16)` | 16 |

Two of those rows need explaining.

**`HL+` and `HL-`** copy the byte and then increment or decrement `HL`, wrapping
at 16 bits. They exist because copying a block of memory is the most common thing
a Game Boy program does, and this makes the inner loop two instructions instead
of four. Tetris's `LD (HL-), A` at `0x0214` is exactly that: clearing work RAM
downwards from `0xDFFF`.

**`LDH` and `LD (C), A`** address the I/O page. The full address is `0xFF00` plus
an 8-bit offset, so a single byte reaches any hardware register. `LDH` takes the
offset as an immediate; `LD (C), A` takes it from register `C`, which is what
lets a loop walk across I/O registers. This is the `C`-as-I/O-offset note from
Step 04's register table finally paying off.

### 5. The ALU block

**Generate `0x80` to `0xBF`** from the operation index and source index in theory
section 2, and the eight immediate opcodes `11 ooo 110` alongside them, since
they share the operation dispatch and differ only in where the operand comes
from.

`ADC` and `SBC` need the current carry flag as a third input; `CP` discards the
result and keeps the flags.

**Then `INC r` and `DEC r`**, sixteen opcodes from the `00 rrr 100` and
`00 rrr 101` patterns. Remember they do not write `C`, which your flag record
expresses as `None`.

### 6. 16-bit loads and arithmetic

| Opcodes | Instruction | Cycles | Flags |
| --- | --- | --- | --- |
| `0x01` `0x11` `0x21` `0x31` | `LD rr, d16` (`BC` `DE` `HL` `SP`) | 12 | none |
| `0x08` | `LD (a16), SP` | 20 | none |
| `0x03` `0x13` `0x23` `0x33` | `INC rr` | 8 | none |
| `0x0B` `0x1B` `0x2B` `0x3B` | `DEC rr` | 8 | none |
| `0x09` `0x19` `0x29` `0x39` | `ADD HL, rr` | 8 | `N=0`, `H` at bit 11, `C` at bit 15, `Z` unchanged |

`LD (a16), SP` writes two bytes, low first. You have `Bus.write16` from Step 03,
but `CPU.bus` is typed as the `MemoryDevice` protocol, which declares only `read`
and `write`. Two honest options: write the two bytes from the instruction body,
or widen the protocol. Prefer the first today. A protocol should describe what
the CPU needs from a bus, and everything the CPU needs it can build from `read`
and `write`.

The remaining 16-bit loads (`PUSH`, `POP`, `LD SP, HL`, `LD HL, SP+e8`) are Step
06, because they are about the stack rather than about arithmetic.

### 7. `DAA`, `CPL`, `SCF`, `CCF`

Four opcodes, 4 cycles each: `0x27`, `0x2F`, `0x37`, `0x3F`. Theory sections 5
and 7 have the rules. `CPL` is a bitwise NOT of `A`, masked to 8 bits.

Put `DAA`'s logic in `alu.py` with the rest of the arithmetic. It takes `A` and
the three flags it reads, and returns the adjusted `A` and the flags it writes.

### 8. The rotate instructions are deliberately not here

`RLCA`, `RRCA`, `RLA` and `RRA` (`0x07`, `0x0F`, `0x17`, `0x1F`) look like they
belong in this step. They are going to Step 07 instead, with the 256
CB-prefixed opcodes, because they are the same four rotations as `RLC A`,
`RRC A`, `RL A` and `RR A` with one difference: the CB forms set `Z` from the
result, and these four always clear it. Implementing them twice, in two steps,
is how that difference turns into a bug. Implement them once, next to their
twins, with the `Z` rule as a parameter.

A ROM that hits `0x07` before Step 07 will raise, which is correct.

### 9. Tests

The suite grows a lot here. Organise it around what can be wrong rather than
around opcodes.

**The flag rules, in `tests/test_alu.py`.** No CPU anywhere in this file. One
parametrized test per operation, with cases chosen at the boundaries: the
half-carry cases are `0x0F + 0x01` and `0x10 - 0x01`; the carry cases are
`0xFF + 0x01` and `0x00 - 0x01`; the zero cases are anything that lands on zero.
Add the `ADC` case where the carry alone causes the half-carry
(`0x0F + 0x00 + 1`), because that is the bug from theory section 4.

**The generated tables, in `tests/test_cpu.py`.** Do not test 64 loads
individually. Test the generation instead:

- every opcode in `0x40` to `0x7F` except `0x76` is in the table, and `0x76` is
  not
- a handful of specific entries decode to the right operands: `0x47` is
  `LD B, A`, `0x7E` is `LD A, (HL)`, `0x70` is `LD (HL), B`
- cycle costs follow the rule: a sample with no `(HL)` reports 4, one with `(HL)`
  reports 8, `INC (HL)` reports 12
- the closure trap from theory section 9 is caught by testing two different
  entries from the same generated block, which is the minimum that would fail if
  every entry had captured the same index

**The flags reach the registers.** `alu.py` is tested in isolation, so `cpu.py`
needs only to prove it applies what it gets: one test that an operation writing
`None` for `C` leaves a set carry flag set, and one that a `False` clears it.

**A handmade program.** The payoff test. Assemble a few instructions by hand into
the `cpu_running` fixture and assert on the final register state:

```python
cpu = cpu_running(0x3E, 0x3C, 0x06, 0x18, 0x80)  # LD A,0x3C; LD B,0x18; ADD A,B
```

Step it three times, assert `A` is `0x54` and the flags are what section 5 says.
Then a second program that overflows, so `C` and `Z` both end up set.

These have to be straight-line programs, since conditional jumps are Step 06 and
without them a loop cannot terminate.

### 10. Run a real ROM

No new CLI flag. `--trace 12` on a real cartridge is the acceptance criterion,
and the goal listing at the top of this document is what it should print.

When it stops early on an opcode from this step's tables, `--dump` at the address
in the error and read the surrounding bytes. That loop, trace until it stops,
dump where it stopped, is the debugging workflow for the rest of the project.

---

## Hints

- Generate the tables at module import time, in a function that builds and
  returns the dict, rather than by mutating a module-level dict from module-level
  loops. A function keeps its loop variables out of the module namespace, and it
  is the difference between `OPCODES: Final[dict[int, Instruction]] = _build()`
  and a module that has `dest` and `src` lying around in it forever.
- When a generated instruction misbehaves, print the table entry rather than
  reasoning about the generator: `OPCODES[0x47]` shows you the name and the
  cycles, and if the name is right and the behaviour is wrong, the bug is in the
  body rather than in the encoding.
- `bits.u8(-1)` is `0xFF`, because Python's `&` on a negative integer works on
  its two's-complement representation, which is infinite to the left. Subtraction
  therefore needs no special handling before masking. Verify it in a REPL once
  and then trust it.
- If mypy complains that `bool | None` is not `bool` when you apply flags, that
  is the `is None` check from theory section 6 missing, not mypy being difficult.
- The opcode table at <https://gbdev.io/gb-opcodes/optables/> shows flags per
  instruction as `Z N H C`, where `-` means unchanged and `0`/`1` mean forced.
  Cross-check theory section 5 against it before writing any code; if the two
  disagree, the table on the web is right and this document has a typo worth
  reporting.
- Sixteen `INC`/`DEC` opcodes, eight registers, two operations. If you find
  yourself writing the eighth one by hand, stop and go back to the loop.

---

## Acceptance criteria

- [ ] `uv run python -m gameboy rom.gb --trace 12` runs nine instructions and
      stops on an unknown opcode that belongs to Step 06. On Tetris that is
      `0x20` at `0x0216`, and `HL` has walked from `0xDFFF` to `0xDFFE`.
- [ ] `XOR A` sets `Z` and clears the other three flags.
- [ ] `INC B` when `B` is `0xFF` leaves `B` at `0x00` with `Z` and `H` set, and
      leaves `C` exactly as it was.
- [ ] `ADD A, B` with `A = 0x0F` and `B = 0x01` sets `H` and not `C`; with
      `A = 0xFF` and `B = 0x01` sets `Z`, `H` and `C`.
- [ ] `ADC A, B` with `A = 0x0F`, `B = 0x00` and carry set sets `H`.
- [ ] `AND` leaves `H` set; `OR` and `XOR` leave it clear.
- [ ] `ADD HL, BC` computes its half-carry at bit 11 and does not touch `Z`.
- [ ] `CP` leaves `A` unchanged and sets the same flags `SUB` would.
- [ ] `DAA` after `LD A, 0x37` / `ADD A, 0x05` leaves `A` at `0x42`.
- [ ] `0x76` is absent from the table and raises `UnknownOpcodeError`.
- [ ] Every generated instruction's name names its operands, and the trace lines
      up in columns.
- [ ] `alu.py` imports nothing from `cpu.py`, and `tests/test_alu.py` constructs
      no `CPU`.
- [ ] No `ValueError` from the `Registers` guard anywhere in the test suite,
      which is the proof that every arithmetic path masks.
- [ ] `uv run pytest` is green, `uv run ruff check .`,
      `uv run ruff format --check .` and `uv run mypy` are clean.

---

## Questions to ask yourself before moving on

1. `INC` does not write `C` and `ADD` does. Where in your code is that fact
   stated, and is it stated once?
2. You now have two things that know an instruction's cycle count: the table and
   the rule that generated it. Is that a violation of the one-source-of-truth
   rule from Step 04, or not, and why?
3. A generated `LD` body receives its operands through `partial`. What would fail,
   and how visibly, if you had used a lambda without the default-argument trick?
4. Step 06 adds conditional jumps, which take one cycle count when taken and
   another when not. You now have 180 instructions with a fixed `cycles` field.
   What is the smallest change that admits the variable ones?
5. `CP` is `SUB` with the result discarded. If you implemented it by calling your
   `sub` and ignoring the result, what did that cost you at runtime, and would
   you be able to measure the difference?

When these pass, ping me and I will review before Step 06, where the stack
arrives and the CPU learns to call a subroutine.
