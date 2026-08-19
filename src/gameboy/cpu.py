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

from gameboy.alu import Flags, adc, add, add16, and_, daa, dec, inc, or_, sbc, sub, xor
from gameboy.bits import get_bit, high_byte, join_bytes, low_byte, u8, u16
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


@dataclass(frozen=True, slots=True)
class AluOperation:
    name: str
    apply: Callable[[int, int, bool], tuple[int, Flags]]
    writes_result: bool


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

    def push16(self, value: int) -> None:
        self.registers.sp = u16(self.registers.sp - 2)
        self.bus.write16(self.registers.sp, value)

    def pop16(self) -> int:
        value = self.bus.read16(self.registers.sp)
        self.registers.sp = u16(self.registers.sp + 2)

        return value


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


class RegisterPair(IntEnum):
    """The two-bit pair index in bits 5 and 4 of the 16-bit instructions."""

    BC = 0b00
    DE = 0b01
    HL = 0b10
    SP = 0b11


def read_pair(cpu: CPU, pair: RegisterPair) -> int:
    match pair:
        case RegisterPair.BC:
            return cpu.registers.bc
        case RegisterPair.DE:
            return cpu.registers.de
        case RegisterPair.HL:
            return cpu.registers.hl
        case RegisterPair.SP:
            return cpu.registers.sp


def write_pair(cpu: CPU, pair: RegisterPair, value: int) -> None:
    match pair:
        case RegisterPair.BC:
            cpu.registers.bc = value
        case RegisterPair.DE:
            cpu.registers.de = value
        case RegisterPair.HL:
            cpu.registers.hl = value
        case RegisterPair.SP:
            cpu.registers.sp = value


T_CYCLES_PER_ACCESS = 4


def count_cycles(
    *accesses: Operand, immediates: int = 0, data_accesses: int = 0
) -> int:
    """Cost of one generated instruction:
    One access for the opcode fetch, one per immediate byte, and one for
    every operand access that reads memory.
    """
    total = 1  # the fetch cost one
    for op in accesses:
        if op is Operand.HL_POINTER:
            total += 1  # memory access

    return (total + immediates + data_accesses) * T_CYCLES_PER_ACCESS


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


def _make_ld_immediate(dst: Operand) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        value = cpu.fetch_u8()
        write_operand(cpu, dst, value)

    return execute


def _ld_block() -> dict[int, Instruction]:
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


def _ld_immediate_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}
    # Opcodes: [0x06, 0x0E, 0x16, 0x1E, 0x26, 0x2E, 0x36, 0x3E]
    # Registers:  B     C     D     E     H     L    (HL)   A

    for opcode in range(0x06, 0x40, 8):  # 00 rrr 110
        dst = Operand((opcode >> 3) & 0b111)

        instructions[opcode] = Instruction(
            f"LD {dst.assembly_name}, d8",
            count_cycles(dst, immediates=1),
            _make_ld_immediate(dst),
        )
    return instructions


# Irregular instructions
#
# Loads that carry the accumulator to or from memory. They do not sit on a
# shared bit pattern the way the LD and ALU blocks do, so each one is written
# out by hand.
#
# | Opcode | Mnemonic     | Effect                      | Bytes | Cycles |
# | ------ | ------------ | --------------------------- | ----- | ------ |
# | 0x02   | LD (BC), A   | memory[BC] = A              | 1     | 8      |
# | 0x0A   | LD A, (BC)   | A = memory[BC]              | 1     | 8      |
# | 0x12   | LD (DE), A   | memory[DE] = A              | 1     | 8      |
# | 0x1A   | LD A, (DE)   | A = memory[DE]              | 1     | 8      |
# | 0x22   | LD (HL+), A  | memory[HL] = A, then HL++   | 1     | 8      |
# | 0x2A   | LD A, (HL+)  | A = memory[HL], then HL++   | 1     | 8      |
# | 0x32   | LD (HL-), A  | memory[HL] = A, then HL--   | 1     | 8      |
# | 0x3A   | LD A, (HL-)  | A = memory[HL], then HL--   | 1     | 8      |
# | 0xE0   | LDH (a8), A  | memory[0xFF00 + a8] = A     | 2     | 12     |
# | 0xF0   | LDH A, (a8)  | A = memory[0xFF00 + a8]     | 2     | 12     |
# | 0xE2   | LD (C), A    | memory[0xFF00 + C] = A      | 1     | 8      |
# | 0xF2   | LD A, (C)    | A = memory[0xFF00 + C]      | 1     | 8      |
# | 0xEA   | LD (a16), A  | memory[a16] = A             | 3     | 16     |
# | 0xFA   | LD A, (a16)  | A = memory[a16]             | 3     | 16     |
#
# Notes:
#   - The HL+/HL- forms access memory at HL *first*, then move the pointer.
#     The move wraps at 16 bits and costs nothing: it never touches the bus.
#   - The 0xFF00 page is the I/O register block. LDH and LD (C), A reach it
#     with one byte of offset instead of a full address, which is why they are
#     cheaper than LD (a16), A for the same destination.
#   - None of these touches the flags.


