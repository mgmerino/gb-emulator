import pytest
from conftest import CpuRunning

from gameboy.alu import Flags
from gameboy.cpu import (
    Operand,
    Registers,
    UnknownOpcodeError,
    read_operand,
    write_operand,
)

REGISTER_OPERANDS = [
    Operand.B,
    Operand.C,
    Operand.D,
    Operand.E,
    Operand.H,
    Operand.L,
    Operand.A,
]


def test_pair_composes_from_its_halves(registers: Registers) -> None:
    registers.b = 0x23
    registers.c = 0xEE

    assert registers.bc == 0x23EE


def test_pair_decomposes_into_its_halves(registers: Registers) -> None:
    registers.bc = 0x109A

    assert registers.b == 0x10
    assert registers.c == 0x9A


@pytest.mark.parametrize(
    "pair,high,low", [("bc", 0x23, 0xEA), ("de", 0x72, 0x34), ("hl", 0x13, 0x10)]
)
def test_every_pair_composes(
    registers: Registers, pair: str, high: int, low: int
) -> None:

    setattr(registers, pair, (high << 8) | low)

    assert getattr(registers, pair[0]) == high
    assert getattr(registers, pair[1]) == low


def test_af_composes_from_a_and_the_flag_byte(registers: Registers) -> None:
    registers.a = 0x10
    registers.f = 0x90

    assert registers.af == 0x1090


def test_flag_byte_is_zero_when_no_flag_is_set(registers: Registers) -> None:
    assert registers.f == 0x00


def test_flag_byte_is_f0_when_every_flag_is_set(registers: Registers) -> None:
    registers.z_flag = True
    registers.n_flag = True
    registers.h_flag = True
    registers.c_flag = True

    assert registers.f == 0xF0


@pytest.mark.parametrize(
    "flag,bit",
    [("z_flag", 0x80), ("n_flag", 0x40), ("h_flag", 0x20), ("c_flag", 0x10)],
)
def test_each_flag_lands_in_its_own_bit(
    registers: Registers, flag: str, bit: int
) -> None:
    setattr(registers, flag, True)

    assert registers.f == bit


def test_flag_byte_unpacks_into_the_four_flags(registers: Registers) -> None:
    registers.af = 0x10BA
    # from the low byte, we only take the first nibble 0xB, which translates to
    # 0b1011, so z = true, n = false, h = true, c = true

    assert registers.a == 0x10
    assert registers.f == 0xB0  # The low nibble is lost
    assert registers.z_flag
    assert not registers.n_flag
    assert registers.h_flag
    assert registers.c_flag


def test_flag_byte_round_trips(registers: Registers) -> None:
    registers.f = 0xC0

    assert registers.f == 0xC0


def test_flag_low_nibble_has_no_storage(registers: Registers) -> None:
    registers.f = 0xFF

    assert registers.f == 0xF0


def test_af_low_nibble_has_no_storage(registers: Registers) -> None:
    registers.af = 0x10BA

    assert registers.af == 0x10B0


_FIRST_TOO_WIDE = [
    ("a", 0x100),
    ("b", 0x100),
    ("c", 0x100),
    ("d", 0x100),
    ("e", 0x100),
    ("h", 0x100),
    ("l", 0x100),
    ("f", 0x100),
    ("sp", 0x10000),
    ("pc", 0x10000),
    ("af", 0x10000),
    ("bc", 0x10000),
    ("de", 0x10000),
    ("hl", 0x10000),
]


@pytest.mark.parametrize("name,value", _FIRST_TOO_WIDE)
def test_register_rejects_a_value_wider_than_itself(
    registers: Registers, name: str, value: int
) -> None:
    with pytest.raises(ValueError):
        setattr(registers, name, value)


@pytest.mark.parametrize("name", [name for name, _ in _FIRST_TOO_WIDE])
def test_register_rejects_a_negative_value(registers: Registers, name: str) -> None:
    with pytest.raises(ValueError):
        setattr(registers, name, -1)


@pytest.mark.parametrize("name", [name for name, _ in _FIRST_TOO_WIDE])
def test_register_rejects_a_non_integer(registers: Registers, name: str) -> None:
    with pytest.raises(ValueError):
        setattr(registers, name, "0x10")


def test_widest_accepted_value_is_stored(registers: Registers) -> None:
    # The other side of the boundary: one below each rejected value is fine.
    registers.a = 0xFF
    registers.pc = 0xFFFF
    registers.hl = 0xFFFF

    assert registers.a == 0xFF
    assert registers.pc == 0xFFFF
    assert registers.hl == 0xFFFF


def test_a_rejected_pair_assignment_leaves_both_halves_untouched(
    registers: Registers,
) -> None:
    # The guard runs before the property setter, so nothing is half-written.
    registers.hl = 0xBEEF

    with pytest.raises(ValueError):
        registers.hl = 0x10000

    assert registers.h == 0xBE
    assert registers.l == 0xEF


def test_registers_default_to_zero(registers: Registers) -> None:
    assert registers.a == 0
    assert registers.b == 0
    assert registers.c == 0
    assert registers.d == 0
    assert registers.e == 0
    assert registers.h == 0
    assert registers.l == 0
    assert registers.sp == 0
    assert registers.pc == 0
    assert not registers.z_flag
    assert not registers.n_flag
    assert not registers.h_flag
    assert not registers.c_flag


def test_post_boot_matches_the_hardware_table() -> None:
    # a == 0x01, sp == 0xFFFE, pc == 0x0100, and the rest of the table.
    registers = Registers.post_boot()

    assert registers.a == 0x01
    assert registers.b == 0x00
    assert registers.c == 0x13
    assert registers.d == 0x00
    assert registers.e == 0xD8
    assert registers.h == 0x01
    assert registers.l == 0x4D
    assert registers.pc == 0x0100
    assert registers.sp == 0xFFFE


def test_apply_set_expected_values_other_flags_keep_pristine() -> None:
    registers = Registers(c_flag=True)
    flags = Flags(z=True)

    registers.apply(flags)

    assert registers.c_flag
    assert registers.z_flag


def test_post_boot_af_is_01b0() -> None:
    registers = Registers.post_boot()

    assert registers.af == 0x01B0


def test_fetch_u8_returns_the_byte_and_advances_pc(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0x3C)

    assert cpu.fetch_u8() == 0x3C
    assert cpu.registers.pc == 0x0101


def test_fetch_u16_is_little_endian_and_advances_pc_by_two(
    cpu_running: CpuRunning,
) -> None:
    # Low byte first in memory: 0x34, then 0x12  ->  0x1234
    cpu = cpu_running(0x34, 0x12)

    assert cpu.fetch_u16() == 0x1234
    assert cpu.registers.pc == 0x0102


def test_fetch_wraps_at_the_top_of_memory(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0x99, at=0xFFFF)

    assert cpu.fetch_u8() == 0x99
    assert cpu.registers.pc == 0x0000


def test_nop_advances_pc_by_one_and_costs_four_cycles(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0x00)

    assert cpu.step() == 4
    assert cpu.registers.pc == 0x0101


def test_jp_sets_pc_to_its_operand_and_costs_sixteen_cycles(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xC3, 0x50, 0x01)

    assert cpu.step() == 16
    assert cpu.registers.pc == 0x0150


def test_unknown_opcode_raises_with_the_opcode_and_its_address(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xD3)

    with pytest.raises(UnknownOpcodeError, match="0xD3") as excinfo:
        cpu.step()

    assert excinfo.value.opcode == 0xD3
    assert excinfo.value.address == 0x0100


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
