# gb-emulator

A Game Boy (DMG) emulator written from scratch in Python, as a learning project.
With the goal of avoiding emulation libraries and no rendering framework inside
the core: the emulator is a plain Python package that exposes a framebuffer and
accepts button state.

Progress follows [`docs/PLAN.md`](docs/PLAN.md). Each step has its own document
with the theory, the tasks and the acceptance criteria.

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
illegal opcodes account for all 256 bytes. A real ROM now runs its whole boot
sequence to the end, and what stops it is missing hardware rather than a missing
instruction:

```
0235  FE     CP A, d8      A:00 F:70 BC:0000 DE:00D8 HL:CFFF SP:FFFE  8
0237  20     JR NZ, e8     A:00 F:70 BC:0000 DE:00D8 HL:CFFF SP:FFFE  12
0233  F0     LDH A, (a8)   A:00 F:70 BC:0000 DE:00D8 HL:CFFF SP:FFFE  12
--- 200000 instructions, 2100400 T-cycles, reached the 200000 instruction limit ---
```

Tetris reaches `0x0233` after 12341 instructions — thirteen past the `DI` that
used to end the run — and never leaves. Feed the address back to `--dump` and the
loop explains itself:

```
0233: F0 44    LDH A, (FF44)    ; LY, the line the PPU is drawing
0235: FE 94    CP  A, 0x94      ; 148, the first line of VBlank
0237: 20 FA    JR  NZ, -6
0239: 3E 03    LD  A, 0x03      ; never reached — what follows writes LCDC
```

It reads `LY` 62554 times in this run and gets `0x00` every time, because nothing
writes `LY` yet. An endless loop here is the correct outcome: the ROM has
finished configuring itself and is waiting for the start of VBlank before it
touches VRAM.

Interrupts work, but nothing raises one. `IF` at `0xFF0F` is written by hardware,
and the first devices that will write it are the timer in Step 09 and the PPU in
Step 11.

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
