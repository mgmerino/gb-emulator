# Step 03 — The memory bus

## Goal

Build the object every other component will talk through. By the end of this
step you will have a `Bus` that can read and write any of the 65 536 addresses,
route each one to the right storage, mirror echo RAM, ignore writes to ROM, and
hand back 16-bit little-endian values. You will be able to point it at a real
cartridge and dump any region of the address space from the command line.

> **Visual companion:** [`memory-and-the-cartridge.html`](memory-and-the-cartridge.html).
> You read it for Step 02, but the address-space map in the middle is really a
> Step 03 diagram. Re-open that section: this whole step is about turning that
> picture into a dispatch function.

---

## Theory

### 1. The bus is the machine's only interface

The SM83 has no I/O instructions (no `IN`, no `OUT`, no port space, no DMA
controller). There is one operation:

```
read(address) -> byte
write(address, byte)
```

The cartridge, video RAM, sprite memory, sound chip, buttons, the timer and the
interrupt flags target those two calls at some address. When the CPU wants to
know which buttons are held, it reads `0xFF00`. When it wants to start a DMA
transfer, it writes to `0xFF46`. When it wants to turn the screen off, it clears
a bit at `0xFF40`.

This is why the bus comes before the CPU. Once `read`/`write` exist and route
correctly, adding the PPU in Step 11 comes down to teaching one existing branch
of the dispatch to call something new. Get the bus wrong and every component
after it inherits the mistake.

There is a second reason to build it now: the bus is the only object that sees
every access. Memory breakpoints, access logging and trace diffs against a
reference emulator (Step 16) are all a couple of lines inside `read` and
`write`, and they have nowhere else to live.

### 2. The map

| Range | Size | What lives there | Who owns it |
| --- | --- | --- | --- |
| `0x0000–0x3FFF` | 16 KiB | ROM bank 0, fixed | cartridge |
| `0x4000–0x7FFF` | 16 KiB | ROM bank 1..N, switchable | cartridge (MBC) |
| `0x8000–0x9FFF` | 8 KiB | VRAM (tiles and tile maps) | PPU |
| `0xA000–0xBFFF` | 8 KiB | External RAM, switchable | cartridge (MBC) |
| `0xC000–0xCFFF` | 4 KiB | WRAM bank 0 | console |
| `0xD000–0xDFFF` | 4 KiB | WRAM bank 1 (switchable on CGB) | console |
| `0xE000–0xFDFF` | 7.5 KiB | Echo RAM, a mirror of `0xC000–0xDDFF` | console |
| `0xFE00–0xFE9F` | 160 B | OAM, 40 sprite entries of 4 bytes | PPU |
| `0xFEA0–0xFEFF` | 96 B | Prohibited | nobody |
| `0xFF00–0xFF7F` | 128 B | I/O registers | everyone |
| `0xFF80–0xFFFE` | 127 B | HRAM, high RAM | console |
| `0xFFFF` | 1 B | `IE`, interrupt enable | console |

Four things to notice:

- **Half the address space is cartridge.** `0x0000–0x7FFF` plus
  `0xA000–0xBFFF`. The console is mostly a window onto a chip it does not own.
- **The console's own RAM is 8 KiB.** That is all of it. `0xC000–0xDFFF`.
  Everything else is either someone else's memory or registers.
- **HRAM is its own 127-byte scratchpad**, physically separate from WRAM. It
  sits *inside* the CPU chip, so it stays accessible while a DMA transfer has
  the external bus locked, and the routine that waits out a DMA has to be copied
  into HRAM and run from there. Games use it for their hottest variables. There
  is also a shorter, faster instruction form (`LDH`) that can only reach
  `0xFF00–0xFFFF`.
- **`IE` sits at `0xFFFF`, alone, outside the I/O block.** Its partner `IF` is
  at `0xFF0F`, inside it. There is no reason for this beyond how the address
  decoding fell out. You will just remember it.

