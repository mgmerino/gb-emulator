from dataclasses import dataclass
from enum import IntEnum
from typing import Final

#      0xFF00  P1 / JOYP
# ┌─────┬─────┬─────────┬─────────┬───────┬────────┬──────┬───────┐
# │  7  │  6  │    5    │    4    │   3   │   2    │  1   │   0   │
# ├─────┴─────┼─────────┼─────────┼───────┼────────┼──────┼───────┤
# │  unwired  │ select  │ select  │ Start │ Select │  B   │   A   │  if bit 5 is 0
# │ read as 1 │ buttons │  d-pad  │ Down  │  Up    │ Left │ Right │  if bit 4 is 0
# └───────────┴─────────┴─────────┴───────┴────────┴──────┴───────┘
#               written by the CPU   read-only: 0 means pressed

_UNWIRED: Final = 0xC0
_SELECT_LINES: Final = 0x30
_BUTTON_LINES: Final = 0x0F


class Button(IntEnum):
    """Each value is bits 5-0 of what P1 reads when that button is the only one
    held and its group is selected. Active-low, like the register: the 0 in
    bits 5-4 is the select line that reaches the button, and the 0 in bits 3-0
    is the line it pulls down.
    """

    START = 0b01_0111
    SELECT = 0b01_1011
    B = 0b01_1101
    A = 0b01_1110
    DOWN = 0b10_0111
    UP = 0b10_1011
    LEFT = 0b10_1101
    RIGHT = 0b10_1110


@dataclass(slots=True)
class Joypad:
    select: int = 0
    held: frozenset[Button] = frozenset()

    def read(self, address: int) -> int:
        low_nibble = _BUTTON_LINES

        for button in self.held:
            if self._group_is_selected(button):
                # Same flip on bits 3-0: the 0 in the pattern becomes the one
                # bit this button pulls down.
                pattern = button & _BUTTON_LINES
                bit = _BUTTON_LINES ^ pattern
                low_nibble &= ~bit

        return _UNWIRED | self.select | low_nibble

    def write(self, address: int, value: int) -> None:
        self.select = value & _SELECT_LINES

    def _group_is_selected(self, button: Button) -> bool:
        # The button's select line is the 0 in its bits 5-4. Flipping them
        # inside the mask turns that 0 into a bit to test `select` with.
        group_bit = _SELECT_LINES ^ (button & _SELECT_LINES)
        return (self.select & group_bit) == 0
