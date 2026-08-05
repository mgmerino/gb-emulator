# Implementation plan

A Game Boy is a small, fully documented machine. That is what makes it the
canonical "first emulator": every component is simple on its own, and the hard
part is only ever *how they agree on time*.

## The machine we are emulating

| Part | What it is |
| --- | --- |
| CPU | Sharp SM83, an 8-bit CPU, Z80-flavoured but its own thing. ~4.19 MHz |
| Memory | One flat 16-bit address space (0x0000–0xFFFF), no MMU, no virtual memory |
| Cartridge | ROM, sometimes RAM, usually behind a bank-switching chip (MBC) |
| PPU | Picture Processing Unit. Draws 160×144 pixels, 4 shades of grey, scanline by scanline |
| APU | 4 sound channels (2 pulse, 1 wave, 1 noise) |
| Timer | A divider and a programmable counter that can raise interrupts |
| Joypad | 8 buttons, read through a single multiplexed register |

Everything the CPU talks to — cartridge, video RAM, sprite memory, sound
registers, buttons — is *memory-mapped*. There are no I/O instructions. That is
the single most important architectural fact for us: if we get the memory bus
right, every other component plugs into it the same way.

## The central concept: the emulator loop

```
while running:
    cycles = cpu.step()      # execute exactly one instruction
    timer.tick(cycles)       # advance every other component
    ppu.tick(cycles)         # by the same amount of time
    apu.tick(cycles)
    interrupts.service()
```

Real hardware runs all of these *in parallel*. We fake that by running the CPU
for one instruction, then letting everyone else catch up by the exact number of
cycles that instruction took. This is "cycle-counted" or "instruction-stepped"
emulation. It is accurate enough for the vast majority of games and vastly
simpler than the alternative (cycle-stepped, where you advance every component
one T-cycle at a time).

Because of this, **cycle counts are not an optimisation detail — they are the
clock**. An instruction that reports the wrong duration desynchronises video and
audio. We will care about them from the very first opcode.

## Roadmap

Each step gets its own `docs/STEP_XY.md` with theory, atomic tasks, hints and
acceptance criteria. Steps are ordered so that **every one of them ends in
something you can run and observe**, never in "trust me, we'll use this later".

| Step | Title | You will be able to |
| --- | --- | --- |
| 01 | Project scaffolding & bit primitives | Run tests, lint, type-check; manipulate 8/16-bit values safely |
| 02 | Cartridge & ROM header | Load a `.gb` file, print its title, MBC type, ROM/RAM size, verify checksums |
| 03 | The memory bus | Read/write any address; route to ROM, WRAM, HRAM, echo RAM, I/O stubs |
| 04 | CPU state & the fetch–decode–execute skeleton | Step a CPU that executes `NOP` and halts on unknown opcodes |
| 05 | Loads, ALU and flags | Run a handmade ROM that computes something and check the registers |
| 06 | Jumps, calls, the stack | Run subroutines and loops |
| 07 | CB-prefixed opcodes (bit ops, rotates, shifts) | Complete the instruction set |
| 08 | Interrupts, `HALT`, `EI`/`DI` | Handle the interrupt vector table and the famous HALT bug |
| 09 | Timer & divider | Pass Blargg's `instr_timing` / timer test ROMs |
| 10 | Blargg `cpu_instrs` harness | **Serial output says "Passed" — the CPU is provably correct** |
| 11 | PPU part 1: tiles, background, LCD registers | Dump a rendered frame as a PNG/PPM |
| 12 | PPU part 2: window & sprites (OAM) | Full frame composition |
| 13 | Screen output & frame pacing | See Nintendo's boot logo scroll down, at the right speed |
| 14 | Joypad | Play something |
| 15 | MBC1/MBC3, external RAM, battery saves | Load real, bigger games and keep save files |
| 16 | Debug tooling: disassembler, tracer, breakpoints | Diff your execution trace against a reference emulator |
| 17 | APU (optional) | Sound |

Steps 01–10 are the ones that teach the most. Step 10 is the milestone: a
passing `cpu_instrs` is the moment the project stops being a toy.

## Design constraints we are committing to

1. **The core is framework-independent.** No pygame, no SDL, no I/O library
   inside `gameboy/`. The core exposes a framebuffer and accepts button state.
   Rendering is a separate, swappable layer. This keeps everything testable
   headlessly and keeps the interesting code honest.
2. **Explicit and typed.** Full type hints, `mypy --strict`. Types are the
   cheapest documentation for a domain full of `int`s that are secretly
   different things (addresses, opcodes, cycle counts, register values).
3. **Test-driven where it pays.** Bit primitives, header parsing, memory
   routing and individual opcodes are pure functions over small state — perfect
   for unit tests. Rendering and timing get verified against real test ROMs
   instead.
4. **Correctness before speed.** Python will be slow. We do not care yet.
   Optimise only once a real game boots, and only with measurements.
5. **Byte order belongs to the memory bus, not to `bits.py`.** `bits.py` knows
   about *widths* (8-bit, 16-bit); endianness is a property of how a value is
   laid out across addressable cells, so it is the bus's business. `join_bytes`
   stays order-agnostic and the swap appears exactly once, at the call site
   where the address arithmetic already lives:
   `join_bytes(read(addr + 1), read(addr))`. This keeps `bits.py` a leaf module
   with no imports, and keeps `read16`/`write16`/`push16`/`pop16` provably
   mirror images of each other. *(Decided in Step 01.)*

## Reference material

- [Pan Docs](https://gbdev.io/pandocs/) — *the* reference. Bookmark it.
- [Opcode table](https://gbdev.io/gb-opcodes/optables/) — every instruction, its
  length, its cycles, its flag effects.
- [Blargg's test ROMs](https://github.com/retrio/gb-test-roms) — the standard
  correctness suite.
- [The Ultimate Game Boy Talk](https://www.youtube.com/watch?v=HyzD8pNlpwI) —
  33c3, still the best 1-hour overview of the hardware.
