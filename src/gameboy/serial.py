"""The link cable, modelled as far as a test ROM needs and no further.

# | 0xFF01 | SB | serial transfer data. One byte in, one byte out
# | 0xFF02 | SC | serial control. Bit 7 starts a transfer, bit 0 picks the clock
#
# A ROM sends a byte by writing it to SB and then writing 0x81 to SC: bit 7
# "start", bit 0 "use my own clock". Real hardware then shifts eight bits out
# over the cable at 8192 Hz — 512 T-cycles a bit, 4096 for the byte — clears
# bit 7, and requests the serial interrupt.
#
# What is modelled here: the byte is handed to `output` and bit 7 is cleared in
# the same instruction. What is not:
#
# - the 4096 T-cycles. There is nothing on the other end of the cable to be
#   slow, so the transfer is instant. This is a lie about timing, and the right
#   one until a second Game Boy shows up.
# - the serial interrupt. Blargg's ROMs poll SC rather than waiting on it, and
#   firing an interrupt for a transfer that took no time is a bigger lie than
#   the one above. If a ROM ever hangs waiting for one, this is the line to
#   revisit.
#
# SB reads back 0xFF after a transfer rather than the byte that was sent: a real
# DMG with no cable attached clocks in a high line, eight times.
"""

from dataclasses import dataclass, field

from gameboy.bits import clear_bit, get_bit
from gameboy.memory_map import (
    OPEN_BUS,
    SERIAL_CONTROL,
    SERIAL_CONTROL_UNUSED,
    SERIAL_DATA,
)

_TRANSFER_START = 7


@dataclass(slots=True)
class Serial:
    data: int = OPEN_BUS
    control: int = 0
    output: bytearray = field(default_factory=bytearray)

    @property
    def text(self) -> str:
        """What the ROM has said so far. Undecodable bytes are not our problem."""
        return self.output.decode("ascii", errors="replace")

    def read(self, address: int) -> int:
        if address == SERIAL_DATA:
            return self.data
        if address == SERIAL_CONTROL:
            return self.control | SERIAL_CONTROL_UNUSED

        return OPEN_BUS

    def write(self, address: int, value: int) -> None:
        if address == SERIAL_DATA:
            self.data = value
            return
        if address == SERIAL_CONTROL:
            self.control = value
            if get_bit(value, _TRANSFER_START):
                self.output.append(self.data)
                self.data = OPEN_BUS  # nothing on the cable drives the line low
                self.control = clear_bit(self.control, _TRANSFER_START)
