# Step 02 — The cartridge and its header

## Goal

Load a `.gb` file and tell the user what it is: title, cartridge hardware, ROM
and RAM size, and whether the file is intact. By the end of this step you will
have run your emulator against a real game for the first time — it will not
execute anything yet, but it will read the game's own description of itself.

---

## Theory

### 1. A cartridge is not just a ROM

The plastic shell contains, depending on the game:

- a **ROM chip** — the code and graphics, 32 KiB to 8 MiB
- optionally a **bank controller** (MBC) — a small chip that lets the CPU see
  more than 32 KiB through a 16-bit address space that cannot reach that far
- optionally **RAM** — for save data or scratch space
- optionally a **battery** — to keep that RAM alive on the shelf
- rarely, a **real-time clock** (Pokémon Gold), or a **rumble motor**

The console cannot detect any of this electrically. It finds out by *reading a
data structure the cartridge declares about itself* — the header. Getting the
header right is therefore a precondition for everything else: it tells you which
MBC to emulate, and picking the wrong one means the game boots to garbage.

### 2. Why the header sits at 0x0100

When the Game Boy powers on, the CPU does not start at address `0x0000`. A small
256-byte **boot ROM** inside the console is mapped over `0x0000–0x00FF` and runs
first. It scrolls the Nintendo logo, plays the chime, performs two checks
(below), and then unmaps itself and jumps to **`0x0100`**.

So `0x0100` is the first cartridge address the CPU ever executes, and the header
is laid out immediately around it:

```
0x0100 ─ 0x0103   entry point        4 bytes of code, almost always: NOP; JP 0x0150
0x0104 ─ 0x0133   Nintendo logo      48 bytes, bit-for-bit fixed
0x0134 ─ 0x0143   title              16 bytes, ASCII, null-padded
0x0143            CGB flag           (overlaps the title's last byte)
0x0144 ─ 0x0145   new licensee code
0x0146            SGB flag
0x0147            cartridge type     ← which MBC. The important one.
0x0148            ROM size
0x0149            RAM size
0x014A            destination code    0x00 Japan, 0x01 overseas
0x014B            old licensee code   0x33 means "use the new code above"
0x014C            mask ROM version
0x014D            header checksum    ← the boot ROM enforces this
0x014E ─ 0x014F   global checksum     nobody enforces this
0x0150 ─          the actual game
```

Note the entry point is only four bytes. There is no room for a program there,
so it is a jump — the header physically sits in the middle of the code, and the
game has to hop over it.

### 3. The two checks the boot ROM performs

**The Nintendo logo.** Those 48 bytes at `0x0104` are compared byte-for-byte
against a copy inside the boot ROM. Mismatch, and the console halts — a black
screen, forever. This was a legal mechanism, not a technical one: an unlicensed
cartridge had to reproduce Nintendo's trademarked logo to boot at all, which
made every unlicensed cartridge a trademark infringement by construction. It is
also why the logo is what scrolls down the screen: the console is displaying the
data it just verified.

**The header checksum**, byte `0x014D`. Computed over `0x0134–0x014C` — the
title through the version byte. Mismatch, and the console also halts. The
algorithm is deliberately trivial:

```
checksum = 0
for address in 0x0134 ..= 0x014C:
    checksum = checksum - rom[address] - 1
```

…truncated to 8 bits, which is where your `u8` earns its keep. Note it is a
running *subtraction*, so it relies on wraparound at every step.

There is a third checksum at `0x014E–0x014F`, the **global checksum**: a 16-bit
sum of every byte in the ROM except those two. The boot ROM does not check it,
and real cartridges ship with it wrong. Compute it, report it, do not enforce it.

> **The global checksum is stored big-endian.** High byte at `0x014E`, low byte
> at `0x014F` — the opposite of everything else on the machine. It is one of
> perhaps three big-endian values in the entire system. This is a nice early
> confirmation of the decision you made in Step 01: because byte order lives at
> the boundary and not inside `join_bytes`, handling this exception is a local
> choice at one call site rather than a special case in your primitives.

### 4. Sizes are exponents, not byte counts

`0x0148` does not hold a size. It holds a shift:

```
rom_size_bytes = 32 * 1024 << value        # 0x00 → 32 KiB, 0x01 → 64 KiB, … 0x08 → 8 MiB
bank_count     = 2 << value                # 2, 4, 8, … 512 banks of 16 KiB
```

