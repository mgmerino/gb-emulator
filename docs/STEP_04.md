# Step 04 — CPU state and the fetch-decode-execute skeleton

## Goal

Build the object that drives everything else. By the end of this step you will
have a `CPU` holding the SM83's ten registers, starting in the state the boot
ROM would have left behind, able to fetch an opcode from the bus you built in
Step 03, look it up in a table, execute it, and report how many cycles it took.
It will know two instructions: `NOP` and `JP a16`. That is enough to run the
first two instructions of every commercial Game Boy game and watch the program
counter land where the cartridge told it to.

> **Visual companion:** none yet. If the flag register or the instruction cycle
> is still fuzzy when you finish, say so and I will draw one before Step 05,
> where flags become the whole game.

---

## Theory

### 1. A CPU emulator is a struct and a loop

Strip away the mystique and an interpreting CPU emulator is two things:

```
state:  ten registers and a handful of booleans
loop:   read a byte at PC, decide what it means, do it, report the cost
```

That is the entire design. Everything hard about a CPU emulator is either
*correctness of the individual instructions* (Steps 05 to 07) or *agreeing on
time with the rest of the machine* (Steps 08 and 09). The skeleton itself is
small, and it is worth building it deliberately now, because in Step 05 you are
going to add roughly 250 instructions on top of it and every structural mistake
gets multiplied by 250.

The one thing to get right today is the **seam**: `step()` executes exactly one
instruction and returns the number of cycles it consumed. Nothing else. No
rendering, no interrupt servicing, no timers. Those get bolted onto the return
value later, by the owner of the loop, not by the CPU.

### 2. The registers

The SM83 has seven 8-bit general-purpose registers, one flag register, and two
16-bit registers:

| Register | Width | Conventional use |
| --- | --- | --- |
| `A` | 8 | The accumulator. Every ALU result lands here |
| `F` | 8 | Flags. Not addressable directly, only through `AF` |
| `B`, `C` | 8 | General purpose. `C` doubles as an I/O offset in `LDH (C), A` |
| `D`, `E` | 8 | General purpose |
| `H`, `L` | 8 | General purpose, but `HL` is *the* pointer register |
| `SP` | 16 | Stack pointer. Grows downwards |
| `PC` | 16 | Program counter. The address of the next byte to fetch |

The 8-bit registers pair up into four 16-bit views: `AF`, `BC`, `DE`, `HL`. The
first of the pair is the high byte. `B = 0x12`, `C = 0x34`, therefore
`BC = 0x1234`.

These pairs are not a convenience the assembler invented; they are wired that
way. `LD BC, d16` writes both halves in one instruction, `INC BC` increments the
pair as a single 16-bit number (and, unlike `INC B`, touches no flags), and
`LD A, (HL)` uses the pair as an address. So the pairs need to be first-class in
your representation, not something the caller reassembles by hand.

Which leaves the representation choice:

| Approach | `B` costs | `BC` costs | Verdict |
| --- | --- | --- | --- |
| Eight 8-bit fields, pairs as properties | a field read | a shift and an or | **Start here** |
| Four 16-bit fields, halves as properties | a shift and a mask | a field read | defensible, but 8-bit access is far more common |
| One `bytearray(8)` plus index constants | an index | two indexes | fast, unreadable, and mypy learns nothing |

Go with the first. Eight-bit access dominates by a wide margin, and the pairs
read fine as properties.

### 3. The flag register is four bits and four holes

`F` is one byte, but only its top nibble exists:

```
bit    7     6     5     4     3  2  1  0
       Z     N     H     C     0  0  0  0
```

| Flag | Name | Set when |
| --- | --- | --- |
| `Z` | Zero | the result was 0. The flag every conditional jump reads |
| `N` | Subtract | the last ALU op was a subtraction. Only `DAA` ever reads it |
| `H` | Half carry | a carry crossed bit 3 into bit 4. Only `DAA` ever reads it |
| `C` | Carry | a carry left bit 7, or a borrow was needed |

The low nibble is not "usually zero", it is **physically absent**. There are no
latches there. Write `0xFF` to `F` (which you can only do via `POP AF`) and read
it back and you get `0xF0`. That is a real behaviour that Blargg's test ROMs
check, so it belongs in your setter, not in a comment.

`N` and `H` exist almost entirely for `DAA`, the decimal-adjust instruction used
by games that store scores as binary-coded decimal. You will implement it in
Step 05, hate it briefly, and then never think about those two flags again.