### 3. Echo RAM, or: the map is a wiring diagram

`0xE000–0xFDFF` reads and writes the same cells as `0xC000–0xDDFF`. Write `0x42`
to `0xC000`, read `0xE000`, and you get `0x42`.

Echo RAM is the absence of a feature. The WRAM chip is 8 KiB, so it needs 13
address lines to select a cell. To *place* it at `0xC000` you also have to
decode the top three lines to distinguish it from VRAM, cartridge RAM and
everything else, and the console's address decoding does not check them fully.
Addresses `0xC000` and `0xE000` differ only in a bit the decoder ignores, so
they arrive at the same physical cell.

Nintendo's manual said not to use the echo region. Games used it anyway, some by
accident and some deliberately, and Blargg's test ROMs check it. So: implement
it, as a mirror, in one line.

A memory map describes physical wiring. The gaps, the mirrors and the prohibited
regions are all consequences of what was cheap to build in 1989, so do not look
for intent behind them.

### 4. Writing to ROM is legal and means something else

`0x0000–0x7FFF` is a read-only chip. So what happens when the CPU writes there?

Nothing happens *to the ROM*. But the write still travels down the bus, and the
MBC chip on the cartridge is listening. Writing `0x02` to `0x2100` on an MBC1
cartridge does not store a byte. It tells the mapper "from now on, when the CPU
reads `0x4000–0x7FFF`, serve bank 2". The write is a **command to the mapper**,
using the ROM address range as its command space.

For a `ROM_ONLY` cartridge there is no mapper, so the write goes nowhere. Your
bus should therefore silently ignore writes to ROM. Games write there routinely,
and in Step 15 those same writes become the MBC's control interface. Design the
seam now: the bus should hand the write to the cartridge and let the cartridge
decide to drop it.

### 5. Reads that are not memory

Two regions return values without storing anything:

- **`0xFEA0–0xFEFF`, prohibited.** Real DMG hardware returns `0x00` here in most
  states, with behaviour that depends on what the PPU is doing. Nothing sane
  reads it. Return a constant, write a comment saying it is a simplification,
  move on.
- **Unimplemented I/O.** You have no timer, no PPU, no APU and no joypad yet, so
  most of `0xFF00–0xFF7F` has nothing behind it. Real hardware returns `0xFF`
  for unmapped I/O, because the bus floats high, and emulators follow that
  convention. A game polling an unimplemented register usually copes with `0xFF`
  and hangs on `0x00`.

The general rule for this project: an unimplemented read returns `0xFF`, an
unimplemented write is dropped. Never raise. A raise means one missing feature
crashes the emulator instead of degrading it, and you lose the ability to see
how far a ROM gets.

### 6. Sixteen-bit access, and the Step 01 promise coming due

The CPU reads 16-bit values constantly: `LD HL, d16`, every `PUSH`, every `POP`,
every `CALL` and `RET`. The Game Boy is little-endian, so the value `0x1234` at
`0xC000` is stored as:

```
0xC000: 0x34   <- low byte first
0xC001: 0x12
```

In Step 01 you decided that `join_bytes` stays order-agnostic and endianness
lives at the boundary. This is that boundary. The whole of the machine's byte
order should collapse into two functions:

```python
def read16(self, address: int) -> int:
    return join_bytes(self.read(address + 1), self.read(address))


def write16(self, address: int, value: int) -> None:
    self.write(address, low_byte(value))
    self.write(address + 1, high_byte(value))
```

Read them side by side and check they are exact mirrors. If they are, the
project's byte order is now correct everywhere, permanently, and you will never
think about it again outside this file.

One thing to notice for later: a 16-bit access is **two** 8-bit bus accesses,
and on real hardware each one costs 4 T-cycles. You do not need that today, but
it is why `read16` should be written in terms of `read` instead of reaching into
the arrays directly. When Step 09 makes memory access tick the clock, this
composition makes the timing fall out for free.

### 7. One array or many?

