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

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Final, Self

from gameboy.alu import Flags
from gameboy.bits import get_bit, high_byte, join_bytes, low_byte, u16
from gameboy.memory import MemoryDevice

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


@dataclass(frozen=True, slots=True)
class Instruction:
    name: str
    cycles: int
    execute: Callable[["CPU"], None]


@dataclass
class CPU:
    bus: MemoryDevice
    registers: Registers

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
        # PC advances before execution, not after. By the time an instruction
        # runs, PC already points at its first operand byte.
        opcode = self.fetch_u8()
        instruction = OPCODES.get(opcode)

        if instruction is None:
            raise UnknownOpcodeError(opcode, u16(self.registers.pc - 1))

        instruction.execute(self)

        return instruction.cycles


class Operand(IntEnum):
    B = 0b000
    C = 0b001
    D = 0b010
    E = 0b011
    H = 0b100
    L = 0b101
    HL_POINTER = 0b110
    A = 0b111

    @property
    def assembly_name(self) -> str:
        if self is Operand.HL_POINTER:
            return "(HL)"

        return self.name


def read_operand(cpu: CPU, operand: Operand) -> int:
    match operand:
        case Operand.HL_POINTER:
            return cpu.bus.read(cpu.registers.hl)
        case Operand.A:
            return cpu.registers.a
        case Operand.B:
            return cpu.registers.b
        case Operand.C:
            return cpu.registers.c
        case Operand.D:
            return cpu.registers.d
        case Operand.E:
            return cpu.registers.e
        case Operand.H:
            return cpu.registers.h
        case Operand.L:
            return cpu.registers.l


def write_operand(cpu: CPU, operand: Operand, value: int) -> None:
    match operand:
        case Operand.HL_POINTER:
            cpu.bus.write(cpu.registers.hl, value)
        case Operand.A:
            cpu.registers.a = value
        case Operand.B:
            cpu.registers.b = value
        case Operand.C:
            cpu.registers.c = value
        case Operand.D:
            cpu.registers.d = value
        case Operand.E:
            cpu.registers.e = value
        case Operand.H:
            cpu.registers.h = value
        case Operand.L:
            cpu.registers.l = value


T_CYCLES_PER_ACCESS = 4


def count_cycles(*accesses: Operand, immediates: int = 0) -> int:
    """Cost of one generated instruction:
    One access for the opcode fetch, one per immediate byte, and one for
    every operand access that reads memory.
    """
    total = 1  # the fetch cost one
    for op in accesses:
        if op is Operand.HL_POINTER:
            total += 1  # memory access

    return (total + immediates) * T_CYCLES_PER_ACCESS


def _nop(cpu: CPU) -> None:
    # NOP's job is to pass four cycles and advance PC by one, and fetch_u8
    # already advanced PC.
    pass


def _jp_a16(cpu: CPU) -> None:
    # move the PC to the address yielded by reading two consecutive bytes
    cpu.registers.pc = cpu.fetch_u16()


# ----------
# Load Block
# ----------


def _make_ld(dst: Operand, src: Operand) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        value = read_operand(cpu, src)
        write_operand(cpu, dst, value)

    return execute


def _load_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}

    for opcode in range(0x40, 0x80):
        if opcode == 0x76:
            # 0x76 is HALT. Nothing to do here.
            continue

        dst = Operand((opcode >> 3) & 0b111)
        src = Operand(opcode & 0b111)

        instructions[opcode] = Instruction(
            f"LD {dst.assembly_name}, {src.assembly_name}",
            count_cycles(dst, src),
            _make_ld(dst, src),
        )
    return instructions


OPCODES: Final[dict[int, Instruction]] = {
    # Address         OPCODE     CYCLES
    0x00: Instruction("NOP", 4, _nop),
    0xC3: Instruction("JP a16", 16, _jp_a16),
    **_load_block(),
}
