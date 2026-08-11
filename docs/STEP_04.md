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

A "nibble" is four bits, so a byte is two nibbles: the top one is bits 7 to 4 and
the low one is bits 3 to 0. `F` is one byte, but only its top nibble exists:

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

The low nibble is not "usually zero", it is **physically absent**. A latch, or
flip-flop, is the circuit that stores one bit; the chip has four of them wired up
for the top nibble and none at all for the low one, so those four bits can never
hold a value.

The consequence you can observe: write `0xFF` to `F` (which you can only do via
`POP AF`) and read it back, and you get `0xF0`. That is a real behaviour that
Blargg's test ROMs check, so it belongs in your setter, not in a comment.

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
    opcode = self.fetch_u8()  # read at PC, then PC += 1
    instruction = OPCODES[opcode]  # decode
    instruction.execute(self)  # execute, may move PC again
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


def fetch_u16(self) -> int: ...  # two fetch_u8 calls, low byte first
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

These are written out at length on purpose. Every term is defined where it is
used, and no sentence mixes a hardware fact with a Python mechanism. If a section
covers something you already know, skip it; the length is there so that nothing
requires a second reading to parse.

### 0. Carry-over from Step 03: the hexdump

`--dump ADDR --length N` never landed, and two of Step 03's acceptance criteria
depend on it. Do it first. It takes twenty minutes, it exercises the bus you just
built, and you will want it within the hour to look at whatever byte the CPU
chokes on. Step 03 task 9 has the output format.

### 1. `src/gameboy/cpu.py`: the `Registers` class

**What this class is.** A plain container for the CPU's state. It holds numbers
and booleans and nothing else. It does not know about the bus, it does not
execute anything, and it has no idea what an instruction is. Keeping it separate
from `CPU` means your tests can build one, poke at it, and assert on it without
constructing a bus or a cartridge.

**What it stores.** Nine numbers and four booleans:

| Attribute | Range | Meaning |
| --- | --- | --- |
| `a` | 0 to 255 | the accumulator |
| `b`, `c`, `d`, `e`, `h`, `l` | 0 to 255 | general purpose |
| `sp` | 0 to 65535 | stack pointer |
| `pc` | 0 to 65535 | program counter |
| `z`, `n`, `h_flag`, `c_flag` | `True` / `False` | the four flags |

Note the awkwardness in that last row, and deal with it now rather than
discovering it halfway through. The register named `H` and the half-carry flag
named `H` are different things, and so are `C` the register and `C` the carry
flag. They collide in any naming scheme that uses bare letters for both. Pick one
of these and apply it everywhere:

- registers keep bare letters, flags get a prefix: `h` and `flag_h`
- flags keep bare letters, registers get a prefix: `reg_h` and `h`

The first reads better at the call sites you will write most often, which are
register accesses. Whatever you pick, do not mix them.

**How to declare it in Python.** Use `@dataclass`. Write each attribute as a name,
a colon, a type, and a default value:

```python
@dataclass(slots=True)
class Registers:
    a: int = 0
```

Three things about that:

- The decorator reads those annotated lines and generates an `__init__` that
  assigns each one. Without the decorator, a line like `a: int` is an annotation
  and nothing more: no attribute is created, and `Registers().a` raises
  `AttributeError`. You met the mirror of this bug in `Bus`, where an assignment
  *without* an annotation became a class attribute shared by every instance.
- Do **not** pass `frozen=True`. `Cartridge` is frozen because a ROM image never
  changes. Registers change on almost every instruction, so this class must be
  mutable.
- `slots=True` makes attribute access slightly faster and instances smaller, and
  it is the same option you used on `Cartridge`. It has one consequence that
  matters here, covered in task 2.

**Give every attribute a default of `0` or `False`.** A `Registers()` with no
arguments is then valid, which is what your unit tests will want. The real
starting values come from task 4, not from these defaults.

### 2. The `f` property

**The hardware fact.** `F` is a single byte, and only its top four bits exist. A
"nibble" is four bits, so the top nibble is bits 7, 6, 5 and 4. Those four bits
are the flags:

