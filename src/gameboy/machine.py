"""Driving the machine: one instruction at a time, and one frame at a time.

Core code, not CLI code. The CLI and the window both call it, so it cannot live
in `__main__.py`.
"""

from collections.abc import Iterator
from typing import Final

from gameboy.cpu import CPU, Registers
from gameboy.memory import Bus
from gameboy.ppu import LINES_PER_FRAME, SCANLINE_DOTS

# One DMG frame in T-cycles: 154 scanlines of 456 dots.
FRAME_CYCLES: Final = LINES_PER_FRAME * SCANLINE_DOTS


def step(cpu: CPU, bus: Bus) -> int:
    """Run one instruction, then let every device catch up by what it cost.

    Every loop that drives the machine calls this, so no two of them can drift
    apart on how time is handed out. They differ only in when they stop.

    It takes a `Bus` and not a `MemoryDevice` because `tick` is not part of that
    protocol. The CPU needs four ways to move bytes; passing time to the devices
    is the caller's job.
    """
    cycles = cpu.step()
    bus.tick(cycles)

    return cycles


def run(bus: Bus, instructions: int) -> Iterator[tuple[CPU, int, int]]:
    """Run `instructions` instructions, yielding the CPU, the address it
    fetched from, and what the step cost.
    """
    cpu = CPU(bus, Registers.post_boot())

    for _ in range(instructions):
        # Read the pc first: stepping moves it. The cycle count only exists
        # afterwards.
        address = cpu.registers.pc

        yield (cpu, address, step(cpu, bus))


def run_frame(cpu: CPU, bus: Bus, budget: int = FRAME_CYCLES * 4) -> bool:
    """Run until the PPU finishes a frame. Says whether one arrived.

    The caller owns the CPU. This runs once per frame for as long as the window
    is open, so building a CPU here would reset the registers sixty times a
    second.

    `False` means no frame this time, not an error. The PPU stops ticking while
    LCDC bit 7 is clear, and ROMs turn the LCD off whenever they like: Tetris
    does at 0x0237. The caller should show the last frame again and come back.
    What the budget rules out is waiting forever on a frame that is not coming,
    which hangs the window with nothing to explain it.

    The budget counts T-cycles, because that is what a frame is measured in;
    the default is four frames' worth. `run` counts instructions instead,
    because that is what the CLI reports.
    """
    # Read the counter rather than assume it is zero. This is call 30000 as
    # often as it is the first.
    target = bus.ppu.frames + 1
    spent = 0

    while spent < budget:
        spent += step(cpu, bus)

        if bus.ppu.frames >= target:
            return True

    return False
