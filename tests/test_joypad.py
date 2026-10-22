import pytest

from gameboy import memory_map
from gameboy.joypad import Button, Joypad


@pytest.mark.parametrize(
    "written, expected",
    [
        (0x20, 0xED),
        (0x10, 0xDE),
        (0x30, 0xFF),
        (0x00, 0xCC)
    ],
)
def test_held_button_read_selected_group(written: int, expected: int) -> None:
    joypad = Joypad(held={Button.LEFT, Button.A})

    joypad.write(memory_map.JOYPAD, written)
    assert joypad.read(memory_map.JOYPAD) == expected


@pytest.mark.parametrize(
    "written, expected",
    [(0x00, 0xCF), (0x10, 0xDF), (0xFF, 0xFF)],
)
def test_nothing_held_reads_all_released(written: int, expected: int) -> None:
    joypad = Joypad()

    joypad.write(memory_map.JOYPAD, written)
    assert joypad.read(memory_map.JOYPAD) == expected
