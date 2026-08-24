import pytest

from gameboy.interrupts import Interrupt, pending
from gameboy.memory import Bus


def test_interrupt_table_vectors() -> None:
    assert Interrupt.VBLANK.vector == 0x40
    assert Interrupt.LCD_STAT.vector == 0x48
    assert Interrupt.TIMER.vector == 0x50
    assert Interrupt.SERIAL.vector == 0x58
    assert Interrupt.JOYPAD.vector == 0x60


@pytest.mark.parametrize(
    ("ie", "i_flag", "expected"),
    [
        (0b00000, 0b00000, None),  # Nothing
        (0b00100, 0b00000, None),  # Enabled, but it didn't happen
        (0b00000, 0b00001, None),  # It happened, but it was not enabled
        (0b11111111, 0b11100000, None),  # Noise, masked
        (0b10101, 0b00001, Interrupt.VBLANK),
        (0b10110, 0b00010, Interrupt.LCD_STAT),
        (0b11111, 0b10100, Interrupt.TIMER),  # priority over joypad
        (0b11111, 0b01000, Interrupt.SERIAL),
        (0b11111, 0b10000, Interrupt.JOYPAD),
    ],
)
def test_pending(bus: Bus, ie: int, i_flag: int, expected: Interrupt | None) -> None:
    bus.write(0xFFFF, ie)  # ie
    bus.write(0xFF0F, i_flag)  # if

    assert pending(bus) is expected
