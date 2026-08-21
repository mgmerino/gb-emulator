"""What the bits of an opcode mean, and how to act on them.

`Operand` is the `rrr` field, `RegisterPair` and `StackPair` are `pp`, and
`Condition` is `cc`. The accessors turn a decoded field into a read or a write
on a CPU. That is the vocabulary `cpu` and `instructions` have to agree on, so
it lives in the module neither of them imports from the other and the dependency
graph stays acyclic.

`CPU` appears only in annotations, so it is imported under `TYPE_CHECKING`, and
`from __future__ import annotations` keeps those annotations unevaluated at
runtime. Without both, this module and `cpu` would import each other.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gameboy.cpu import CPU


@dataclass(frozen=True, slots=True)
class Instruction:
    name: str
    cycles: int
    execute: Callable[[CPU], bool | None]
    cycles_when_taken: int | None = None


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


class StackPair(IntEnum):
    BC = 0b00
    DE = 0b01
    HL = 0b10
    AF = 0b11


def read_stack_pair(cpu: CPU, pair: StackPair) -> int:
    match pair:
        case StackPair.BC:
            return cpu.registers.bc
        case StackPair.DE:
            return cpu.registers.de
        case StackPair.HL:
            return cpu.registers.hl
        case StackPair.AF:
            return cpu.registers.af


def write_stack_pair(cpu: CPU, pair: StackPair, value: int) -> None:
    match pair:
        case StackPair.BC:
            cpu.registers.bc = value
        case StackPair.DE:
            cpu.registers.de = value
        case StackPair.HL:
            cpu.registers.hl = value
        case StackPair.AF:
            cpu.registers.af = value


class Condition(IntEnum):
    NZ = 0b00
    Z = 0b01
    NC = 0b10
    C = 0b11


def condition_met(cpu: CPU, condition: Condition) -> bool:
    match condition:
        case Condition.Z:
            return cpu.registers.z_flag
        case Condition.NZ:
            return not cpu.registers.z_flag
        case Condition.C:
            return cpu.registers.c_flag
        case Condition.NC:
            return not cpu.registers.c_flag
