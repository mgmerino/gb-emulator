from dataclasses import dataclass

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
#
# 0xFF07 byte:  │ 7  6  5  4  3 │ 2 │ 1  0
#               └──── unused ───┘ │   └──┴── clock speed
#                                 └── on/off
#
# Notice that the four rates are *not* mapped to binary values in speed order, as one
# might expect:
# ┌──────┬─────┬───────────────┐
# │ Hex  │ Bin │ Hardware      │
# ├──────┼─────┼───────────────┤
# │ 0x00 │ 000 │ off           │
# │ 0x04 │ 100 │ on, 4096 Hz   │
# │ 0x05 │ 101 │ on, 262144 Hz │
# │ 0x06 │ 110 │ on, 65536 Hz  │
# │ 0x07 │ 111 │ on, 16384 Hz  │
# └──────┴─────┴───────────────┘


@dataclass(slots=True)
class Timer:
    counter: int = 0
    tima: int = 0
    tma: int = 0
    tac: int = 0
    last_and: bool = False

    @property
    def divider(self) -> int:
        return (self.counter >> 8) & 0xFF

    def tick(self, cycles: int) -> None:
        self.counter = (self.counter + cycles) & 0xFFFF