The tempting implementation is `bytearray(0x10000)`: one flat block, `read` is
an index, done. It is also wrong, in three escalating ways:

1. **Writes to ROM would stick.** The game modifies its own code, silently, and
   you find out three hours later.
2. **Echo RAM would not mirror**, because `0xC000` and `0xE000` are different
   indices.
3. **It has no seams.** The PPU owns VRAM and OAM; it needs to lock them during
   certain rendering modes, watch writes to the tile maps, and be handed them at
   construction. The timer owns four registers and needs to be ticked. None of
   that has anywhere to live if memory is one anonymous block.

So: separate storage per region, and a dispatch function that picks one. The bus
owns WRAM and HRAM outright (nobody else wants them), holds the cartridge, and
for now holds plain `bytearray`s for VRAM and OAM as placeholders that the PPU
will take over in Step 11.

For the dispatch itself you have three options:

| Approach | Cost | Verdict |
| --- | --- | --- |
| `if`/`elif` chain over ranges | one comparison per branch until a hit | **Start here.** Order branches by access frequency |
| `match` with guards | identical semantics, arguably reads better | fine, same thing |
| Page table: 256 handlers indexed by `address >> 8` | one index, no comparisons | the real optimisation, ~10× fewer branches; do it in Step 16 with a profiler |

Constraint 4 of the plan applies: correctness before speed. Write the `if`
chain, but write it so the page table is a mechanical refactor later.

### 8. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| `bytearray` | mutable fixed-width byte storage; indexing yields `int` | `String#setbyte` / `Array.new(n, 0)`, but tighter |
| `range` as a constant | `WRAM = range(0xC000, 0xE000)`, then `address in WRAM` | `(0xC000...0xE000)`, and `.cover?` |
| `typing.Protocol` | structural typing: "anything with `read`/`write`" without inheritance | duck typing, but checkable by mypy |
| `match` with guards | multi-way dispatch on a value | `case/in`, which Ruby 3 borrowed from the same tradition |
| Module-level `Final` | the map is constants, not configuration | frozen constants |

`Protocol` is the interesting one. Ruby lets you pass any object that responds
to the right methods and nothing checks it until it fails at runtime. Python's
`Protocol` gives you that same freedom *plus* a static check: declare

```python
class MemoryDevice(Protocol):
    def read(self, address: int) -> int: ...
    def write(self, address: int, value: int) -> None: ...
```

and any class with those two methods satisfies it, without inheriting from
anything or registering anywhere. mypy verifies the shape at every call site.
Duck typing with a proof, which is what a bus talking to interchangeable devices
wants.

You do not need it yet with one device. Declare it anyway: it documents the
contract that the PPU, timer and joypad will all have to satisfy, and it costs
five lines.

### 9. What we are deliberately leaving out

- **The boot ROM.** The real console maps 256 bytes over `0x0000–0x00FF` until a
  write to `0xFF50` unmaps it. We skip it and start the CPU with the register
  values it would have left behind (Step 04). Leave a comment where the overlay
  would go; adding it later is one branch at the top of `read`.
- **CGB double-speed and WRAM banking.** DMG only. `0xD000–0xDFFF` is just the
  second half of one 8 KiB block.
- **PPU access restrictions.** Real hardware makes VRAM return `0xFF` while the
  PPU is drawing. That rule belongs to the PPU, in Step 11.
- **DMA.** `0xFF46` triggers a 160-byte copy into OAM. It needs OAM to matter,
  so it lands with the PPU.

---

## Tasks

### 1. `src/gameboy/memory.py`: the map as constants

Every region from the table above, as `Final` `range` objects:

```python
ROM_BANK_0: Final = range(0x0000, 0x4000)
...
INTERRUPT_ENABLE: Final = 0xFFFF
```

Ranges rather than pairs of ints: `address in ROM_BANK_0` then reads like the
table and is O(1) in CPython (it does arithmetic, it does not iterate).

