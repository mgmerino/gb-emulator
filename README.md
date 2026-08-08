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
| 03 | [The memory bus](docs/STEP_03.md) | in progress |
| 04 | [CPU state & the fetch-decode-execute skeleton](docs/STEP_04.md) | next |

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
