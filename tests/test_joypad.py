import pytest

from gameboy import memory_map
from gameboy.joypad import Button, Joypad

NOTHING: frozenset[Button] = frozenset()


@pytest.mark.parametrize(
    "written, expected",
    [
        (0x20, 0xED),
        (0x10, 0xDE),
        (0x30, 0xFF),
        (0x00, 0xCC),
        (0x2F, 0xED),  # bits 3-0 are the buttons' lines, not the CPU's
    ],
)
def test_held_button_read_selected_group(written: int, expected: int) -> None:
    joypad = Joypad(held=frozenset({Button.LEFT, Button.A}))

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


@pytest.mark.parametrize(
    "select, held, hold, expected",
    [
        pytest.param(
            0x10, NOTHING, frozenset({Button.A}), True, id="new-in-selected-group"
        ),
        pytest.param(
            0x20, NOTHING, frozenset({Button.A}), False, id="new-in-other-group"
        ),
        pytest.param(
            0x10,
            frozenset({Button.A}),
            frozenset({Button.A}),
            False,
            id="still-held",
        ),
        pytest.param(0x10, frozenset({Button.A}), NOTHING, False, id="released"),
        pytest.param(
            0x00, NOTHING, frozenset({Button.LEFT}), True, id="both-groups-selected"
        ),
        pytest.param(
            0x20,
            frozenset({Button.LEFT}),
            frozenset({Button.LEFT, Button.A}),
            False,
            id="only-old-one-in-selected-group",
        ),
    ],
)
def test_hold_writes_selected_group_button_set_and_returns_interrupt_flag(
    select: int, held: frozenset[Button], hold: frozenset[Button], expected: bool
) -> None:
    joypad = Joypad(select=select, held=held)

    assert joypad.hold(hold) == expected
