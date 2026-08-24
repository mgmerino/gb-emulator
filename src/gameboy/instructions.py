"""Every instruction body, the block generators, the cycle rule they cost
their entries with, and the two opcode tables.

Nothing here touches `cpu` at runtime: a body receives a `CPU` and calls methods
on it, so the import is annotation-only. That is what lets `cpu.step()` import
`OPCODES` and `CB_OPCODES` from this module without a cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from gameboy.alu import (
    Flags,
    adc,
    add,
    add16,
    add_sp_e8,
    and_,
    daa,
    dec,
    inc,
    or_,
    rl,
    rlc,
    rr,
    rrc,
    sbc,
    sla,
    sra,
    srl,
    sub,
    swap,
    xor,
)
from gameboy.bits import clear_bit, get_bit, set_bit, to_signed8, u8, u16
from gameboy.encoding import (
    Condition,
    Instruction,
    Operand,
    RegisterPair,
    StackPair,
    condition_met,
    read_operand,
    read_pair,
    read_stack_pair,
    write_operand,
    write_pair,
    write_stack_pair,
)

if TYPE_CHECKING:
    from gameboy.cpu import CPU


@dataclass(frozen=True, slots=True)
class AluOperation:
    name: str
    apply: Callable[[int, int, bool], tuple[int, Flags]]
    writes_result: bool


@dataclass(frozen=True, slots=True)
class ShiftOperation:
    name: str
    apply: Callable[[int, bool], tuple[int, Flags]]


T_CYCLES_PER_ACCESS = 4


def count_cycles(
    *accesses: Operand,
    immediates: int = 0,
    data_accesses: int = 0,
    prefixed: bool = False,
) -> int:
    """Cost of one generated instruction:
    - one access for the opcode fetch,
    - one extra if prefixed (additional opcode fetch)
    - one per immediate byte,
    - and one for every operand access that reads memory.
    """
    total = 1  # the fetch cost one
    if prefixed:
        total += 1

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
    cpu.registers.a = u8(~cpu.registers.a)  # notice the mask to wrap on < 0


def _scf(cpu: CPU) -> None:
    cpu.registers.apply(Flags(n=False, h=False, c=True))


def _ccf(cpu: CPU) -> None:
    cpu.registers.apply(Flags(n=False, h=False, c=not cpu.registers.c_flag))


# ------------------
# JR - relative jumps
# ------------------
#
# | Opcodes             | Instruction | Cycles  | Flags |
# | ------------------- | ----------- | ------- | ----- |
# | 0x18                | JR e8       | 12      | none  |
# | 0x20 0x28 0x30 0x38 | JR cc, e8   | 12 / 8  | none  |
#
# The offset is signed, and relative to the address of the instruction *after*
# the JR. Fetching the operand already moved PC there, so there is no
# correction term.
#
# cc is bits 4 and 3: 00 NZ, 01 Z, 10 NC, 11 C. Same field in all four
# conditional families.
#
# The operand is fetched whether or not the branch is taken. A body that
# returns early leaves PC pointing at an operand byte.


def _jr_e8(cpu: CPU) -> None:
    offset_jump = to_signed8(cpu.fetch_u8())
    cpu.registers.pc = u16(cpu.registers.pc + offset_jump)


def _jr_nz_e8(cpu: CPU) -> bool:
    offset_jump = to_signed8(cpu.fetch_u8())
    if condition_met(cpu, Condition.NZ):
        cpu.registers.pc = u16(cpu.registers.pc + offset_jump)
        return True

    return False


def _jr_z_e8(cpu: CPU) -> bool:
    offset_jump = to_signed8(cpu.fetch_u8())
    if condition_met(cpu, Condition.Z):
        cpu.registers.pc = u16(cpu.registers.pc + offset_jump)
        return True

    return False


def _jr_nc_e8(cpu: CPU) -> bool:
    offset_jump = to_signed8(cpu.fetch_u8())
    if condition_met(cpu, Condition.NC):
        cpu.registers.pc = u16(cpu.registers.pc + offset_jump)
        return True

    return False


def _jr_c_e8(cpu: CPU) -> bool:
    offset_jump = to_signed8(cpu.fetch_u8())
    if condition_met(cpu, Condition.C):
        cpu.registers.pc = u16(cpu.registers.pc + offset_jump)
        return True

    return False


# ------------------
# JP - absolute jumps
# ------------------
#
# | Opcodes             | Instruction | Cycles  | Flags |
# | ------------------- | ----------- | ------- | ----- |
# | 0xC3                | JP a16      | 16      | none  |
# | 0xC2 0xCA 0xD2 0xDA | JP cc, a16  | 16 / 12 | none  |
# | 0xE9                | JP HL       | 4       | none  |
#
# 0xC3's body lives with the Step 04 code near the top of the file.
#
# JP HL reads no memory: it copies HL into PC. The 4 cycles are the proof, one
# fetch and no access. Tables that print it as `JP (HL)` are lying; it is how
# you implement a jump table.


def _jp_hl(cpu: CPU) -> None:
    address = cpu.registers.hl
    cpu.registers.pc = address


def _jp_nz_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.NZ):
        cpu.registers.pc = address
        return True

    return False


def _jp_z_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.Z):
        cpu.registers.pc = address
        return True

    return False


def _jp_nc_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.NC):
        cpu.registers.pc = address
        return True

    return False


def _jp_c_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.C):
        cpu.registers.pc = address
        return True

    return False


# -------------------------
# CALL - call a subroutine
# -------------------------
#
# | Opcodes             | Instruction  | Cycles  | Flags |
# | ------------------- | ------------ | ------- | ----- |
# | 0xCD                | CALL a16     | 24      | none  |
# | 0xC4 0xCC 0xD4 0xDC | CALL cc, a16 | 24 / 12 | none  |
#
# The return address is never computed. Fetching the operand already left PC
# past the instruction, so pushing PC is the whole of it.
#
# 24 cycles for five memory accesses: the extra machine cycle is the 16-bit
# decrement of SP, the same one PUSH pays for.


def _call_a16(cpu: CPU) -> None:
    address = cpu.fetch_u16()
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = address


def _call_nz_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.NZ):
        cpu.push16(cpu.registers.pc)
        cpu.registers.pc = address
        return True

    return False


def _call_z_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.Z):
        cpu.push16(cpu.registers.pc)
        cpu.registers.pc = address
        return True

    return False


def _call_nc_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.NC):
        cpu.push16(cpu.registers.pc)
        cpu.registers.pc = address
        return True

    return False


def _call_c_a16(cpu: CPU) -> bool:
    address = cpu.fetch_u16()
    if condition_met(cpu, Condition.C):
        cpu.push16(cpu.registers.pc)
        cpu.registers.pc = address
        return True

    return False


# ------------------------------
# RET - return from a subroutine
# ------------------------------
#
# | Opcodes             | Instruction | Cycles | Flags |
# | ------------------- | ----------- | ------ | ----- |
# | 0xC9                | RET         | 16     | none  |
# | 0xC0 0xC8 0xD0 0xD8 | RET cc      | 20 / 8 | none  |
#
# RET cc costs 20 taken against RET's 16 with identical memory accesses. That
# extra machine cycle is the condition test itself.
#
# RETI (0xD9) is deliberately absent: it re-enables interrupts, which do not
# exist until Step 08.


def _ret(cpu: CPU) -> None:
    cpu.registers.pc = cpu.pop16()


def _ret_nz(cpu: CPU) -> bool:
    if condition_met(cpu, Condition.NZ):
        cpu.registers.pc = cpu.pop16()
        return True

    return False


def _ret_z(cpu: CPU) -> bool:
    if condition_met(cpu, Condition.Z):
        cpu.registers.pc = cpu.pop16()
        return True

    return False


def _ret_nc(cpu: CPU) -> bool:
    if condition_met(cpu, Condition.NC):
        cpu.registers.pc = cpu.pop16()
        return True

    return False


def _ret_c(cpu: CPU) -> bool:
    if condition_met(cpu, Condition.C):
        cpu.registers.pc = cpu.pop16()
        return True

    return False


# -------------
# PUSH and POP
# -------------
#
# | Opcodes             | Instruction      | Cycles | Flags       |
# | ------------------- | ---------------- | ------ | ----------- |
# | 0xC5 0xD5 0xE5 0xF5 | PUSH BC/DE/HL/AF | 16     | none        |
# | 0xC1 0xD1 0xE1 0xF1 | POP BC/DE/HL/AF  | 12     | POP AF only |
#
# The pair index sits in bits 5 and 4, the same field as the 16-bit block --
# but 0b11 means AF here and SP there. That is why StackPair exists next to
# RegisterPair rather than reusing it.
#
# PUSH costs 16 against POP's 12 with the same three accesses: the difference
# is the 16-bit decrement of SP.
#
# POP AF writes F, whose low nibble does not exist in hardware. Popping 0x1234
# leaves F at 0x30. The four booleans behind the `f` property give that for
# free.


def _push_bc(cpu: CPU) -> None:
    value = read_stack_pair(cpu, StackPair.BC)
    cpu.push16(value)


def _push_de(cpu: CPU) -> None:
    value = read_stack_pair(cpu, StackPair.DE)
    cpu.push16(value)


def _push_hl(cpu: CPU) -> None:
    value = read_stack_pair(cpu, StackPair.HL)
    cpu.push16(value)


def _push_af(cpu: CPU) -> None:
    value = read_stack_pair(cpu, StackPair.AF)
    cpu.push16(value)


def _pop_bc(cpu: CPU) -> None:
    value = cpu.pop16()
    write_stack_pair(cpu, StackPair.BC, value)


def _pop_de(cpu: CPU) -> None:
    value = cpu.pop16()
    write_stack_pair(cpu, StackPair.DE, value)


def _pop_hl(cpu: CPU) -> None:
    value = cpu.pop16()
    write_stack_pair(cpu, StackPair.HL, value)


def _pop_af(cpu: CPU) -> None:
    value = cpu.pop16()
    write_stack_pair(cpu, StackPair.AF, value)


# -----------------------------------
# RST - one-byte calls to a fixed page
# -----------------------------------
#
# Encoded 11 ttt 111, target is ttt * 8. All eight cost 16 and touch no flags.
#
# | Opcode | Target | Opcode | Target |
# | ------ | ------ | ------ | ------ |
# | 0xC7   | 0x0000 | 0xE7   | 0x0020 |
# | 0xCF   | 0x0008 | 0xEF   | 0x0028 |
# | 0xD7   | 0x0010 | 0xF7   | 0x0030 |
# | 0xDF   | 0x0018 | 0xFF   | 0x0038 |
#
# One byte instead of three, so a routine called from hundreds of places costs
# a third of the ROM space. Not to be confused with the interrupt vectors at
# 0x40..0x60 in Step 08: two different tables that live near each other.
#
# 0xFF is RST 0x38, and unmapped memory reads as 0xFF. A trace that turns into
# an endless RST 0x38 is not a bug in RST -- it is evidence that a jump went
# wrong several instructions earlier.


def _rst_00(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x00


def _rst_10(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x10


def _rst_08(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x08


def _rst_18(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x18


def _rst_20(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x20


def _rst_28(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x28


def _rst_30(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x30


def _rst_38(cpu: CPU) -> None:
    cpu.push16(cpu.registers.pc)
    cpu.registers.pc = 0x38


def _add_sp_e8(cpu: CPU) -> None:
    offset_jump = to_signed8(cpu.fetch_u8())
    result, flags = add_sp_e8(cpu.registers.sp, offset_jump)

    cpu.registers.apply(flags)

    cpu.registers.sp = result


def _ld_hl_sp_e8(cpu: CPU) -> None:
    offset_jump = to_signed8(cpu.fetch_u8())
    result, flags = add_sp_e8(cpu.registers.sp, offset_jump)

    cpu.registers.apply(flags)

    cpu.registers.hl = result


def _ld_sp_hl(cpu: CPU) -> None:
    cpu.registers.sp = cpu.registers.hl


#
# --- ROTATE/SHIFT BLOCK
#
# 00 ooo rrr
#    |   └── Operand:   (opcode & 0b111)
#    └────── Operation: (opcode >> 3) & 0b111
# ┌─────┬─────┬─────┬──────┐
# │ ooo │     │ ooo │      │
# ├─────┼─────┼─────┼──────┤
# │ 000 │ RLC │ 100 │ SLA  │
# ├─────┼─────┼─────┼──────┤
# │ 001 │ RRC │ 101 │ SRA  │
# ├─────┼─────┼─────┼──────┤
# │ 010 │ RL  │ 110 │ SWAP │
# ├─────┼─────┼─────┼──────┤
# │ 011 │ RR  │ 111 │ SRL  │
# └─────┴─────┴─────┴──────┘


_SHIFT_OPERATIONS: Final[tuple[ShiftOperation, ...]] = (
    ShiftOperation("RLC", lambda a, _carry: rlc(a)),
    ShiftOperation("RRC", lambda a, _carry: rrc(a)),
    ShiftOperation("RL", rl),
    ShiftOperation("RR", rr),
    ShiftOperation("SLA", lambda a, _carry: sla(a)),
    ShiftOperation("SRA", lambda a, _carry: sra(a)),
    ShiftOperation("SWAP", lambda a, _carry: swap(a)),
    ShiftOperation("SRL", lambda a, _carry: srl(a)),
)


def _make_shift(operand: Operand, operation: ShiftOperation) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        value = read_operand(cpu, operand)
        result, flags = operation.apply(value, cpu.registers.c_flag)
        cpu.registers.apply(flags)
        write_operand(cpu, operand, result)

    return execute


def _shift_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}
    for opcode in range(0x40):
        operation = _SHIFT_OPERATIONS[(opcode >> 3) & 0b111]
        operand = Operand(opcode & 0b111)

        instructions[opcode] = Instruction(
            f"{operation.name} {operand.assembly_name}",
            count_cycles(operand, operand, prefixed=True),
            _make_shift(operand, operation),
        )

    return instructions


# --------------------
# CB BIT, RES and SET
# --------------------
#
#
# | Range         | Bits       | Family   |
# | ------------- | ---------- | -------- |
# | 0x40 - 0x7F   | 01 bbb rrr | BIT b, r |
# | 0x80 - 0xBF   | 10 bbb rrr | RES b, r |
# | 0xC0 - 0xFF   | 11 bbb rrr | SET b, r |
#
# rrr: 000 B, 001 C, 010 D, 011 E, 100 H, 101 L, 110 (HL), 111 A
# bbb: 0 to 7, counting from the LSB.
#
# So the opcode is base + bit * 8 + operand:
#
#   BIT 7, (HL)  =  0x40 + 7*8 + 6  =  0x7E
#   RES 3, A     =  0x80 + 3*8 + 7  =  0x9F
#   SET 0, B     =  0xC0 + 0*8 + 0  =  0xC0
#
# | Family | Effect                  | Z         | N | H | C    | r | (HL) |
# | ------ | ----------------------- | --------- | - | - | ---- | - | ---- |
# | BIT    | test bit b, discard it  | NOT bit b | 0 | 1 | kept | 8 | 12   |
# | RES    | value AND NOT (1 << b)  | -         | - | - | -    | 8 | 16   |
# | SET    | value OR (1 << b)       | -         | - | - | -    | 8 | 16   |
#


def _make_bit(operand: Operand, index: int) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        value = read_operand(cpu, operand)
        bit = get_bit(value, index)
        cpu.registers.apply(Flags(z=not bit, n=False, h=True))

    return execute


def _make_res(operand: Operand, index: int) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        value = read_operand(cpu, operand)
        write_operand(cpu, operand, clear_bit(value, index))

    return execute


def _make_set(operand: Operand, index: int) -> Callable[[CPU], None]:
    def execute(cpu: CPU) -> None:
        value = read_operand(cpu, operand)
        write_operand(cpu, operand, set_bit(value, index))

    return execute


def _bit_res_set_block() -> dict[int, Instruction]:
    instructions: dict[int, Instruction] = {}

    # BIT block
    for opcode in range(0x40, 0x80):
        operand = Operand(opcode & 0b111)
        bit_index = (opcode >> 3) & 0b111

        instructions[opcode] = Instruction(
            f"BIT {bit_index}, {operand.assembly_name}",
            count_cycles(operand, prefixed=True),
            _make_bit(operand, bit_index),
        )

    # RES block
    for opcode in range(0x80, 0xC0):
        operand = Operand(opcode & 0b111)
        bit_index = (opcode >> 3) & 0b111

        instructions[opcode] = Instruction(
            f"RES {bit_index}, {operand.assembly_name}",
            count_cycles(operand, operand, prefixed=True),
            _make_res(operand, bit_index),
        )

    # SET block
    for opcode in range(0xC0, 0x100):
        operand = Operand(opcode & 0b111)
        bit_index = (opcode >> 3) & 0b111

        instructions[opcode] = Instruction(
            f"SET {bit_index}, {operand.assembly_name}",
            count_cycles(operand, operand, prefixed=True),
            _make_set(operand, bit_index),
        )

    return instructions


#
# --- RLCA, RRCA, RLA, RRA ---
#
# `Flags` is frozen, so `replace` returns a copy of what the alu produced with
# z forced to False: these four always clear Z, while their CB twins take it
# from the result. Keeping the override here leaves alu.py with one rule.


def _rlca(cpu: CPU) -> None:
    result, flags = rlc(cpu.registers.a)
    cpu.registers.apply(replace(flags, z=False))
    cpu.registers.a = result


def _rrca(cpu: CPU) -> None:
    result, flags = rrc(cpu.registers.a)
    cpu.registers.apply(replace(flags, z=False))
    cpu.registers.a = result


def _rla(cpu: CPU) -> None:
    result, flags = rl(cpu.registers.a, cpu.registers.c_flag)
    cpu.registers.apply(replace(flags, z=False))
    cpu.registers.a = result


def _rra(cpu: CPU) -> None:
    result, flags = rr(cpu.registers.a, cpu.registers.c_flag)
    cpu.registers.apply(replace(flags, z=False))
    cpu.registers.a = result


#
# --- Interrupts
#


def _di(cpu: CPU) -> None:
    cpu.ime = False


def _ei(cpu: CPU) -> None:
    cpu.ime_pending = True


def _reti(cpu: CPU) -> None:
    cpu.registers.pc = cpu.pop16()
    cpu.ime = True


def _halt(cpu: CPU) -> None:
    cpu.halted = True


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
    0x18: Instruction("JR e8", 12, _jr_e8),
    0x20: Instruction("JR NZ, e8", 8, _jr_nz_e8, 12),
    0x28: Instruction("JR Z, e8", 8, _jr_z_e8, 12),
    0x30: Instruction("JR NC, e8", 8, _jr_nc_e8, 12),
    0x38: Instruction("JR C, e8", 8, _jr_c_e8, 12),
    0xC2: Instruction("JP NZ, a16", 12, _jp_nz_a16, 16),
    0xCA: Instruction("JP Z, a16", 12, _jp_z_a16, 16),
    0xD2: Instruction("JP NC, a16", 12, _jp_nc_a16, 16),
    0xDA: Instruction("JP C, a16", 12, _jp_c_a16, 16),
    0xE9: Instruction("JP HL", 4, _jp_hl),
    0xCD: Instruction("CALL a16", 24, _call_a16),
    0xC4: Instruction("CALL NZ, a16", 12, _call_nz_a16, 24),
    0xCC: Instruction("CALL Z, a16", 12, _call_z_a16, 24),
    0xD4: Instruction("CALL NC, a16", 12, _call_nc_a16, 24),
    0xDC: Instruction("CALL C, a16", 12, _call_c_a16, 24),
    0xC9: Instruction("RET", 16, _ret),
    0xC0: Instruction("RET NZ", 8, _ret_nz, 20),
    0xC8: Instruction("RET Z", 8, _ret_z, 20),
    0xD0: Instruction("RET NC", 8, _ret_nc, 20),
    0xD8: Instruction("RET C", 8, _ret_c, 20),
    0xC5: Instruction("PUSH BC", 16, _push_bc),
    0xD5: Instruction("PUSH DE", 16, _push_de),
    0xE5: Instruction("PUSH HL", 16, _push_hl),
    0xF5: Instruction("PUSH AF", 16, _push_af),
    0xC1: Instruction("POP BC", 12, _pop_bc),
    0xD1: Instruction("POP DE", 12, _pop_de),
    0xE1: Instruction("POP HL", 12, _pop_hl),
    0xF1: Instruction("POP AF", 12, _pop_af),
    0xC7: Instruction("RST 0x00", 16, _rst_00),
    0xCF: Instruction("RST 0x08", 16, _rst_08),
    0xD7: Instruction("RST 0x10", 16, _rst_10),
    0xDF: Instruction("RST 0x18", 16, _rst_18),
    0xE7: Instruction("RST 0x20", 16, _rst_20),
    0xEF: Instruction("RST 0x28", 16, _rst_28),
    0xF7: Instruction("RST 0x30", 16, _rst_30),
    0xFF: Instruction("RST 0x38", 16, _rst_38),
    0xE8: Instruction("ADD SP, e8", 16, _add_sp_e8),
    0xF8: Instruction("LD HL, SP+e8", 12, _ld_hl_sp_e8),
    0xF9: Instruction("LD SP, HL", 8, _ld_sp_hl),
    0x07: Instruction("RLCA", 4, _rlca),
    0x0F: Instruction("RRCA", 4, _rrca),
    0x17: Instruction("RLA", 4, _rla),
    0x1F: Instruction("RRA", 4, _rra),
    0xF3: Instruction("DI", 4, _di),
    0xFB: Instruction("EI", 4, _ei),
    0xD9: Instruction("RETI", 16, _reti),
    0x76: Instruction("HALT", 4, _halt),
}

# The CB-prefixed table, the 0xCB escape in `step()`.
#
# Cycle counts here include the prefix fetch.
CB_OPCODES: Final[dict[int, Instruction]] = {
    **_shift_block(),
    **_bit_res_set_block(),
}
