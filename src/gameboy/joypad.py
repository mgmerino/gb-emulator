from dataclasses import dataclass, field
from enum import IntEnum

# #    0xFF00  P1 / JOYP
# ┌─────┬─────┬─────────┬─────────┬───────┬────────┬──────┬───────┐
# │  7  │  6  │    5    │    4    │   3   │   2    │  1   │   0   │
# ├─────┴─────┼─────────┼─────────┼───────┼────────┼──────┼───────┤
# │  unwired  │ select  │ select  │ Start │ Select │  B   │   A   │  if bit 5 is 0
# │ read as 1 │ buttons │  d-pad  │ Down  │  Up    │ Left │ Right │  if bit 4 is 0
# └───────────┴─────────┴─────────┴───────┴────────┴──────┴───────┘
#               written by the CPU   read-only: 0 means pressed

# Button encodes the bits 5-4 and 3-0 as hex values:
# | BIN  | HEX |
# |------|-----|
# |010111| 17  |
# |011011| 1B  |
# |011101| 1D  |
# |011110| 1E  |
# |100111| 27  |
# |101011| 2B  |
# |101101| 2D  |
# |101110| 2E  |

GROUP_BIT_MASK = 0x30
BUTTON_BIT_MASK = 0x0F

class Button(IntEnum):
    START = 0x17
    SELECT = 0x1B
    B = 0x1D
    A = 0x1E
    DOWN = 0x27
    UP = 0x2B
    LEFT = 0x2D
    RIGHT = 0x2E


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
