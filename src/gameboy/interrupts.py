# Interrupt table:
# IF / IE:   bit  4    3    2    1    0
#                 │    │    │    │    └── VBlank
#                 │    │    │    └─────── LCD STAT
#                 │    │    └──────────── Timer
#                 │    └───────────────── Serial
#                 └────────────────────── Joypad
#
# 0x0040  ┌────────┐ 8 bytes  VBlank
# 0x0048  ├────────┤ 8 bytes  LCD STAT
# 0x0050  ├────────┤ 8 bytes  Timer
# 0x0058  ├────────┤ 8 bytes  Serial
# 0x0060  └────────┘ 8 bytes  Joypad

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

from gameboy.bits import get_bit, set_bit
from gameboy.memory_map import INTERRUPT_ENABLE, INTERRUPT_FLAG

if TYPE_CHECKING:
    from gameboy.memory import MemoryDevice


class Interrupt(IntEnum):
    VBLANK = 0
    LCD_STAT = 1
    TIMER = 2
    SERIAL = 3
    JOYPAD = 4

    @property
    def vector(self) -> int:
        return 0x40 + self * 8


def pending(bus: MemoryDevice) -> Interrupt | None:
    ie = bus.read(INTERRUPT_ENABLE)
    i_flag = bus.read(INTERRUPT_FLAG)
    result = ie & i_flag & 0x1F

    # The order is the implied priority. If any, will return the lowest one
    for interrupt in Interrupt:
        if get_bit(result, interrupt):
            return interrupt

    return None


def request(bus: MemoryDevice, interrupt: Interrupt) -> None:
    i_flag = bus.read(INTERRUPT_FLAG)

    bus.write(INTERRUPT_FLAG, set_bit(i_flag, interrupt))