def _ld_bc_a(cpu: CPU) -> None:
    cpu.bus.write(cpu.registers.bc, cpu.registers.a)


def _ld_de_a(cpu: CPU) -> None:
    cpu.bus.write(cpu.registers.de, cpu.registers.a)


def _ld_a_bc(cpu: CPU) -> None:
    cpu.registers.a = cpu.bus.read(cpu.registers.bc)


def _ld_a_de(cpu: CPU) -> None:
    cpu.registers.a = cpu.bus.read(cpu.registers.de)


def _ld_hl_inc_a(cpu: CPU) -> None:
    cpu.bus.write(cpu.registers.hl, cpu.registers.a)
    cpu.registers.hl = u16(cpu.registers.hl + 1)


def _ld_hl_dec_a(cpu: CPU) -> None:
    cpu.bus.write(cpu.registers.hl, cpu.registers.a)
    cpu.registers.hl = u16(cpu.registers.hl - 1)


def _ld_a_hl_inc(cpu: CPU) -> None:
    cpu.registers.a = cpu.bus.read(cpu.registers.hl)
    cpu.registers.hl = u16(cpu.registers.hl + 1)


def _ld_a_hl_dec(cpu: CPU) -> None:
    cpu.registers.a = cpu.bus.read(cpu.registers.hl)
    cpu.registers.hl = u16(cpu.registers.hl - 1)


def _ld_a16_a(cpu: CPU) -> None:
    address = cpu.fetch_u16()
    cpu.bus.write(address, cpu.registers.a)


def _ld_a_a16(cpu: CPU) -> None:
    address = cpu.fetch_u16()
    cpu.registers.a = cpu.bus.read(address)


def _ldh_a8_a(cpu: CPU) -> None:
    address = u16(0xFF00 + cpu.fetch_u8())
    cpu.bus.write(address, cpu.registers.a)


def _ldh_a_a8(cpu: CPU) -> None:
    address = u16(0xFF00 + cpu.fetch_u8())
    cpu.registers.a = cpu.bus.read(address)


def _ld_c_a(cpu: CPU) -> None:
    address = u16(0xFF00 + cpu.registers.c)
    cpu.bus.write(address, cpu.registers.a)


def _ld_a_c(cpu: CPU) -> None:
    address = u16(0xFF00 + cpu.registers.c)
    cpu.registers.a = cpu.bus.read(address)


# ----------
# ALU Block
# ----------
# The ALU block, 0x80 to 0xBF. The bits read 10 ooo sss: operation in bits 5 to
# 3, source in bits 2 to 0. The destination is always A, which is why it is
# called the accumulator.
_ALU_OPERATIONS: Final[tuple[AluOperation, ...]] = (
    AluOperation("ADD", lambda a, b, _carry: add(a, b), writes_result=True),
    AluOperation("ADC", adc, writes_result=True),
    AluOperation("SUB", lambda a, b, _carry: sub(a, b), writes_result=True),
    AluOperation("SBC", sbc, writes_result=True),
    AluOperation("AND", lambda a, b, _carry: and_(a, b), writes_result=True),
    AluOperation("XOR", lambda a, b, _carry: xor(a, b), writes_result=True),
    AluOperation("OR", lambda a, b, _carry: or_(a, b), writes_result=True),
    AluOperation("CP", lambda a, b, _carry: sub(a, b), writes_result=False),
)


def _apply_alu(cpu: CPU, operation: AluOperation, value: int) -> None:
    result, flags = operation.apply(cpu.registers.a, value, cpu.registers.c_flag)
    cpu.registers.apply(flags)

    if operation.writes_result:
        cpu.registers.a = result


def _make_alu(operation: AluOperation, src: Operand) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        _apply_alu(cpu, operation=operation, value=read_operand(cpu, src))

    return execute