RAM size at `0x0149` is not regular and must be a lookup table — and its history
shows: `0x01` was 2 KiB on some early hardware and is now considered unused, and
the values are not in ascending order (`0x04` is 128 KiB, `0x05` is 64 KiB).

| Value | RAM |
| --- | --- |
| 0x00 | none |
| 0x01 | unused |
| 0x02 | 8 KiB (1 bank) |
| 0x03 | 32 KiB (4 banks) |
| 0x04 | 128 KiB (16 banks) |
| 0x05 | 64 KiB (8 banks) |

A useful cross-check: the declared ROM size should equal the actual file length.
If it does not, you have a trimmed, overdumped, or corrupt file, and you want to
know that now rather than during a wild jump three hours from now.

### 5. Cartridge type

Byte `0x0147` encodes the mapper *and* its extras in one value. The full table is
in Pan Docs; the ones that matter early:

| Value | Hardware |
| --- | --- |
| 0x00 | ROM only — 32 KiB, no mapper. Tetris, Dr. Mario |
| 0x01 | MBC1 |
| 0x02 | MBC1 + RAM |
| 0x03 | MBC1 + RAM + battery |
| 0x0F–0x13 | MBC3 (+RTC, +RAM, +battery in combinations) |
| 0x19–0x1E | MBC5 (+RAM, +battery, +rumble) |

You will implement only `0x00` for now — Step 15 handles the rest. But parse the
byte into a meaningful value today, because "which mapper" is the question the
memory bus will ask in Step 03.

### 6. Python concepts this step introduces

| Concept | Why here | Ruby analogue |
| --- | --- | --- |
| `pathlib.Path` | `read_bytes()` is the clean way to load a ROM | `File.binread` |
| `@dataclass(frozen=True)` | A parsed header is a value object — immutable, comparable, printable | `Struct.new(..., keyword_init: true)`, or a frozen `Data` |
| `enum.IntEnum` | `CartridgeType.MBC1` reads better than `0x01` but still compares as an int | a module of constants, or a symbol |
| `@classmethod` alternate constructor | `Cartridge.from_path(p)` alongside `__init__` | `def self.from_path` |
| `typing.Final` | marks module constants as non-reassignable for mypy | `FOO = ...` + `freeze` |
| Custom exception | `InvalidCartridgeError` beats a bare `ValueError` | `class InvalidCartridgeError < StandardError` |

The dataclass is the one worth dwelling on. In Ruby you would reach for
`attr_reader` and a constructor; Python's `@dataclass` generates `__init__`,
`__repr__` and `__eq__` from the annotated fields, and `frozen=True` makes
assignment raise. Add `slots=True` and instances stop carrying a `__dict__`,
which matters not at all for one header and quite a lot for the 160×144 pixels
you will be pushing around in Step 11 — so it is a habit worth forming now.

---

## Tasks

### 1. `src/gameboy/cartridge.py` — constants

Define the header offsets as module-level `Final` constants. Prefer named
constants over magic numbers at the call site; you will read this file again in
Step 15 and `HEADER_CHECKSUM` is a lot kinder than `0x014D`.

### 2. `CartridgeType(IntEnum)`

Cover at least `ROM_ONLY`, the three MBC1 variants, the MBC3 range and the MBC5
range. Decide what to do with a value you do not recognise — `IntEnum` raises on
an unknown value, which may or may not be what you want for a corrupt file.

### 3. `Header` — a frozen dataclass

Fields: `title`, `cartridge_type`, `rom_size` (bytes), `rom_banks`, `ram_size`
(bytes), `ram_banks`, `cgb_flag`, `sgb_flag`, `destination`, `version`,
`header_checksum`, `global_checksum`.

Store sizes as real byte counts, not raw header values. The raw byte is an
encoding detail; every consumer wants the number.

### 4. `parse_header(rom: bytes) -> Header`

Raise `InvalidCartridgeError` if the ROM is shorter than `0x0150` — you cannot
parse a header that is not there, and the slice would silently return something
short rather than failing.

### 5. The two checksums

```python
def compute_header_checksum(rom: bytes) -> int: ...
def compute_global_checksum(rom: bytes) -> int: ...
```