```
bit     7     6     5     4     3     2     1     0
      [ Z ] [ N ] [ H ] [ C ] [ - ] [ - ] [ - ] [ - ]
       128    64    32    16      always read as 0
```

Bits 3 to 0 are not "conventionally zero". There is no storage there at all. The
chip has four flip-flops wired up for the top four bits and nothing wired up for
the bottom four, so those bits can never hold a value. A flip-flop, or latch, is
the circuit that physically stores one bit; the low nibble has none.

**What you are storing in Python.** Four separate `bool` attributes, one per flag,
declared in task 1. There is no byte anywhere in your object. Nothing stores `F`.

**What the getter must do.** A few instructions want all four flags as a single
byte, laid out as in the diagram. The getter builds that byte on demand. Each
flag that is `True` contributes the value of its bit position; each flag that is
`False` contributes nothing:

```
z = True, n = False, h = True, c = True

    128  (bit 7, because z is True)
  +   0  (bit 6, because n is False)
  +  32  (bit 5, because h is True)
  +  16  (bit 4, because c is True)
  = 176, which is 0xB0
```

You can express that as additions, as `<<` and `|`, or with `bits.set_bit`. They
are the same arithmetic. Pick the one you find clearest and use the same style
for the pair properties in task 3.

**What the setter must do.** It receives a byte and performs the reverse: for each
of the four bit positions, decide whether that bit is set, and store the answer
as a `bool`. `bits.get_bit(value, 7)` already returns a `bool`, which is exactly
the shape you need.

**Why the low nibble needs no code.** Because the setter only ever inspects bits 7
to 4, the incoming byte's bottom four bits are ignored automatically. You do not
need to mask them off. Write a comment saying so, because to a later reader it
looks like an oversight rather than a decision.

**The observable consequence,** which is what your test asserts: assign `0xFF`,
read back `0xF0`.

**The `slots` collision.** With `slots=True`, every annotated attribute becomes a
fixed storage slot on the class. A property is also stored on the class, under
its own name. If a slot and a property share a name, one silently wins and you
get an attribute that either never stores or never computes. So there must be no
attribute named `f` in task 1. `f` exists only as a property.

### 3. The pair properties

**The hardware fact.** The eight-bit registers are wired together in pairs, and
several instructions address a pair as one sixteen-bit number. The four pairs are
`AF`, `BC`, `DE` and `HL`. In each pair the first letter is the high byte:

```
b = 0x12       c = 0x34
bc = 0x1234
     ^^ ^^
     b  c
```

**What you are writing in Python.** Four properties named `af`, `bc`, `de` and
`hl`, each with a getter and a setter. They store nothing. Reading `regs.bc`
runs code that combines `b` and `c`; writing `regs.bc = 0x1234` runs code that
splits the value back into `b` and `c`.

You already have all three helpers in `bits.py`: `join_bytes(high, low)` builds
the sixteen-bit value, `high_byte(value)` and `low_byte(value)` take it apart.

The mechanism, for one pair:

```python
@property
def bc(self) -> int:
    return bits.join_bytes(self.b, self.c)


@bc.setter
def bc(self, value: int) -> None:
    self.b = bits.high_byte(value)
    self.c = bits.low_byte(value)
```

`@bc.setter` reads oddly the first time. After the getter is defined, the name
`bc` refers to a `property` object. `.setter` is a method on that object which
returns a new property carrying both halves. That is why both functions must
share the name `bc`.

**Why the pairs are not stored as fields.** It is tempting to also keep a `bc`
attribute and update it alongside `b` and `c`. Do not. Then `LD B, 5` has to
remember to update two places, and the day it does not, `b` and `bc` disagree.
One source of truth per fact.

**`AF` is the special one.** Its low half is the flag byte, which does not exist
as storage. So `af`'s setter must pass the low byte through the `f` setter from
task 2 rather than assigning it anywhere directly. That keeps the "low nibble
does not exist" rule stated in exactly one place. The test for this: assign
`0x12FF` to `af`, read back `0x12F0`.