def _make_alu_immediate(operation: AluOperation) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        _apply_alu(cpu, operation=operation, value=cpu.fetch_u8())

    return execute


def _alu_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}
    for opcode in range(0x80, 0xC0):  # 10 ooo sss
        operation = _ALU_OPERATIONS[(opcode >> 3) & 0b111]
        src = Operand(opcode & 0b111)

        instructions[opcode] = Instruction(
            f"{operation.name} A, {src.assembly_name}",
            count_cycles(src),
            _make_alu(operation, src),
        )
    return instructions


def _alu_immediate_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}
    # Opcodes:   [0xC6, 0xCE, 0xD6, 0xDE, 0xE6, 0xEE, 0xF6, 0xFE]
    # Operation:  ADD   ADC   SUB   SBC   AND   XOR   OR    CP

    for opcode in range(0xC6, 0xFF, 8):  # 11 ooo 110
        operation = _ALU_OPERATIONS[(opcode >> 3) & 0b111]

        instructions[opcode] = Instruction(
            f"{operation.name} A, d8",
            count_cycles(immediates=1),
            _make_alu_immediate(operation),
        )
    return instructions


# The encoding: 00 rrr 100 is INC r,
#               00 rrr 101 is DEC r
# INC:  0x04 0x0C 0x14 0x1C 0x24 0x2C 0x34 0x3C
# DEC:  0x05 0x0D 0x15 0x1D 0x25 0x2D 0x35 0x3D
#         B    C    D    E    H    L  (HL)   A
def _make_inc_dec(
    operand: Operand, operation: Callable[[int], tuple[int, Flags]]
) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        current_value = read_operand(cpu, operand)
        result, flags = operation(current_value)
        cpu.registers.apply(flags)

        write_operand(cpu, operand, result)

    return execute


def _inc_dec_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}
    # INC block
    for opcode in range(0x04, 0x40, 8):
        operand = Operand((opcode >> 3) & 0b111)  #  00 rrr 100

        instructions[opcode] = Instruction(
            f"INC {operand.assembly_name}",
            count_cycles(operand, operand),  # twice, one for read, one for write
            _make_inc_dec(operand, inc),
        )

    # DEC block
    for opcode in range(0x05, 0x40, 8):
        operand = Operand((opcode >> 3) & 0b111)  #  00 rrr 101

        instructions[opcode] = Instruction(
            f"DEC {operand.assembly_name}",
            count_cycles(operand, operand),  # twice, one for read, one for write
            _make_inc_dec(operand, dec),
        )

    return instructions


# ------------------------------
# 16-bit loads and arithmetic
# ------------------------------
#
# | Opcodes                | Instruction  | Cycles | Flags                     |
# | ---------------------- | ------------ | ------ | ------------------------- |
# | 0x01 0x11 0x21 0x31    | LD rr, d16   | 12     | none                      |
# | 0x08                   | LD (a16), SP | 20     | none                      |
# | 0x03 0x13 0x23 0x33    | INC rr       | 8      | none at all               |
# | 0x0B 0x1B 0x2B 0x3B    | DEC rr       | 8      | none at all               |
# | 0x09 0x19 0x29 0x39    | ADD HL, rr   | 8      | Z kept, N=0, H@11, C@15   |


_LD_PAIR_IMMEDIATE_CYCLES = 12
_PAIR_INTERNAL_CYCLES = 8
_LD_A16_SP_CYCLES = 20


def _make_ld_pair_immediate(pair: RegisterPair) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        write_pair(cpu, pair, cpu.fetch_u16())

    return execute


def _make_inc_pair(pair: RegisterPair) -> Callable[[CPU], None]:
    # No flags
    def execute(cpu: CPU) -> None:
        write_pair(cpu, pair, u16(read_pair(cpu, pair) + 1))

    return execute


def _make_dec_pair(pair: RegisterPair) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        write_pair(cpu, pair, u16(read_pair(cpu, pair) - 1))

    return execute


def _make_add_hl(pair: RegisterPair) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        result, flags = add16(cpu.registers.hl, read_pair(cpu, pair))
        cpu.registers.apply(flags)
        cpu.registers.hl = result

    return execute


def _ld_a16_sp(cpu: CPU) -> None:
    address = cpu.fetch_u16()
    cpu.bus.write16(address, cpu.registers.sp)