Also define the echo offset (the distance between `0xE000` and the `0xC000` it
mirrors) as a named constant rather than a literal at the call site.

### 2. `MemoryDevice` Protocol

As in the theory section. Put it in `memory.py` for now; if it needs a home of
its own later, moving it is one import.

### 3. Teach `Cartridge` to serve reads and swallow writes

Add to `cartridge.py`:

```python
def read(self, address: int) -> int: ...
def write(self, address: int, value: int) -> None: ...
```

`read` covers `0x0000–0x7FFF` (straight index into `raw_bytes`) and
`0xA000–0xBFFF` (external RAM: return `0xFF` for now, since a `ROM_ONLY` cart
has none). `write` does nothing at all, with a comment explaining that Step 15
turns it into the MBC command interface.

Note that `Cartridge` is a frozen dataclass. Think about whether that is still
right once a cartridge has mutable RAM and a current-bank number, and what
`frozen=True` will cost you in Step 15. You do not have to change it today, but
have an answer.

### 4. Building the `Bus`

Holds: the cartridge, `wram = bytearray(0x2000)`, `hram = bytearray(0x7F)`,
`vram = bytearray(0x2000)`, `oam = bytearray(0xA0)`, and `ie = 0`.

Also a `bytearray(0x80)` for I/O so that writes to unimplemented registers can
at least be read back. A game that writes `0xFF47` (the background palette) and
reads it back should get its value. Decide for yourself whether that or a flat
`0xFF` is the better placeholder, and write the reason down in a comment.

### 5. `read(self, address: int) -> int`

Dispatch on the region. Order the branches by how often the CPU hits them rather
than by address order; ROM and WRAM dominate.

One guard at the top: mask the address to 16 bits (`u16`), so a caller doing
`read(address + 1)` at `0xFFFF` wraps like the hardware rather than exploding.

### 6. `write(self, address: int, value: int) -> None`

Mirror image. Mask the value to 8 bits. Cartridge writes go to the cartridge;
prohibited and unimplemented writes are dropped.

### 7. Echo RAM

One branch in each of `read` and `write`, translating the address into the WRAM
one. Do it by subtracting the region start and adding WRAM's. That arithmetic
states the relationship between the two regions; a bit mask that happens to land
on the same index states a coincidence.

### 8. `read16` / `write16`

As in the theory section. Resist the urge to optimise them into a slice of the
underlying array.

### 9. CLI: a memory dump

Extend `__main__.py` with `--dump ADDR` and `--length N` (default 64) that
builds a `Bus` from the cartridge and prints a classic hexdump:

```
0100: 00 C3 50 01 CE ED 66 66  CC 0D 00 0B 03 73 00 83  ..P...ff.....s..
0110: 00 0C 00 0D 00 08 11 1F  88 89 00 0E DC CC 6E E6  ..............n.
```

Every byte goes through `bus.read` rather than `cartridge.raw_bytes`, so the
dump exercises the bus. `int(x, 0)` parses `0x100` and `256` alike, which makes
a good `type=` for the argument.

### 10. Tests in `tests/test_memory.py`

At least these:

- WRAM round-trips: write then read at `0xC000`, `0xCFFF`, `0xDFFF`
- HRAM round-trips at `0xFF80` and `0xFFFE`
- echo mirrors both ways: write `0xC000`, read `0xE000`; write `0xE000`, read
  `0xC000`
- ROM reads return the cartridge's bytes
- ROM writes are ignored and leave the ROM intact
- prohibited region reads a constant and swallows writes
- `IE` at `0xFFFF` round-trips independently of the I/O block
- `read16` is little-endian: write `0x34` at `0xC000`, `0x12` at `0xC001`,
  expect `0x1234`
- `write16` then `read16` round-trips a 16-bit value
- values are masked: `write(0xC000, 0x1FF)` stores `0xFF`

