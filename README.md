# gb-emulator

A Game Boy (DMG) emulator written from scratch in Python, as a learning project.
With the goal of avoiding emulation libraries and no rendering framework inside
the core: the emulator is a plain Python package that exposes a framebuffer and
accepts button state.

Progress follows [`docs/PLAN.md`](docs/PLAN.md). Each step has its own document
with the theory, the tasks and the acceptance criteria. Those read as a story in
order; for a map of the code as it stands right now, there is an AI-generated
tour:

[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mgmerino/gb-emulator)

| Step | | |
| --- | --- | --- |
| 01 | [Project scaffolding & bit primitives](docs/STEP_01.md) | done |
| 02 | [Cartridge & ROM header](docs/STEP_02.md) | done |
| 03 | [The memory bus](docs/STEP_03.md) | done |
| 04 | [CPU state & the fetch-decode-execute skeleton](docs/STEP_04.md) | done |
| 05 | [Loads, the ALU and the flags](docs/STEP_05.md) | done |
| 06 | [Jumps, calls and the stack](docs/STEP_06.md) | done |
| 07 | [CB-prefixed opcodes: rotates, shifts and bit operations](docs/STEP_07.md) | done |
| 08 | [Interrupts, `HALT` and the master flag](docs/STEP_08.md) | done |
| 09 | [Timer, divider and the falling-edge detector](docs/STEP_09.md) | done |
| 10 | Blargg `cpu_instrs` — arrived with Step 09's serial port | done |

## Requirements

Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## Usage

Inspect a cartridge header:

```
uv run python -m gameboy path/to/rom.gb
```

```
Title:            TETRIS
Cartridge:        ROM_ONLY (0x00)
ROM:              32 KiB (2 banks)
RAM:              none
CGB:              DMG
SGB:              no
Destination:      Japan
Version:          1
Header checksum:  0x0A  valid
Global checksum:  0x16BF  (computed 0x16BF)
```

Hex dump any address in the 16-bit address space, through the memory bus:

```
uv run python -m gameboy path/to/rom.gb --dump 0x0150 --length 32
```

```
Dump from 0x0150 to 0x0170 (32 bytes)
--- BEGIN ---
0150: C3 0C 02 CD E3 29 F0 41  E6 03 20 FA 46 F0 41 E6  .....).A.. .F.A.
0160: 03 20 FA 7E A0 C9 7B 86  27 22 7A 8E 27 22 3E 00  . .~..{.'"z.'">.
--- END ---
```

Trace execution from the cartridge entry point, one line per instruction:

```
uv run python -m gameboy path/to/rom.gb --trace 3
```

```
0100  00     NOP           A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  4
0101  C3     JP a16        A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  16
0150  C3     JP a16        A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  16
--- 3 instructions, 36 T-cycles, reached the 3 instruction limit ---
```

Left to right: the address the opcode was fetched from, the opcode bytes, the
mnemonic, the register state after the instruction, and its cost in T-cycles.
CB-prefixed instructions occupy two opcode bytes and print both:

```
0101  CB 07  RLC A         A:02 F:00 BC:0013 DE:00D8 HL:014D SP:FFFE  8
```

The summary line closes every run. Its cycle total is the clock everything else
will be synchronised against from Step 09 onwards — one DMG frame is 70224
T-cycles.

The base opcode table is complete: 244 instructions, the `0xCB` prefix and the 11
illegal opcodes account for all 256 bytes.

Run a ROM without the per-instruction firehose, and print whatever it said over
the link cable:

```
uv run python -m gameboy path/to/instr_timing.gb --run 300000
```

```
--- serial ---
instr_timing

Passed

--- 300000 instructions, 2916120 T-cycles, reached the 300000 instruction limit ---
```

## Test ROMs

Blargg's suite reports its verdict on the LCD and, byte by byte, over the serial
port. There is no LCD until Step 11, which is why the serial stub arrives early:
it is the emulator's only way to speak.

All eleven `cpu_instrs` sub-tests pass, and so does `instr_timing`:

| ROM | | ROM | |
| --- | --- | --- | --- |
| `01-special` | Passed | `07-jr,jp,call,ret,rst` | Passed |
| `02-interrupts` | Passed | `08-misc instrs` | Passed |
| `03-op sp,hl` | Passed | `09-op r,r` | Passed |
| `04-op r,imm` | Passed | `10-bit ops` | Passed |
| `05-op rp` | Passed | `11-op a,(hl)` | Passed |
| `06-ld r,r` | Passed | `instr_timing` | Passed |

`instr_timing` is the sharpest of them: it does not check what an instruction
computes, it checks **how long it takes**, and the only clock a ROM can measure
with is the timer. One `Passed` therefore verifies every cycle count in the
opcode table — both branches of the conditionals included — *and* that the timer
runs at the rate it claims.

Roughly 290k instructions/second on CPython 3.12, about 80% of a real DMG.

Two things do not work yet:

- **the combined `cpu_instrs.gb`**, 64 KiB behind an MBC1. The bus maps bank 1 as
  a fixed slice of the image, so banks 2 and 3 are unreachable and the ROM stops
  after `01:ok  02:ok  03`. That is Step 15. The eleven individual ROMs are 32
  KiB each and need no bank switching.
- **`--run N` has no early exit**, so a verdict that arrives at 2M instructions
  still costs the whole budget.

## What is missing

The timer raises interrupts and `HALT` wakes on its own, so the machine now keeps
time. What it cannot do is draw: a real game configures itself, then waits for
the PPU before touching VRAM, and that wait never ends.

```
0233: F0 44    LDH A, (FF44)    ; LY, the line the PPU is drawing
0235: FE 94    CP  A, 0x94      ; 148, the first line of VBlank
0237: 20 FA    JR  NZ, -6
0239: 3E 03    LD  A, 0x03      ; never reached — what follows writes LCDC
```

Nothing writes `LY` yet, so `CP` never matches. An endless loop here is the
correct outcome, and it ends in Step 11.

## Development

```
uv sync                      # install dependencies
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # type check, strict
```

## Reference material

- [Pan Docs](https://gbdev.io/pandocs/) — the hardware reference
- [Opcode table](https://gbdev.io/gb-opcodes/optables/)
- [Blargg's test ROMs](https://github.com/retrio/gb-test-roms)
