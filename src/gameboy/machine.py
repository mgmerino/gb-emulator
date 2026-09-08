"""Driving the machine: one instruction at a time, and one frame at a time.

Core code, not CLI code. The CLI and the window both call it, so it cannot live
in `__main__.py`.
"""

from collections.abc import Iterator

from gameboy.cpu import CPU, Registers
from gameboy.memory import Bus


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