Reuse the synthetic ROM fixture from `tests/test_cartridge.py` rather than
building a second one. If it is not already a `conftest.py` fixture, this is the
moment to move it.

---

## Hints

- `bytearray(n)` gives you `n` zero bytes, and indexing returns an `int` (unlike
  `bytes[i:i+1]`, which gives you `bytes`). Assignment takes an `int` in
  `0..255` and raises `ValueError` outside it, a free assertion that your
  masking is correct, so do not defeat it by masking twice.
- Offset arithmetic is the whole bug surface of this file. Always
  `self.wram[address - WRAM.start]`, never a hand-computed constant. Write it
  the same way in all six branches and a wrong one stands out.
- `range` objects have `.start` and `.stop`, and `.stop` is exclusive, while the
  hardware map is normally written inclusively: `range(0xC000, 0xE000)` is the
  region documented as `0xC000–0xDFFF`. Get this straight once.
- Echo RAM stops at `0xFDFF` and mirrors `0xC000–0xDDFF`, which is 512 bytes
  short of the full 8 KiB. The last 512 bytes of WRAM have no mirror. Nothing
  depends on it, and the ranges should still say the truth.
- `match address:` with `case _ if address in WRAM:` works and reads well, but a
  `match` on ranges does the same comparisons an `if`/`elif` does. Pick whichever
  you find clearer and be consistent.
- For the hexdump, `bytes(...).decode("ascii", errors="replace")` will not give
  you the ASCII column you want (control characters are not replaced). Filter
  with `chr(b) if 0x20 <= b < 0x7F else "."` instead.
- mypy strict will want a return type on every branch of `read`. If you find
  yourself unable to prove the function always returns, that is the type checker
  telling you the dispatch has a hole. Add the final `return 0xFF` catch-all and
  mean it.
- Do not add a `__getitem__` to make `bus[0xC000]` work. It reads nicely and it
  hides the two most important call sites in the project from grep.

---

## Acceptance criteria

- [ ] `uv run python -m gameboy rom.gb --dump 0x0104 --length 48` prints the
      Nintendo logo, starting `CE ED 66 66 CC 0D 00 0B`. Those bytes are
      identical in every commercial ROM ever made, so this is a real check.
- [ ] `uv run python -m gameboy rom.gb --dump 0x0100 --length 4` shows the entry
      point, almost certainly `00 C3 50 01`, which is `NOP; JP 0x0150`. You are
      looking at the first instruction your CPU will execute in Step 04.
- [ ] Writing to any address in `0x0000–0x7FFF` leaves the ROM unchanged.
- [ ] Echo RAM mirrors in both directions.
- [ ] `read16` and `write16` round-trip, and reading `0xC000` after writing
      `0x1234` there gives `0x34`.
- [ ] `uv run pytest` is green, with at least ten new tests and still no ROM file
      needed.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` are
      all clean.
- [ ] No raw hex address literals in `read`/`write` outside the constants block.

---

## Questions to ask yourself before moving on

1. Your `read` ends in a catch-all returning `0xFF`. How would you find out that
   a real game is hitting it constantly? And would you want to know, or is
   silence the point?
2. The bus currently reaches into its own `bytearray`s for VRAM and OAM. In
   Step 11 the PPU takes ownership. Does that branch become
   `self.ppu.read(address)`, or does the bus keep the array and the PPU borrow
   it? Which one lets the PPU enforce its access restrictions?
3. You wrote `MemoryDevice` but only the cartridge implements it. When the timer
   arrives in Step 09, will you add another `elif` for `0xFF04–0xFF07`, or does
   the bus hold a mapping of ranges to devices? At what number of devices does
   the `elif` chain stop being the right answer?
4. `read16(0xFFFF)` reads `0xFFFF` and then `0x0000`, because you masked. Is
   wrapping the right behaviour, or should it be an error? What does real
   hardware do, and does any real program depend on it?

When these pass, ping me and I will review before Step 04, where the CPU finally
starts fetching from this bus.
