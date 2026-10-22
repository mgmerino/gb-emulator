from dataclasses import dataclass, field
from enum import IntEnum

#      0xFF00  P1 / JOYP
# ┌─────┬─────┬─────────┬─────────┬───────┬────────┬──────┬───────┐
# │  7  │  6  │    5    │    4    │   3   │   2    │  1   │   0   │
# ├─────┴─────┼─────────┼─────────┼───────┼────────┼──────┼───────┤
# │  unwired  │ select  │ select  │ Start │ Select │  B   │   A   │  if bit 5 is 0
# │ read as 1 │ buttons │  d-pad  │ Down  │  Up    │ Left │ Right │  if bit 4 is 0
# └───────────┴─────────┴─────────┴───────┴────────┴──────┴───────┘
#               written by the CPU   read-only: 0 means pressed

GROUP_BIT_MASK = 0x30
BUTTON_BIT_MASK = 0x0F

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
    held: set[Button] = field(default_factory=set)

    def read(self, address: int) -> int:
        low_nibble = 0x0F

        for button in self.held:
            # check if button's current group is selected
            group_bit = GROUP_BIT_MASK ^ (button & GROUP_BIT_MASK)
            selected = self.select & group_bit == 0

            # compute the bit that goes down in the nibble
            if selected:
                button_bit = button & BUTTON_BIT_MASK
                mask = BUTTON_BIT_MASK ^ button_bit
                low_nibble &= ~mask

        return 0xC0 | self.select | low_nibble

    def write(self, address: int, value: int) -> None:
        self.select = value & 0x30