# base opcode, mnemonic template, cycles, maker
_PAIR_FAMILIES: Final[
    tuple[tuple[int, str, int, Callable[[RegisterPair], Callable[[CPU], None]]], ...]
] = (
    (0x01, "LD {}, d16", _LD_PAIR_IMMEDIATE_CYCLES, _make_ld_pair_immediate),
    (0x03, "INC {}", _PAIR_INTERNAL_CYCLES, _make_inc_pair),
    (0x0B, "DEC {}", _PAIR_INTERNAL_CYCLES, _make_dec_pair),
    (0x09, "ADD HL, {}", _PAIR_INTERNAL_CYCLES, _make_add_hl),
)


def _pair_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}

    for base, template, cycles, make in _PAIR_FAMILIES:
        for opcode in range(base, base + 0x40, 0x10):
            pair = RegisterPair((opcode >> 4) & 0b11)

            instructions[opcode] = Instruction(
                template.format(pair.name),
                cycles,
                make(pair),
            )

    return instructions


# Accumulator and flag oddities
#
# | Opcode | Mnemonic | Effect              | Z         | N | H | C         |
# | ------ | -------- | ------------------- | --------- | - | - | --------- |
# | 0x27   | DAA      | fix A back into BCD | result    | - | 0 | see below |
# | 0x2F   | CPL      | A = ~A              | -         | 1 | 1 | -         |
# | 0x37   | SCF      | set carry           | -         | 0 | 0 | 1         |
# | 0x3F   | CCF      | flip carry          | -         | 0 | 0 | inverted  |

def _daa(cpu: CPU) -> None:
    result, flags = daa(
        cpu.registers.a,
        cpu.registers.n_flag,
        cpu.registers.h_flag,
        cpu.registers.c_flag,
    )
    cpu.registers.apply(flags)
    cpu.registers.a = result


def _cpl(cpu: CPU) -> None:
    cpu.registers.apply(Flags(n=True, h=True))
    cpu.registers.a = u8(~cpu.registers.a) # notice the mask to wrap on < 0


def _scf(cpu: CPU) -> None:
    cpu.registers.apply(Flags(n=False, h=False, c=True))


def _ccf(cpu: CPU) -> None:
    cpu.registers.apply(Flags(n=False, h=False, c=not cpu.registers.c_flag))


OPCODES: Final[dict[int, Instruction]] = {
    0x00: Instruction("NOP", 4, _nop),
    0xC3: Instruction("JP a16", 16, _jp_a16),
    0x02: Instruction("LD (BC), A", 8, _ld_bc_a),
    0x12: Instruction("LD (DE), A", 8, _ld_de_a),
    0x0A: Instruction("LD A, (BC)", 8, _ld_a_bc),
    0x1A: Instruction("LD A, (DE)", 8, _ld_a_de),
    0x22: Instruction("LD (HL+), A", count_cycles(Operand.HL_POINTER), _ld_hl_inc_a),
    0x32: Instruction("LD (HL-), A", count_cycles(Operand.HL_POINTER), _ld_hl_dec_a),
    0x2A: Instruction("LD A, (HL+)", count_cycles(Operand.HL_POINTER), _ld_a_hl_inc),
    0x3A: Instruction("LD A, (HL-)", count_cycles(Operand.HL_POINTER), _ld_a_hl_dec),
    0xEA: Instruction(
        "LD (a16), A", count_cycles(Operand.A, immediates=2, data_accesses=1), _ld_a16_a
    ),
    0xFA: Instruction(
        "LD A, (a16)", count_cycles(Operand.A, immediates=2, data_accesses=1), _ld_a_a16
    ),
    0xE0: Instruction("LDH (a8), A", 12, _ldh_a8_a),
    0xF0: Instruction("LDH A, (a8)", 12, _ldh_a_a8),
    0xE2: Instruction("LD (C), A", 8, _ld_c_a),
    0xF2: Instruction("LD A, (C)", 8, _ld_a_c),
    **_ld_block(),
    **_ld_immediate_block(),
    **_alu_block(),
    **_alu_immediate_block(),
    **_inc_dec_block(),
    0x08: Instruction("LD (a16), SP", _LD_A16_SP_CYCLES, _ld_a16_sp),
    **_pair_block(),
    0x27: Instruction("DAA", 4, _daa),
    0x2F: Instruction("CPL", 4, _cpl),
    0x37: Instruction("SCF", 4, _scf),
    0x3F: Instruction("CCF", 4, _ccf),
}
