from gameboy.interrupts import Interrupt


def test_interrupt_table_vectors() -> None:
    assert Interrupt.VBLANK.vector == 0x40
    assert Interrupt.LCD_STAT.vector == 0x48
    assert Interrupt.TIMER.vector == 0x50
    assert Interrupt.SERIAL.vector == 0x58
    assert Interrupt.JOYPAD.vector == 0x60
