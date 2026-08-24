"""Reference table:
| Register | Width | Conventional use                                              |
| -------- | ----- | ------------------------------------------------------------- |
| `A`      | 8     | The accumulator. Every ALU result ends here                  |
| `F`      | 8     | Flags. Not addressable directly, only through `AF`            |
| `B`, `C` | 8     | General purpose.                                              |
| `D`, `E` | 8     | General purpose                                               |
| `H`, `L` | 8     | General purpose, but `HL` is *the* pointer register           |
| `SP`     | 16    | Stack pointer.                                                |
| `PC`     | 16    | Program counter.                                              |
"""

from dataclasses import dataclass
from typing import Self

from gameboy.alu import Flags
from gameboy.bits import clear_bit, get_bit, high_byte, join_bytes, low_byte, u16
from gameboy.instructions import CB_OPCODES, OPCODES
from gameboy.interrupts import pending
from gameboy.memory import MemoryDevice
from gameboy.memory_map import INTERRUPT_FLAG

# Since masking is _expected_ to be executed from the top layer, we want to ensure
# no invalid values slip into the Registers class.
#
# The properties are listed too. Their setters run `high_byte`/`low_byte`, which
# mask, so a too-wide value assigned to a pair reaches both halves already in
# range and the guard on the halves never fires.
_WIDTHS = {
    "a": 0xFF,
    "b": 0xFF,
    "c": 0xFF,
    "d": 0xFF,
    "e": 0xFF,
    "h": 0xFF,
    "l": 0xFF,
    "f": 0xFF,
    "sp": 0xFFFF,
    "pc": 0xFFFF,
    "af": 0xFFFF,
    "bc": 0xFFFF,
    "de": 0xFFFF,
    "hl": 0xFFFF,
}


@dataclass(slots=True)
class Registers:
    a: int = 0  # 8 bits (a-l)
    b: int = 0
    c: int = 0
    d: int = 0
    e: int = 0
    h: int = 0
    l: int = 0
    sp: int = 0  # 16 bits (sp & pc)
    pc: int = 0
    z_flag: bool = False  # bit 7
    n_flag: bool = False  # bit 6
    h_flag: bool = False  # bit 5
    c_flag: bool = False  # bit 4

    if __debug__:

        def __setattr__(self, name: str, value: object) -> None:
            width = _WIDTHS.get(name)
            # isinstance narrows `value` to int for the comparison, and rejects
            # anything that is not an integer.
            if width is not None and (
                not isinstance(value, int) or not 0 <= value <= width
            ):
                raise ValueError(f"{value!r} does not fit in register {name}")
            object.__setattr__(self, name, value)

    def apply(self, flags: Flags) -> None:
        if flags.z is not None:
            self.z_flag = flags.z

        if flags.n is not None:
            self.n_flag = flags.n

        if flags.h is not None:
            self.h_flag = flags.h

        if flags.c is not None:
            self.c_flag = flags.c

    @classmethod
    def post_boot(cls) -> Self:
        registers = cls()
        # See https://gbdev.io/pandocs/Power_Up_Sequence.html#cpu-registers
        # If the header checksum is 0x00, then the carry and half-carry flags
        # are clear; otherwise, they are both set.
        registers.af = 0x01B0  # Z=1 N=0 H=? C=?
        registers.bc = 0x0013
        registers.de = 0x00D8
        registers.hl = 0x014D
        registers.pc = 0x0100
        registers.sp = 0xFFFE

        return registers

    @property
    def f(self) -> int:
        return (
            (0x80 if self.z_flag else 0)
            | (0x40 if self.n_flag else 0)
            | (0x20 if self.h_flag else 0)
            | (0x10 if self.c_flag else 0)
        )

    @f.setter
    def f(self, value: int) -> None:
        self.z_flag = get_bit(value, 7)
        self.n_flag = get_bit(value, 6)
        self.h_flag = get_bit(value, 5)
        self.c_flag = get_bit(value, 4)

    @property
    def af(self) -> int:
        return join_bytes(self.a, self.f)

    @af.setter
    def af(self, value: int) -> None:
        self.a = high_byte(value)
        self.f = low_byte(value)

    @property
    def bc(self) -> int:
        return join_bytes(self.b, self.c)

    @bc.setter
    def bc(self, value: int) -> None:
        self.b = high_byte(value)
        self.c = low_byte(value)

    @property
    def de(self) -> int:
        return join_bytes(self.d, self.e)

    @de.setter
    def de(self, value: int) -> None:
        self.d = high_byte(value)
        self.e = low_byte(value)

    @property
    def hl(self) -> int:
        return join_bytes(self.h, self.l)

    @hl.setter
    def hl(self, value: int) -> None:
        self.h = high_byte(value)
        self.l = low_byte(value)


class UnknownOpcodeError(Exception):
    def __init__(self, opcode: int, address: int) -> None:
        super().__init__(f"unknown opcode 0x{opcode:02X} at 0x{address:04X}")
        self.opcode = opcode
        self.address = address


@dataclass
class CPU:
    bus: MemoryDevice
    registers: Registers
    ime: bool = False  # master flag
    ime_pending: bool = False  # EI fired, promote after the next instruction
    halted: bool = False

    def fetch_u8(self) -> int:
        # where are you, dear Program Counter?
        # please, tell me what 8 bits are on your sight!
        value = self.bus.read(self.registers.pc)
        # ok, now advance one step, see you on the next address!
        self.registers.pc = u16(self.registers.pc + 1)  # out(t) = out(t-1) + 1

        return value

    def fetch_u16(self) -> int:
        # tell me what 8 bits can you see now and advance 1 step
        low = self.fetch_u8()
        # do it again
        high = self.fetch_u8()

        return join_bytes(high, low)

    def step(self) -> int:
        pending_interrupt = pending(self.bus)  # is a bus read, so we better save it
        # wake up or keep halted
        if self.halted:
            if pending_interrupt is not None:
                self.halted = False
            else:
                return 4

        if self.ime and pending_interrupt is not None:
            self.ime = False

            # clear interrupt flag before pushing the stack
            i_flag = self.bus.read(INTERRUPT_FLAG)
            self.bus.write(INTERRUPT_FLAG, clear_bit(i_flag, pending_interrupt))

            # push (ie: save the current pc), then point to the interrupt vector
            self.push16(self.registers.pc)
            self.registers.pc = pending_interrupt.vector
            return 20

        promote = self.ime_pending  # caution: needs to be captured *before* fetching
        opcode = self.fetch_u8()
        cb_opcode = None

        if opcode == 0xCB:
            cb_opcode = self.fetch_u8()
            instruction = CB_OPCODES.get(cb_opcode)
        else:
            instruction = OPCODES.get(opcode)

        if instruction is None:
            if cb_opcode is not None:
                address = u16(self.registers.pc - 2)
            else:
                address = u16(self.registers.pc - 1)

            raise UnknownOpcodeError(opcode, address)

        if promote:
            self.ime = True
            self.ime_pending = False

        taken = instruction.execute(self)
        if taken and instruction.cycles_when_taken is not None:
            return instruction.cycles_when_taken

        return instruction.cycles

    def push16(self, value: int) -> None:
        self.registers.sp = u16(self.registers.sp - 2)
        self.bus.write16(self.registers.sp, value)

    def pop16(self) -> int:
        value = self.bus.read16(self.registers.sp)
        self.registers.sp = u16(self.registers.sp + 2)

        return value
