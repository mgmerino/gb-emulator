from dataclasses import dataclass
from typing import Final

from gameboy.bits import high_byte, u16
from gameboy.memory_map import DIVIDER, TIMER_CONTROL, TIMER_COUNTER, TIMER_MODULO

# Timer memory registers:
# ------------------------------------------------------------------------------
# | 0xFF04 | DIV  | the divider, represented by the internal 16 bit counter top byte
# | 0xFF05 | TIMA | the timer counter. Counts at a configurable rate
# | 0xFF06 | TMA  | the timer modulo. What TIMA reloads to when it overflows
# | 0xFF07 | TAC  | the timer control. On/off, and which of four rates
#
# DIV:
# Besides the timer counter (TIMA), there is a *internal* counter. The top byte is what
# DIV shows.
#
# TAC:
# Only the lowest 3 bits exist. Bits 7-3 are unused: ignored on write, read as 1.
# 0xFF07 byte:  │ 7  6  5  4  3 │ 2 │ 1  0
#               └──── unused ───┘ │   └──┴── clock select
#                                 └── enable
# Enable: Controls whether TIMA is incremented. Note that DIV is always counting,
# regardless of this bit.
#
# Clock select: Controls the frequency at which TIMA is incremented, as follows. Notice
# that the four rates are *not* mapped to binary values in speed order, as one might
# expect:
# ┌──────┬─────┬───────────────┐
# │ Hex  │ Bin │ Hardware      │
# ├──────┼─────┼───────────────┤
# │ 0x00 │ 000 │ off           │
# │ 0x04 │ 100 │ on, 4096 Hz   │
# │ 0x05 │ 101 │ on, 262144 Hz │
# │ 0x06 │ 110 │ on, 65536 Hz  │
# │ 0x07 │ 111 │ on, 16384 Hz  │
# └──────┴─────┴───────────────┘

_TAC_UNUSED: Final = 0xF8  # 5 bits high, 3 low


@dataclass(slots=True)
class Timer:
    counter: int = 0  # internal timer counter, fixed
    tima: int = 0  # timer counter, configurable
    tma: int = 0  # timer modulo
    tac: int = 0  # timer control
    last_and: bool = False

    @property
    def divider(self) -> int:
        return high_byte(self.counter)

    def tick(self, cycles: int) -> None:
        self.counter = u16(self.counter + cycles)

    def read(self, address: int) -> int:
        if address == DIVIDER:
            return self.divider
        if address == TIMER_COUNTER:
            return self.tima
        if address == TIMER_MODULO:
            return self.tma
        if address == TIMER_CONTROL:
            return self.tac | _TAC_UNUSED

        return 0xFF

    def write(self, address: int, value: int) -> None:
        if address == DIVIDER:
            self.counter = 0
            return
        if address == TIMER_COUNTER:
            self.tima = value
            return
        if address == TIMER_MODULO:
            self.tma = value
            return
        if address == TIMER_CONTROL:
            self.tac = value
            return
