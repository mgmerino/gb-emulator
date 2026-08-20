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
| 07 | [CB-prefixed opcodes: rotates, shifts and bit operations](docs/STEP_07.md) | next |

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
0100  00  NOP        A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  4
0101  C3  JP a16     A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  16
0150  C3  JP a16     A:01 F:B0 BC:0013 DE:00D8 HL:014D SP:FFFE  16
```

Left to right: the address the opcode was fetched from, the opcode byte, the
mnemonic, the register state after the instruction, and its cost in T-cycles.
Two instructions are implemented so far, so the trace stops early with a non-zero
exit code and a message naming the opcode and the address it was read from:

```
gameboy: unknown opcode 0xAF at 0x020C
```

That address is what you feed back to `--dump`.

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