Representation, again a choice:

| Approach | Cost | Verdict |
| --- | --- | --- |
| Four `bool` fields, `f` as a packing property | flag reads are free, `PUSH AF` packs | **Start here** |
| One `int` field, flags as bit properties | every flag read is a mask and a compare | closer to hardware, worse to read |
| `enum.IntFlag` | pretty, but you still mask and shift | leave it |

Instructions touch individual flags constantly (`Z` alone gets read by half the
conditional jumps) and touch `F` as a byte exactly twice, in `PUSH AF` and
`POP AF`. Optimise the representation for the common case: four booleans, and
one property that assembles the byte when someone finally asks for it.

Ruby note: `attr_accessor :z` would give you the four booleans and nothing else.
Python's `@property` is the same idea as writing `def f; ...; end` and
`def f=(v); ...; end` by hand, except that the getter and setter pair is
declared together and mypy can check both sides.

### 4. Where the CPU starts, and why `F` is `0xB0`

Real hardware runs a 256-byte boot ROM first: it scrolls the logo, plays the
chime, verifies the header checksum you computed in Step 02, and then jumps to
`0x0100`. We are skipping it (Step 03 decision), so we have to fabricate the
state it would have left behind.

For the DMG:

| Register | Value |
| --- | --- |
| `A` | `0x01` |
| `F` | `0xB0` |
| `B` | `0x00` |
| `C` | `0x13` |
| `D` | `0x00` |
| `E` | `0xD8` |
| `H` | `0x01` |
| `L` | `0x4D` |
| `SP` | `0xFFFE` |
| `PC` | `0x0100` |

Three of those are meaningful and the rest are litter:

- **`PC = 0x0100`** is the entry point. The boot ROM's last instruction jumps
  there.
- **`SP = 0xFFFE`** is the top of HRAM. The stack grows downwards from the
  highest usable byte, and `0xFFFF` is `IE`, so the top of the stack is one
  below it.
- **`F = 0xB0`** means `Z=1, N=0, H=1, C=1`, and it is *not* arbitrary. The boot
  ROM's last act before jumping is the header checksum comparison from Step 02.
  `H` and `C` are set as a side effect of that subtraction. On a cartridge whose
  header checksum byte is `0x00`, the comparison comes out differently and
  `F = 0x80` instead.

Everything else is whatever happened to be in the registers when the boot ROM
finished. `A = 0x01` is the DMG's console-type marker, which is why some games
read it: on a Game Boy Color the boot ROM leaves `0x11` there instead.

