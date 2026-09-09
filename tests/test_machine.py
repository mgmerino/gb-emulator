"""The loop a display drives, and the guard that keeps it from hanging."""

import pytest

from gameboy.cartridge import Cartridge
from gameboy.cpu import CPU, Registers
from gameboy.machine import FRAME_CYCLES, run_frame
from gameboy.memory import Bus
from gameboy.ppu import PPU
from gameboy.timer import Timer


@pytest.fixture
def spinning() -> Cartridge:
    """A ROM whose whole program is `JP 0x0100`.

    The `cartridge` fixture has stray bytes in it, and a CPU left running for a
    few frames reaches them and dies on an opcode that does not exist.
    """
    image = bytearray(0x8000)
    image[0x0100:0x0103] = bytes((0xC3, 0x00, 0x01))

    return Cartridge.from_bytes(bytes(image))


def test_run_frame_draws_exactly_one_frame(spinning: Cartridge) -> None:
    bus = Bus.post_boot(spinning)  # post_boot, so the LCD is on
    cpu = CPU(bus, Registers.post_boot())

    assert run_frame(cpu, bus)
    assert bus.ppu.frames == 1


def test_run_frame_resumes_rather_than_restarting(spinning: Cartridge) -> None:
    bus = Bus.post_boot(spinning)
    cpu = CPU(bus, Registers.post_boot())

    for expected in (1, 2, 3):
        assert run_frame(cpu, bus)
        assert bus.ppu.frames == expected


def test_run_frame_gives_up_when_the_lcd_is_off(spinning: Cartridge) -> None:
    # A plain PPU has LCDC bit 7 clear, so it never reaches VBlank. Without the
    # budget this call does not return.
    bus = Bus(spinning, Timer(), PPU())
    cpu = CPU(bus, Registers.post_boot())

    assert not run_frame(cpu, bus, budget=FRAME_CYCLES)
    assert bus.ppu.frames == 0


def test_run_frame_spends_no_more_than_its_budget(spinning: Cartridge) -> None:
    """The timer's counter advances by exactly the cycles handed to `bus.tick`,
    so it is the machine's own clock. It is 16 bits, hence the small budget.
    """
    budget = 1_000
    bus = Bus(spinning, Timer(), PPU())
    cpu = CPU(bus, Registers.post_boot())

    run_frame(cpu, bus, budget=budget)

    # The budget is checked between steps, so it overshoots by at most one
    # instruction. The longest is 24 cycles.
    assert budget <= bus.timer.counter <= budget + 24
