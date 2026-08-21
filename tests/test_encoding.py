"""The operand accessors: that each field value reaches exactly one place."""

import pytest
from conftest import REGISTER_OPERANDS, CpuRunning

from gameboy.encoding import (
    Operand,
    read_operand,
    write_operand,
)


@pytest.mark.parametrize("operand", REGISTER_OPERANDS, ids=lambda operand: operand.name)
def test_register_operands_round_trip(
    cpu_running: CpuRunning, operand: Operand
) -> None:
    cpu = cpu_running()

    write_operand(cpu, operand, 0xAF)

    assert read_operand(cpu, operand) == 0xAF
    assert getattr(cpu.registers, operand.name.lower()) == 0xAF


@pytest.mark.parametrize("operand", REGISTER_OPERANDS, ids=lambda operand: operand.name)
def test_register_operands_touch_exactly_one_register(
    cpu_running: CpuRunning, operand: Operand
) -> None:
    """A write to one index leaves the other six untouched."""
    cpu = cpu_running()
    written = operand.name.lower()

    write_operand(cpu, operand, 0xAF)

    untouched = [
        other.name.lower() for other in REGISTER_OPERANDS if other is not operand
    ]
    assert all(getattr(cpu.registers, name) == 0 for name in untouched), written


def test_hl_pointer_operand_follows_hl_wherever_it_points(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running()

    cpu.registers.hl = 0xC123
    write_operand(cpu, Operand.HL_POINTER, 0xAF)

    cpu.registers.hl = 0xC456
    write_operand(cpu, Operand.HL_POINTER, 0x5A)

    assert cpu.bus.read(0xC123) == 0xAF
    assert cpu.bus.read(0xC456) == 0x5A

    # And the same on the way back in, at both addresses: one read would pass
    # against an accessor that always used the address the test happens to end on.
    cpu.registers.hl = 0xC123
    assert read_operand(cpu, Operand.HL_POINTER) == 0xAF

    cpu.registers.hl = 0xC456
    assert read_operand(cpu, Operand.HL_POINTER) == 0x5A


def test_hl_is_data_in_two_slots_and_an_address_in_a_third(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running()
    cpu.registers.hl = 0xC123
    cpu.bus.write(0xC123, 0x5A)

    assert read_operand(cpu, Operand.H) == 0xC1
    assert read_operand(cpu, Operand.L) == 0x23
    assert read_operand(cpu, Operand.HL_POINTER) == 0x5A


def test_writing_an_unmasked_value_to_a_register_operand_is_rejected(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running()

    with pytest.raises(ValueError, match="register b"):
        write_operand(cpu, Operand.B, 0x1FF)