Encode the table, add a comment pointing at
[Pan Docs' Power Up Sequence](https://gbdev.io/pandocs/Power_Up_Sequence.html),
and do not model the `F = 0x80` special case today. Leave it as a `TODO` on the
constructor with one line explaining when it would matter.

### 5. Fetch, decode, execute

```python
def step(self) -> int:
    opcode = self.fetch_u8()          # read at PC, then PC += 1
    instruction = OPCODES[opcode]     # decode
    instruction.execute(self)         # execute, may move PC again
    return instruction.cycles
```

Three details in that sketch matter more than they look:

**PC advances before execution, not after.** By the time an instruction's body
runs, `PC` already points at its first operand byte. That is what lets
`JP a16`'s body simply call `fetch_u16()` and get the destination: it reads the
two bytes sitting right there and leaves `PC` past them. It is also why a jump
can just assign `PC` without worrying about being "corrected" afterwards. If you
instead advanced `PC` by the instruction's length *after* executing, every jump
would have to undo it, and you would have two things that move `PC` fighting
each other. One rule: **only the fetch helpers and jumps assign `PC`.**

**Operand fetching belongs to the instruction, not the dispatcher.** Instructions
are 1 to 3 bytes long, and the dispatcher does not need to know which. Give the
CPU two helpers, and instructions that need operands call them:

```python
def fetch_u8(self) -> int:
    value = self.bus.read(self.registers.pc)
    self.registers.pc = bits.u16(self.registers.pc + 1)
    return value


def fetch_u16(self) -> int:
    ...  # two fetch_u8 calls, low byte first
```

Write `fetch_u16` in terms of `fetch_u8`, for the same reason `read16` was
written in terms of `read`: in Step 09 every bus access ticks the clock, and if
the composition is honest the timing falls out for free. And note that
`fetch_u16` reads the low byte first, which is the same little-endian rule as
the bus, showing up here as an *ordering of two calls* rather than as byte
manipulation. That is the Step 01 promise still holding.

**`step` returns cycles, and that number is the clock.** Both `NOP` and
`JP a16` are boring instructions, but they take 4 and 16 cycles respectively,
and getting that wrong desynchronises the machine later in a way that is very
hard to trace back. Take the numbers from the
[opcode table](https://gbdev.io/gb-opcodes/optables/), not from intuition.

### 6. T-cycles or M-cycles: pick one now

The Game Boy's clock ticks at ~4.19 MHz. Those ticks are **T-cycles**. But the
CPU cannot do anything useful in fewer than four of them, so the hardware
literature also counts in **M-cycles** (machine cycles), where 1 M = 4 T.

`NOP` is 1 M-cycle, which is 4 T-cycles. Opcode tables print one or the other,
and sometimes both, which is exactly how people end up with an emulator that
runs at a quarter speed.

Pick **T-cycles**. Reasons:

- The PPU is documented in "dots", and one dot is one T-cycle.
- The timer's divider is documented as a 16-bit counter incremented every
  T-cycle.
- Some behaviours (OAM DMA, the exact moment an interrupt is dispatched) only
  make sense at T-cycle granularity.

Divide by four when you need M-cycles; never multiply.

Write the choice down in a module docstring. This is the kind of decision that
looks obvious for two weeks and then costs you an evening.

### 7. Decoding: a table, not a chain of `if`s

256 opcodes, plus 256 more behind the `0xCB` prefix. Options:

| Approach | Verdict |
| --- | --- |
| `if opcode == 0x00: ... elif ...` | 256 comparisons in the worst case, and unreadable at 20 entries |
| `dict[int, Instruction]` | O(1), sparse, `.get` gives you "not implemented" for free |
| `list[Instruction \| None]` of length 256 | O(1) with a cheaper lookup, dense, harder to write by hand |
| Structural decoding on the bit pattern | The real answer for Step 05, premature today |

Start with the dict. Step 05 is where the fourth option earns its keep: the
SM83's opcode map is highly regular (the 64 opcodes from `0x40` to `0x7F` are
almost all `LD r, r'`, with the source in the low three bits and the destination
in the next three), so you will generate whole blocks rather than typing 250
entries. Building that generator against a dict you can already read and test is
much easier than building it against nothing.

An `Instruction` record with a name, a cycle count and a callable is enough:

```python
@dataclass(frozen=True, slots=True)
class Instruction:
    name: str
    cycles: int
    execute: Callable[["CPU"], None]
```

Deliberately absent: `length`. It is tempting to store it, and then you have two
things that know how far `PC` should move (the length field and the fetch calls
inside the body) and only one of them is right. The disassembler in Step 16 will
want lengths, and it can have its own table then. One source of truth per fact.

### 8. Unknown opcodes should raise, even though unknown memory does not

Step 03's rule was: an unimplemented read returns `0xFF`, an unimplemented write
is dropped, never raise. That rule was right there and is wrong here, and it is
worth being able to say why.

An unimplemented I/O register is a *missing feature*. The program asked the
machine a question, the machine shrugged, and the program carries on. Degrading
is the correct behaviour: the ROM gets further and you learn more.

An unknown opcode is a *lost position*. Either you have not implemented that
instruction yet, or, far more likely once the instruction set is complete, `PC`
has wandered into data because of a bug three thousand instructions ago.
Continuing from there produces an execution trace that is pure noise, and it
buries the moment things actually broke. There are eleven byte values on the
SM83 that are genuinely not instructions (`0xD3`, `0xDB`, `0xDD`, `0xE3`, `0xE4`,
`0xEB`, `0xEC`, `0xED`, `0xF4`, `0xFC`, `0xFD`); on real hardware they lock the
CPU up completely until a reset. Locking up is the hardware's way of saying the
same thing.

So: a dedicated exception carrying the opcode *and the address it was fetched
from*. The address is the whole value of the exception, because it is what you
feed to your dump command to see what `PC` actually walked into.

```python
class UnknownOpcodeError(Exception):
    def __init__(self, opcode: int, address: int) -> None:
        super().__init__(f"unknown opcode 0x{opcode:02X} at 0x{address:04X}")
        self.opcode = opcode
        self.address = address
```

Capture the address *before* fetching, since fetching moves `PC`.

### 9. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| `@property` with a setter | `af`, `bc`, `de`, `hl`, `f` are computed views over fields | `def af; end` / `def af=(v); end`, declared as a pair |
| Mutable `@dataclass` | `Registers` is state that changes constantly, so no `frozen=True` here | a `Struct` you are allowed to mutate |
| `Callable[..., None]` as a field type | instructions are values, and a function is one | a `Proc` in a hash, but type-checked |
| Custom exception with attributes | carry the opcode and address, not just a string | `class Foo < StandardError; attr_reader :opcode; end` |
| `slots=True` and properties | they collide if they share a name, which is a real trap | no equivalent, Ruby has no slots |

The `slots` trap is worth stating plainly, because you will hit it. With
`@dataclass(slots=True)`, every annotated field becomes a slot descriptor on the
class. If you also define a property with the same name, one silently wins and
you get an attribute that either never stores or never computes. So a field
named `f` and a property named `f` cannot coexist. Name the stored things
`flag_z`, `flag_n`, `flag_h`, `flag_c` (or keep `z`, `n`, `h`, `c` as fields and
expose only `f` as a property, which is the cleaner version) and there is no
collision to worry about.

---

## Tasks

### 0. Carry-over from Step 03: the hexdump

`--dump ADDR --length N` never landed, and two of Step 03's acceptance criteria
depend on it. Do it first: it is twenty minutes, it exercises the bus you just
built, and you are about to want it for debugging the CPU anyway. Step 03 task 9
has the format.

### 1. `src/gameboy/cpu.py`: `Registers`

A mutable dataclass with `a`, `b`, `c`, `d`, `e`, `h`, `l` (8-bit), `sp` and
`pc` (16-bit), and the four flags as `bool`s. Defaults of `0` / `False` are fine.

### 2. The `f` property

Getter packs the four booleans into the top nibble. Setter unpacks, and the low
nibble is discarded on the way in because the hardware has no latches for it.

### 3. The pair properties

`af`, `bc`, `de`, `hl`, each with a getter and a setter. `af`'s setter must go
through the `f` setter rather than storing a byte, so the low-nibble rule is
stated once.

Mask in the setters, not at the call sites. Python integers do not wrap, so
`registers.hl = registers.hl + 1` at `0xFFFF` gives you `0x10000` and a bug that
surfaces four steps later. `u8` and `u16` from `bits.py` are exactly for this.

### 4. `Registers.post_boot()`

A `classmethod` returning the DMG table from the theory section, with a link to
Pan Docs and a `TODO` about the `F = 0x80` case.

### 5. `UnknownOpcodeError`

Carrying `opcode` and `address`.

### 6. `CPU`

Holds a bus (typed as the `MemoryDevice` protocol from Step 03, not as `Bus`)
and a `Registers`. Give it `fetch_u8`, `fetch_u16` and `step`.

### 7. The opcode table

A module-level `Final[dict[int, Instruction]]` with two entries:

- `0x00` `NOP`, 4 cycles, a body that does nothing.
- `0xC3` `JP a16`, 16 cycles, a body that sets `pc` to `fetch_u16()`.

`NOP`'s body being empty is worth a moment: it does nothing *and that is the
instruction*, so `pass` here is meaningful rather than a stub. Say so in a
comment, because in a week you will not remember which empty bodies were
deliberate.

Define the table after the `CPU` class, or use string annotations, so the
`Callable[["CPU"], None]` reference resolves.

### 8. CLI: `--trace N`

Build the cartridge, wrap it in a `Bus`, construct a `CPU` with `post_boot()`
registers, and step `N` times, printing one line each:

```
0100  00  NOP        A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  4
0101  C3  JP a16     A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  16
0150  ...
```

Address and opcode come from *before* the step, registers from after. Catch
`UnknownOpcodeError`, print it, and exit non-zero: reaching an unimplemented
opcode is the expected outcome today, and it should look like a stopping point
rather than a traceback.

### 9. Tests in `tests/test_cpu.py`

At least these:

- pairs compose and decompose: set `b`/`c`, read `bc`; set `bc`, read `b`/`c`
- `f` packs each flag into the right bit, one test per flag or one parametrized
- `f` drops the low nibble: `registers.f = 0xFF`, expect `0xF0`
- `af` round-trips through the same rule: `registers.af = 0x12FF` gives `0x12F0`
- setters mask: `registers.a = 0x1FF` gives `0xFF`, `registers.hl = 0x10000`
  gives `0x0000`
- `post_boot` matches the table, and `af` reads back as `0x01B0`
- `fetch_u8` returns the byte at `pc` and advances `pc` by one
- `fetch_u16` is little-endian and advances `pc` by two
- `pc` wraps: fetch at `0xFFFF` leaves `pc` at `0x0000`
- `NOP` advances `pc` by one and returns 4
- `JP a16` sets `pc` to the operand and returns 16
- an unknown opcode raises, and the exception's `address` is the opcode's own
  address, not the incremented `pc`

For the ones that need a program, add a conftest helper that builds a ROM image
with your bytes at the entry point and returns a bus over it, so tests read as
`cpu = cpu_running(0x00, 0xC3, 0x50, 0x01)` rather than as five lines of
`bytearray` surgery. The synthetic ROM fixture is already there; this is one
more function next to it.

---

## Hints

- The `slots` and property collision from the theory section is the trap. If an
  attribute mysteriously stops updating, that is what happened.
- `Callable` lives in `collections.abc`, not `typing`, since 3.9. Ruff's `UP`
  rules will tell you if you get it wrong, which is one of the reasons they are
  enabled.
- `bits.join_bytes(high, low)` still takes high first. `fetch_u16` reads low
  first and passes second: `join_bytes(self.fetch_u8(), low)` is wrong because
  Python evaluates arguments left to right, so the two fetches would happen in
  the wrong order. Bind the low byte to a local first. This is a real bug that
  is invisible on inspection.
- `step()` should have no `if` in it. If you find yourself special-casing an
  opcode inside `step`, the table is the wrong shape.
- Do not give `CPU` a `run()` method that loops. The loop belongs to whoever
  owns the machine, because in Step 09 it also has to tick the timer. Two
  candidates for that owner later: a `Machine`/`GameBoy` class, or the CLI.
  Leaving it out today keeps the choice open.
- Type the bus parameter as `MemoryDevice`, not `Bus`. The CPU genuinely only
  needs `read` and `write`, and a test that drives the CPU over a fake device is
  much easier to write than one that builds a cartridge. This is the `Protocol`
  from Step 03 paying for itself.
- `0xC3` is the only jump you are implementing. Resist adding `JR`, `CALL` or
  the conditional forms: they are Step 06, and conditional jumps have two
  different cycle counts, which changes the shape of `Instruction`. Meet that
  problem when you have to.
- For the trace output, `f"{value:02X}"` and `f"{value:04X}"` are the whole
  formatting vocabulary you need. Ruby's `%02X` with different punctuation.

---

## Acceptance criteria

- [ ] `uv run python -m gameboy rom.gb --trace 2` on a real ROM prints `NOP` at
      `0x0100`, then `JP a16` at `0x0101`, and the second line leaves `PC` at
      `0x0150`. You are watching the cartridge take control of the machine.
- [ ] `uv run python -m gameboy rom.gb --trace 3` stops on an
      `UnknownOpcodeError` naming an opcode and an address, without a traceback,
      with a non-zero exit code.
- [ ] `--dump` at the address from that error shows the byte the CPU choked on.
- [ ] `Registers.post_boot()` matches the Pan Docs table, and its `af` is
      `0x01B0`.
- [ ] `registers.f = 0xFF` reads back `0xF0`.
- [ ] Every register setter masks, and `pc` wraps from `0xFFFF` to `0x0000`.
- [ ] `NOP` reports 4 cycles and `JP a16` reports 16, in T-cycles, with the unit
      stated in the module docstring.
- [ ] `uv run pytest` is green, with at least twelve new tests and still no ROM
      file needed.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` are
      all clean.
- [ ] Nothing outside `fetch_u8`, `fetch_u16` and jump bodies assigns to `pc`.

---

## Questions to ask yourself before moving on

1. `step()` returns a cycle count that nobody consumes yet. Who will own the
   loop that consumes it, and what else has to exist before that loop is worth
   writing?
2. The bus never raises and the CPU does. Say the rule out loud in one sentence.
   If you cannot, one of the two is wrong.
3. You chose T-cycles. What is the first thing that would visibly break if one
   instruction in the table reported M-cycles by mistake, and how many steps
   from now would you notice?
4. `Instruction` holds a fixed `cycles`. Conditional jumps in Step 06 take 12
   cycles when not taken and 16 when taken. What is the smallest change to
   `Instruction` and `step` that handles that, and does it make the common case
   worse?
5. Flags are four booleans, and `f` is assembled on demand. If profiling in
   Step 16 said flag packing was hot, what would you measure before changing
   anything?

When these pass, ping me and I will review before Step 05, where the ALU
arrives and the flags stop being decoration.
