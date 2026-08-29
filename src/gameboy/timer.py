from dataclasses import dataclass
from typing import Final

from gameboy.bits import get_bit, high_byte, u16
from gameboy.memory_map import DIVIDER, TIMER_CONTROL, TIMER_COUNTER, TIMER_MODULO

# Timer memory registers:
# ------------------------------------------------------------------------------
# | 0xFF04 | DIV  | the divider, represented by the internal 16 bit counter top byte
# | 0xFF05 | TIMA | the timer counter. Counts at a configurable rate
# | 0xFF06 | TMA  | the timer modulo. What TIMA reloads to when it overflows
# | 0xFF07 | TAC  | the timer control. On/off, and which of four rates
#
# The internal counter:
# ┌──────────────── DIV ────────────────┐
# │                                     │
# ┌────┬────┬────┬────┬────┬────┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
# │ 15 │ 14 │ 13 │ 12 │ 11 │ 10 │▒9▒│ 8 │▒7▒│ 6 │▒5▒│ 4 │▒3▒│ 2 │ 1 │ 0 │
# └────┴────┴────┴────┴────┴────┴─┬─┴───┴─┬─┴───┴─┬─┴───┴─┬─┴───┴───┴───┘
#                                 │       │       │       └─ 262144 Hz
#                                 │       │       │
#                                 │       │       └─ 65536 Hz
#                                 │       │
#                                 │       └─ 16384 Hz
#                                 │
#                                 └─ 4096 Hz
#
# TIMA: counts based on the *internal* counter. That counter has 16 bits, and those bits
# represent the following:
# - The top byte is what DIV shows
# - The bits 9, 7, 5 and 3 are the possible rates at which TIMA counts. TAC register will
#   select the desired speed (read below). Hardware-wise, a multiplexer makes this
#   possible. The output is then connected to the AND gate to evaluate, using the enable
#   bit of TAC, if there is a falling edge.
#
# The signal path, and why TAC shows up twice in it:
#
#   ┌───────────────────────────┐
#   │ counter · 16 bits · +1/cy │──── bits 15-8 ────────────► DIV · 0xFF04
#   └─────────────┬─────────────┘
#                 │ bit 9 / 7 / 5 / 3
#                 ▼
#             ┌───────┐
#             │  MUX  │◄──── TAC bits 1-0 · which bit is watched
#             └───┬───┘
#                 ▼
#             ┌───────┐
#             │  AND  │◄──── TAC bit 2 · the switch
#             └───┬───┘
#                 ▼
#         did it fall 1 → 0 ?  (last_and remembers the previous sample)
#                 │
#                 ▼
#            TIMA + 1 ──── on overflow ───► TIMA = TMA, and IF bit 2 · 0xFF0F
#
# TAC: control bits for enabling TIMA and selecting the clock speed.
# Only the lowest 3 bits exist. Bits 7-3 are unused: ignored on write, read as 1.
# 0xFF07 byte:  │ 7  6  5  4  3 │ 2 │ 1  0
#               └──── unused ───┘ │   └──┴── clock select
#                                 └── enable
# Enable: Controls whether TIMA is incremented. Note that DIV is always counting,
# regardless of this bit. The output is connected to the AND gate.
#
# Clock select: Controls the frequency at which TIMA is incremented, as follows. Notice
# that the four rates are *not* mapped to binary values in speed order, as one might
# expect. This is what *selects* in the multiplexer the target value.
# ┌──────┬─────┬───────────────┬────────────────┐
# │ Hex  │ Bin │ Hardware      │ Bit in counter │
# ├──────┼─────┼───────────────┼────────────────┤
# │ 0x00 │ 000 │ off           │ 9, but gated   │
# │ 0x04 │ 100 │ on, 4096 Hz   │ 9              │
# │ 0x05 │ 101 │ on, 262144 Hz │ 3              │
# │ 0x06 │ 110 │ on, 65536 Hz  │ 5              │
# │ 0x07 │ 111 │ on, 16384 Hz  │ 7              │
# └──────┴─────┴───────────────┴────────────────┘

_TAC_UNUSED: Final = 0xF8  # 5 bits high, 3 low
_WATCHED_BITS: Final = (9, 3, 5, 7)  # indexed by TAC bits 1-0, in encoding order


@dataclass(slots=True)
class Timer:
    counter: int = 0  # internal timer counter, fixed
    tima: int = 0  # timer counter, configurable
    tma: int = 0  # timer modulo
    tac: int = 0  # timer control
    last_and: bool = False  # what the gate read on the previous sample

    @property
    def divider(self) -> int:
        return high_byte(self.counter)

    def tick(self, cycles: int) -> bool:
        overflowed = False
        watched_bit = _WATCHED_BITS[self.tac & 0b11]
        enable = get_bit(self.tac, 2)

        for _ in range(0, cycles, 4):
            self.counter = u16(self.counter + 4)
            if self._advance_tima(watched_bit, enable):
                overflowed = True

        return overflowed

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

    def write(self, address: int, value: int) -> bool:
        if address == DIVIDER:
            self.counter = 0
            return self._sample_gate()
        if address == TIMER_COUNTER:
            self.tima = value
            return False
        if address == TIMER_MODULO:
            self.tma = value
            return False
        if address == TIMER_CONTROL:
            self.tac = value
            return self._sample_gate()

        return False

    def _advance_tima(self, watched_bit: int, enable: bool) -> bool:
        """Sample the AND gate. Returns whether TIMA overflowed on this sample."""
        current_and = get_bit(self.counter, watched_bit) and enable
        falling = self.last_and and not current_and
        self.last_and = current_and

        if falling:
            self.tima += 1
            if self.tima > 0xFF:
                self.tima = self.tma
                return True

        return False

    def _sample_gate(self) -> bool:
        """Re-evaluate the gate after a write changed one of its inputs."""
        return self._advance_tima(_WATCHED_BITS[self.tac & 0b11], get_bit(self.tac, 2))