**Masking, and why it is the setter's job.** Python integers have no fixed width
and never overflow. `0xFF + 1` is `0x100`, not `0`. The hardware wraps; Python
does not. So somebody has to apply the wrap, and that somebody is the setter,
using `bits.u8` for the eight-bit registers and `bits.u16` for `sp`, `pc` and the
pairs.

Put it in the setter rather than at the call sites. There will eventually be
hundreds of call sites and eight setters, and a rule enforced in eight places
beats the same rule remembered in hundreds.

This means the eight-bit registers need setters too, not just the pairs. Writing
eight nearly identical property pairs by hand is tedious and you may reasonably
decide the masking belongs elsewhere. Two escape hatches worth knowing about:
`__setattr__`, which intercepts every attribute assignment on the object, and
`dataclasses.field` with a custom descriptor. Both are more machinery than this
step needs. Write them out by hand today; revisit if it annoys you.

### 4. `Registers.post_boot()`

**The hardware fact.** A real Game Boy runs a 256-byte boot ROM before the
cartridge gets control. It scrolls the logo, plays the chime, checks the header
checksum you implemented in Step 02, and jumps to `0x0100`. We do not emulate it
(that was a Step 03 decision), so we have to fabricate the register values it
would have left behind. Section 4 of the theory above has the table and explains
which of those values are meaningful.

**What you are writing in Python.** A `@classmethod` that constructs and returns a
`Registers` with those values already set.

```python
@classmethod
def post_boot(cls) -> Self: ...
```

`cls` is the class itself, arriving as an explicit first parameter, the same way
`self` is the instance. You met it in `Cartridge.from_bytes`. Return `cls(...)`
rather than `Registers(...)` so a subclass would get its own type back, and
annotate the return as `Self`.