Keep these as free functions taking the raw ROM. They are pure, they are
testable in isolation, and the header dataclass should hold the *declared*
values while these produce the *computed* ones — so a consumer can compare.

### 6. `Cartridge`

A class holding the raw `bytes` plus its parsed `Header`, with a
`from_path(path: Path)` classmethod. Give it a `header_checksum_valid` property.
This is the object the memory bus will take in Step 03.

### 7. A CLI: `python -m gameboy <rom>`

Create `src/gameboy/__main__.py` using `argparse`. Print a readable summary:

```
Title:            TETRIS
Cartridge:        ROM_ONLY (0x00)
ROM:              32 KiB (2 banks)
RAM:              none
CGB:              no
Version:          1
Header checksum:  0x0A  valid
Global checksum:  0x16BF  (computed 0x16BF)
```

### 8. Tests — without shipping a ROM

You cannot commit a real game. Build a synthetic one in a fixture instead: a
`bytearray(0x8000)` with the header fields you want, and the checksum byte
computed and written in. That gives you a valid 32 KiB ROM-only cartridge in
about ten lines, entirely under your control.

Cover: a valid header parses; a truncated ROM raises; the header checksum
matches a hand-computed value; a corrupted title byte makes the checksum
invalid; ROM size and file length agreeing and disagreeing.

Optionally, add a test that runs against a real ROM only when one is available —
`pytest.mark.skipif` on an environment variable such as `GB_TEST_ROM`. That way
your suite stays green on a fresh clone while you can still point it at Tetris
locally.

---

## Hints

- `rom[0x0134:0x0144]` gives you `bytes`. Turn it into a title with
  `.decode("ascii", errors="replace").rstrip("\x00").strip()` — some games pad
  with spaces rather than nulls, and a few have junk in the high bytes because
  the field was later repurposed for the CGB flag.
- The header checksum loop is where the Step 01 masking rule shows up for real.
  Either mask inside the loop or once at the end; both work, but only one of
  them keeps the intermediate values looking like a real 8-bit register. Think
  about which, and why it does not change the answer.
- `range(0x0134, 0x014D)` — the end is exclusive, and the spec's range is
  inclusive of `0x014C`. Off-by-one here produces a checksum that is wrong for
  every ROM, which is at least an easy failure to spot.
- For the global checksum, `sum(rom)` over a `bytes` object works directly and
  is fast; you then need to subtract the two stored bytes and mask to 16 bits.
- `int.from_bytes(rom[0x014E:0x0150], "big")` — the one place you will type
  `"big"` in this whole project.
- `IntEnum` members compare equal to their int values, so
  `header.cartridge_type == 0x00` still works. Use that to keep the memory bus
  simple later without giving up the readable name in logs.
- `@dataclass(frozen=True, slots=True)` — `slots=True` needs Python 3.10+, which
  you have.
- For the CLI, `argparse` is stdlib and enough. Resist adding `click` or `typer`;
  the design constraint says framework-independent, and a ROM path plus a couple
  of flags does not need a dependency.

---

## Acceptance criteria

- [ ] `uv run gameboy path/to/rom.gb` (or `python -m gameboy …`) prints the
      summary above for a real ROM you own.
- [ ] The header checksum it reports as valid **is** valid — cross-check against
      any online ROM header viewer, or against a second emulator.
- [ ] A truncated file raises `InvalidCartridgeError` with a message that says
      what was wrong, not just that something was.
- [ ] `uv run pytest` — all green, with at least six new tests, none of which
      require a ROM file to exist.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` — all
      clean.
- [ ] `Header` is frozen: attempting to assign to a field raises.
- [ ] No raw hex literals for header offsets outside the constants block.

---

## Questions to ask yourself before moving on

1. `parse_header` raises when the ROM is too short. Should it also raise when the
   header checksum is invalid? The real console halts — but should your *parser*
   refuse, or should it parse and report? Which behaviour would you want when
   debugging a ROM you suspect is corrupt?
2. You are storing `rom_size` as a byte count computed from the header byte. What
   should happen when that disagrees with `len(rom)` — trust the header, trust
   the file, or refuse? There is a defensible answer; Step 03 will depend on it.
3. The global checksum is big-endian. Where did you put that knowledge — in
   `cartridge.py`, or somewhere shared? Does it belong next to the little-endian
   helpers you have not written yet?

When these pass, ping me and I will review before Step 03, the memory bus.