**One wrinkle in the data.** `F` is `0xB0` on a cartridge whose header checksum
byte is non-zero, and `0x80` when that byte is `0x00`, because the flags are left
over from the boot ROM's checksum comparison. Do not model that today. Leave a
`TODO` on the method with one line explaining when it would matter, and a link to
[Pan Docs' Power Up Sequence](https://gbdev.io/pandocs/Power_Up_Sequence.html).

**The test:** `post_boot().af` is `0x01B0`, and `post_boot().pc` is `0x0100`.

### 5. `UnknownOpcodeError`

**The situation it describes.** The CPU fetched a byte, looked it up in the
opcode table, and found nothing there. Either you have not implemented that
instruction yet, or `PC` has wandered into data and is executing bytes that were
never meant to be instructions. Theory section 8 argues why this raises rather
than being ignored.

**What you are writing in Python.** An exception class carrying two pieces of
data: the opcode byte, and the address it was fetched from.

```python
class UnknownOpcodeError(Exception):
    def __init__(self, opcode: int, address: int) -> None:
        super().__init__(f"unknown opcode 0x{opcode:02X} at 0x{address:04X}")
        self.opcode = opcode
        self.address = address
```

`super().__init__(message)` is what makes `str(error)` return that text; it is the
base class that stores the message. Storing `opcode` and `address` as attributes
as well means a caller can inspect them without parsing the string.

**Why the address is the important half.** It is what you feed to `--dump` to see
what `PC` actually walked into. Note that it must be the address the opcode was
*read from*, not the current value of `pc`, because fetching has already moved
`pc` past it by the time you raise. Capture it before you fetch.

### 6. The `CPU` class

**What it holds.** Two things: a memory bus, and a `Registers`. That is the entire
state of the machine as far as this step is concerned.

**How to type the bus parameter.** Use `MemoryDevice`, the `Protocol` you declared
in Step 03, not `Bus`. A protocol describes a shape rather than a class: anything
with a `read` and a `write` of the right signatures satisfies it, with no
inheritance and no registration. The CPU genuinely only needs those two methods.

The practical payoff is in your tests. A test that drives the CPU over a small
fake object with a `read` method is much easier to write than one that builds a
32 KiB ROM image and a cartridge. This is the protocol from Step 03 paying for
itself, one step later.

**The two fetch helpers.** `fetch_u8` does three things in order: read the byte at
`pc`, advance `pc` by one, return the byte. Advancing must wrap, so it goes
through `bits.u16`.

`fetch_u16` reads two bytes and combines them into one sixteen-bit value. The
Game Boy stores sixteen-bit values with the low byte first, so the first byte you
read is the low half. Write it as two calls to `fetch_u8` rather than reaching
into the bus directly: in Step 09 every bus access will tick the clock, and a
composition that is honest today gets the timing right for free then.

There is a real trap in `fetch_u16`. `bits.join_bytes` takes the high byte first,
but you read the low byte first. If you write both fetches inline as arguments,
Python evaluates arguments left to right and the two reads happen in the wrong
order. Bind the first byte to a local variable, then fetch the second. The bug is
invisible on inspection and your little-endian test will catch it.

**`step`.** Theory section 5 has the four-line sketch. Fetch an opcode, look it up,
call it, return its cycle count. It should contain no `if` statement about
opcodes: if you find yourself special-casing one, the table is the wrong shape.

Do **not** add a `run()` method that loops. The loop belongs to whoever owns the
whole machine, because from Step 09 onward it also has to tick the timer with the
number `step` returns. Two candidates for that owner later: a `Machine` class, or
the CLI. Leaving it out today keeps the choice open.

### 7. The opcode table

**What a table is here.** A mapping from a byte to a description of what that byte
means. Theory section 7 compares the options and lands on a dict.

**The `Instruction` record.** A frozen dataclass with three fields: a name for
tracing, a cycle count, and the function that performs the instruction.

```python
@dataclass(frozen=True, slots=True)
class Instruction:
    name: str
    cycles: int
    execute: Callable[["CPU"], None]
```

`Callable[["CPU"], None]` is the type of "a function taking a CPU and returning
nothing". `Callable` is imported from `collections.abc`, not from `typing`. The
quotes around `"CPU"` make it a forward reference, which you need if `Instruction`
is defined above `CPU` in the file.

**The two entries.**

`0x00` is `NOP`, 4 cycles. Its body does nothing. This is worth a comment,
because an empty function usually means an unfinished one. Here the emptiness is
the instruction: `NOP` exists precisely to consume four cycles and advance `PC`
by one, and `PC` was already advanced by the fetch.

`0xC3` is `JP a16`, 16 cycles. `a16` means the instruction is followed by a
sixteen-bit address, stored low byte first. Its body reads that address with
`fetch_u16` and assigns it to `pc`. Nothing else. Note that `fetch_u16` has
already moved `pc` past the two operand bytes by the time you assign, which is
harmless because you are overwriting `pc` anyway. That is the same fact that
makes jumps simple in general: nothing needs to be undone.

**Where to put the dict.** Module level, annotated `Final`, defined after the
`CPU` class so the references resolve. `Final` tells mypy that the name is never
rebound; it does not make the dict itself immutable.

**Look up with `.get`, not `[...]`.** A missing key with `[...]` raises
`KeyError`, which says nothing useful. `.get` returns `None`, and you turn that
`None` into your own `UnknownOpcodeError` with the opcode and address in it.

### 8. CLI: `--trace N`

**What it does.** Builds the machine and runs it for N instructions, printing one
line per instruction so you can watch `PC` move.

**The order of construction:** read the cartridge from disk, wrap it in a `Bus`,
build a `CPU` over that bus with `Registers.post_boot()`.

**The output format.** One line per step:

```
0100  00  NOP        A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  4
0101  C3  JP a16     A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  16
0150  ...
```

Left to right: the address the instruction was fetched from, the opcode byte, the
instruction's name, the register values, and the cycle count.

**The ordering problem this creates.** The address and the opcode have to be read
*before* stepping, because stepping moves `pc`. The register values and the cycle
count only exist *after*. So the loop body reads `pc`, peeks at the opcode with
`bus.read` (peeking, not fetching, so `pc` does not move), calls `step`, and then
formats the line from a mixture of both.

Peeking means you look up the same opcode twice per instruction, once for the
trace and once inside `step`. That is fine here. If it ever bothers you, the
alternative is for `step` to return a small record instead of a bare `int`, which
is a change to make when a second caller wants the same information, not before.

**Handle the error.** Wrap the loop in `try` / `except UnknownOpcodeError`. Print
the exception, return a non-zero exit code, and do not let a traceback reach the
terminal. Hitting an unimplemented opcode is the *expected* outcome today, since
you have implemented two instructions. It should read as a stopping point, not as
a crash.

**Wiring the argument.** `--trace` takes a count, so `type=int` and
`default=None`. Guard with `is not None` rather than truthiness, since `--trace 0`
is a legitimate if useless request and `0` is falsy. Same trap as `--dump 0x0000`.

### 9. Tests in `tests/test_cpu.py`

Group them by what they pin down. Twelve or so, in four clusters.

**The pair properties compose and decompose.** Set `b` and `c` as bytes, assert
`bc` reads back as the combined value. Then the reverse: assign to `bc`, assert
`b` and `c` hold the right halves. One test per direction is enough; you do not
need all four pairs twice.

**The flag byte packs and unpacks correctly.** That each flag lands in the right
bit is four assertions, which parametrizing handles well: a list of
`(flag_name, expected_byte)` pairs, one case per flag. Then two tests for the
missing low nibble: assigning `0xFF` to `f` reads back `0xF0`, and assigning
`0x12FF` to `af` reads back `0x12F0`.

**Values wrap at the right width.** Assigning `0x1FF` to an eight-bit register
leaves `0xFF`. Assigning `0x10000` to `hl` leaves `0x0000`. Fetching at `0xFFFF`
leaves `pc` at `0x0000` rather than `0x10000`. That last one is the important
one: it is the only test that proves the fetch path wraps, and wrapping is what
stops a runaway `PC` from raising `IndexError` somewhere unrelated.

**The instruction cycle works.** `post_boot` matches the Pan Docs table.
`fetch_u8` returns the byte at `pc` and advances `pc` by one. `fetch_u16` is
little-endian and advances by two. `NOP` advances `pc` by one and returns 4.
`JP a16` sets `pc` to its operand and returns 16. An unknown opcode raises, and
the exception's `address` attribute is the opcode's own address rather than the
incremented `pc`.

**A fixture for programs.** Several of those tests need a CPU whose memory
contains a specific sequence of bytes. Writing that inline is five lines of
`bytearray` surgery per test, repeated. Add a helper to `conftest.py` that takes
the bytes and returns a ready CPU, so a test opens with something like:

```python
cpu = cpu_running(0x00, 0xC3, 0x50, 0x01)
```

Two ways to build it, and the choice is yours. Put the bytes into a ROM image at
the entry point and wrap it in a real `Cartridge` and `Bus`, which reuses the
fixtures you already have. Or write a fake device holding a `bytearray`, which is
shorter and leans on the `MemoryDevice` protocol. The second is closer to what
the tests are actually about, since none of these tests care about cartridge
headers.

---

## Hints

The tasks cover the traps in place. These are the ones with nowhere else to live.

- `Callable` lives in `collections.abc`, not `typing`, since 3.9. Ruff's `UP`
  rules will tell you if you get it wrong, which is one of the reasons they are
  enabled.
- If an attribute mysteriously stops updating, it is the `slots` and property
  name collision from task 2. It fails silently, so it does not look like the
  cause of anything.
- `0xC3` is the only jump you are implementing. Resist adding `JR`, `CALL` or
  the conditional forms: they are Step 06, and conditional jumps have two
  different cycle counts, which changes the shape of `Instruction`. Meet that
  problem when you have to.
- For the trace output, `f"{value:02X}"` and `f"{value:04X}"` are the whole
  formatting vocabulary you need. Ruby's `%02X` with different punctuation.
- When something does not behave, print the registers rather than reasoning
  about them. `Registers` is a dataclass, so it has a generated `__repr__` that
  shows every field, and `print(cpu.registers)` in a test tells you more in one
  line than reading the setter again does.

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
