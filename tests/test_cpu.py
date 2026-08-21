import pytest
from conftest import CpuRunning

from gameboy.alu import Flags
from gameboy.cpu import Registers, UnknownOpcodeError
from gameboy.encoding import (
    Operand,
    RegisterPair,
    read_operand,
    read_pair,
    write_operand,
    write_pair,
)
from gameboy.instructions import CB_OPCODES, OPCODES, count_cycles

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


# --- THE STACK ---


def test_push_moves_sp_down_two_and_writes_the_low_byte_first(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running()
    cpu.registers.sp = 0xFFFE

    cpu.push16(0x1234)

    assert cpu.registers.sp == 0xFFFC
    assert cpu.bus.read(0xFFFC) == 0x34
    assert cpu.bus.read(0xFFFD) == 0x12


def test_push_then_pop_returns_the_value_and_restores_sp(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running()
    cpu.registers.sp = 0xFFFE

    cpu.push16(0x1234)

    assert cpu.pop16() == 0x1234
    assert cpu.registers.sp == 0xFFFE


def test_the_stack_pops_in_reverse_order(cpu_running: CpuRunning) -> None:
    cpu = cpu_running()
    cpu.registers.sp = 0xFFFE

    cpu.push16(0xAABB)
    cpu.push16(0xCCDD)

    assert cpu.pop16() == 0xCCDD
    assert cpu.pop16() == 0xAABB
    assert cpu.registers.sp == 0xFFFE


def test_sp_wraps_at_sixteen_bits(cpu_running: CpuRunning) -> None:
    cpu = cpu_running()
    cpu.registers.sp = 0x0000

    cpu.push16(0x1234)

    assert cpu.registers.sp == 0xFFFE


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


def test_ld_copies_the_source_register_and_leaves_it_intact(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0x41)
    cpu.registers.b = 0xFF
    cpu.registers.c = 0x5A

    assert cpu.step() == 4
    assert cpu.registers.b == 0x5A
    assert cpu.registers.c == 0x5A
    assert cpu.registers.pc == 0x0101
    assert not cpu.registers.z_flag
    assert not cpu.registers.n_flag
    assert not cpu.registers.h_flag
    assert not cpu.registers.c_flag


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


@pytest.mark.parametrize(
    "expected, accesses, immediates",
    [
        # No operands at all: the opcode fetch is still one access.
        (4, (), 0),
        # Register operands are wires inside the chip and cost nothing.
        (4, (Operand.B, Operand.C), 0),
        # Index 6 is a bus access wherever it appears.
        (8, (Operand.B, Operand.HL_POINTER), 0),
        (8, (Operand.HL_POINTER, Operand.B), 0),
        (8, (Operand.HL_POINTER,), 0),
        # An immediate byte lives in the instruction stream, which is memory.
        (8, (), 1),
        (8, (Operand.B,), 1),
        (12, (Operand.HL_POINTER,), 1),
        (12, (), 2),
        # Read-modify-write passes the same operand twice, because the
        # instruction touches it twice. Free for a register, charged for memory.
        (4, (Operand.B, Operand.B), 0),
        (12, (Operand.HL_POINTER, Operand.HL_POINTER), 0),
        # The widest operation the rule covers: three instruction bytes and a
        # write.
        (16, (Operand.HL_POINTER,), 2),
    ],
)
def test_count_cycles_counts_memory_accesses(
    expected: int, accesses: tuple[Operand, ...], immediates: int
) -> None:
    assert count_cycles(*accesses, immediates=immediates) == expected


def test_count_cycles_charges_four_per_access() -> None:
    assert count_cycles() == 4
    assert count_cycles(Operand.HL_POINTER) - count_cycles(Operand.B) == 4
    assert count_cycles(immediates=1) - count_cycles() == 4


def test_count_cycles_with_prefixed_costs() -> None:
    assert count_cycles(Operand.B, Operand.B, prefixed=True) == 8
    assert count_cycles(Operand.HL_POINTER, Operand.HL_POINTER, prefixed=True) == 16
    assert count_cycles(Operand.B, prefixed=True) == 8
    assert count_cycles(Operand.HL_POINTER, prefixed=True) == 12


#
#  --- LOAD BLOCK ---
#

# Decoded from the bit pattern, the same way the generator.
LOAD_BLOCK = [
    (opcode, Operand((opcode >> 3) & 0b111), Operand(opcode & 0b111))
    for opcode in range(0x40, 0x80)
    if opcode != 0x76  # HALT
]

# The eight `00 rrr 110` opcodes and the register it targets.
LD_IMMEDIATE: list[tuple[int, Operand]] = [
    (0x06, Operand.B),  # LD B, d8
    (0x0E, Operand.C),  # LD C, d8
    (0x16, Operand.D),  # LD D, d8
    (0x1E, Operand.E),  # LD E, d8
    (0x26, Operand.H),  # LD H, d8
    (0x2E, Operand.L),  # LD L, d8
    (0x36, Operand.HL_POINTER),  # LD (HL), d8
    (0x3E, Operand.A),  # LD A, d8
]


@pytest.mark.parametrize(
    "opcode, dst, src",
    LOAD_BLOCK,
    ids=lambda param: f"{param:#04x}" if isinstance(param, int) else param.name,
)
def test_load_block_copies_source_to_destination(
    cpu_running: CpuRunning, opcode: int, dst: Operand, src: Operand
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.hl = 0xC000
    # Destination first, so it holds something the source will have to
    # overwrite: an implementation that read `dst` instead of `src` would
    # otherwise pass.
    write_operand(cpu, dst, 0xFF)
    write_operand(cpu, src, 0x5A)

    cycles = cpu.step()

    assert read_operand(cpu, dst) == 0x5A
    assert cycles == (8 if Operand.HL_POINTER in (dst, src) else 4)
    assert cpu.registers.pc == 0x0101
    assert cpu.registers.f == 0x00  # the load block never touches flags


def test_load_block_covers_every_opcode_except_halt() -> None:
    halt = 0x76
    block = set(range(0x40, 0x80))

    assert OPCODES.keys() & block == block - {halt}


def test_halt_is_not_a_load(cpu_running: CpuRunning) -> None:
    opcode = 0x76
    cpu = cpu_running(opcode)
    with pytest.raises(UnknownOpcodeError, match="unknown opcode 0x76"):
        cpu.step()


def test_load_block_names_read_as_assembly() -> None:
    assert OPCODES[0x41].name == "LD B, C"
    assert OPCODES[0x46].name == "LD B, (HL)"
    assert OPCODES[0x70].name == "LD (HL), B"
    assert OPCODES[0x7F].name == "LD A, A"


@pytest.mark.parametrize(
    "opcode, dst",
    LD_IMMEDIATE,
    ids=[dst.name for _, dst in LD_IMMEDIATE],
)
def test_ld_immediate_stores_the_byte_that_follows_the_opcode(
    cpu_running: CpuRunning, opcode: int, dst: Operand
) -> None:
    cpu = cpu_running(opcode, 0x5A)
    cpu.registers.hl = 0xC001
    write_operand(cpu, dst, 0xFF)  # ensure seed value
    cycles = cpu.step()

    assert cycles == (12 if dst is Operand.HL_POINTER else 8)
    assert read_operand(cpu, dst) == 0x5A
    assert cpu.registers.pc == 0x0102  # two bytes read, one instruction
    assert cpu.registers.f == 0x00


def test_the_byte_after_an_immediate_is_the_next_opcode(
    cpu_running: CpuRunning,
) -> None:
    # if the immediate is not consumed, step two decodes 0x5A as an opcode
    # instead of reaching the second instruction.

    #                 LD B, 0x48  LD C, 0x9A
    cpu = cpu_running(0x06, 0x48, 0x0E, 0x9A)
    write_operand(cpu, Operand.B, 0xFF)  # seed value
    write_operand(cpu, Operand.C, 0xFF)  # seed value
    cpu.step()
    cpu.step()

    assert read_operand(cpu, Operand.B) == 0x48
    assert read_operand(cpu, Operand.C) == 0x9A
    assert cpu.registers.pc == 0x0104


def test_ld_immediate_block_is_present_and_named() -> None:
    assert OPCODES[0x06].name == "LD B, d8"
    assert OPCODES[0x0E].name == "LD C, d8"
    assert OPCODES[0x16].name == "LD D, d8"
    assert OPCODES[0x1E].name == "LD E, d8"
    assert OPCODES[0x26].name == "LD H, d8"
    assert OPCODES[0x2E].name == "LD L, d8"
    assert OPCODES[0x36].name == "LD (HL), d8"
    assert OPCODES[0x3E].name == "LD A, d8"


@pytest.mark.parametrize("opcode, pair", [(0x02, "bc"), (0x12, "de")])
def test_pair_store_writes_a_to_the_address_in_the_pair(
    cpu_running: CpuRunning, opcode: int, pair: str
) -> None:
    cpu = cpu_running(opcode)
    setattr(cpu.registers, pair, 0xC000)  # cpu.registers.bc = 0xC000
    cpu.registers.a = 0xC5

    cycles = cpu.step()

    assert cpu.bus.read(0xC000) == 0xC5
    assert cycles == 8
    assert cpu.registers.a == 0xC5  # remains unchanged
    assert cpu.registers.pc == 0x0101
    assert cpu.registers.f == 0x00


@pytest.mark.parametrize("opcode, pair", [(0x0A, "bc"), (0x1A, "de")])
def test_pair_load_reads_into_a_from_the_address_in_the_pair(
    cpu_running: CpuRunning, opcode: int, pair: str
) -> None:
    cpu = cpu_running(opcode)
    cpu.bus.write(0xC0AB, 0xF2)  # wire the value that will be loaded
    cpu.registers.a = 0xFF  # sanity check
    setattr(cpu.registers, pair, 0xC0AB)  # cpu.registers.[bc|de] = 0xC0AB

    cycles = cpu.step()

    assert cpu.registers.a == 0xF2
    assert cycles == 8
    assert cpu.bus.read(0xC0AB) == 0xF2  # remains unchanged
    assert cpu.registers.pc == 0x0101
    assert cpu.registers.f == 0x00


@pytest.mark.parametrize(
    "opcode, pair", [(0x02, "bc"), (0x12, "de"), (0x0A, "bc"), (0x1A, "de")]
)
def test_pair_indirect_leaves_the_pointer_alone(
    cpu_running: CpuRunning, opcode: int, pair: str
) -> None:
    cpu = cpu_running(opcode)
    setattr(cpu.registers, pair, 0xC0AB)

    cpu.step()

    assert getattr(cpu.registers, pair) == 0xC0AB


PAIR_ADDRESSES = {"bc": 0xC000, "de": 0xD000}
PAIR_BYTES = {"bc": 0xB0, "de": 0xDE}


@pytest.mark.parametrize(
    "opcode, pair, other", [(0x02, "bc", "de"), (0x12, "de", "bc")]
)
def test_a_store_writes_only_through_the_pair_its_mnemonic_names(
    cpu_running: CpuRunning, opcode: int, pair: str, other: str
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.bc = PAIR_ADDRESSES["bc"]
    cpu.registers.de = PAIR_ADDRESSES["de"]
    cpu.registers.a = 0x5A

    cpu.step()

    assert cpu.bus.read(PAIR_ADDRESSES[pair]) == 0x5A
    assert cpu.bus.read(PAIR_ADDRESSES[other]) == 0x00


@pytest.mark.parametrize(
    "opcode, pair, other", [(0x0A, "bc", "de"), (0x1A, "de", "bc")]
)
def test_a_load_reads_only_through_the_pair_its_mnemonic_names(
    cpu_running: CpuRunning, opcode: int, pair: str, other: str
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.bc = PAIR_ADDRESSES["bc"]
    cpu.registers.de = PAIR_ADDRESSES["de"]
    cpu.bus.write(PAIR_ADDRESSES["bc"], PAIR_BYTES["bc"])
    cpu.bus.write(PAIR_ADDRESSES["de"], PAIR_BYTES["de"])
    cpu.registers.a = 0xFF

    cpu.step()

    assert cpu.registers.a == PAIR_BYTES[pair]
    assert cpu.registers.a != PAIR_BYTES[other]


def test_pair_indirect_block_is_present_and_named() -> None:
    assert OPCODES[0x02].name == "LD (BC), A"
    assert OPCODES[0x12].name == "LD (DE), A"
    assert OPCODES[0x0A].name == "LD A, (BC)"
    assert OPCODES[0x1A].name == "LD A, (DE)"


# (opcode, delta) — the pointer moves by delta *after* the access.
HL_MOVE_STORES = [(0x22, 1), (0x32, -1)]
HL_MOVE_LOADS = [(0x2A, 1), (0x3A, -1)]


@pytest.mark.parametrize("opcode, delta", HL_MOVE_STORES)
def test_hl_move_store_writes_a_then_moves_the_pointer(
    cpu_running: CpuRunning, opcode: int, delta: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.hl = 0xC000
    cpu.registers.a = 0x5A

    cycles = cpu.step()

    assert cpu.bus.read(0xC000) == 0x5A
    assert cpu.registers.hl == 0xC000 + delta
    assert cpu.registers.a == 0x5A  # a store copies, it does not move
    assert cycles == 8  # the pointer update never touches the bus
    assert cpu.registers.pc == 0x0101
    assert cpu.registers.f == 0x00


@pytest.mark.parametrize("opcode, delta", HL_MOVE_LOADS)
def test_hl_move_load_reads_into_a_then_moves_the_pointer(
    cpu_running: CpuRunning, opcode: int, delta: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.hl = 0xC000
    cpu.bus.write(0xC000, 0x5A)
    cpu.registers.a = 0xFF

    cycles = cpu.step()

    assert cpu.registers.a == 0x5A
    assert cpu.registers.hl == 0xC000 + delta
    assert cpu.bus.read(0xC000) == 0x5A  # the source is left alone
    assert cycles == 8
    assert cpu.registers.pc == 0x0101
    assert cpu.registers.f == 0x00


@pytest.mark.parametrize("opcode, delta", HL_MOVE_STORES)
def test_hl_move_store_writes_at_the_address_it_started_on(
    cpu_running: CpuRunning, opcode: int, delta: int
) -> None:
    """Post-increment, not pre-increment.

    If the pointer moved before the write, the byte lands on the neighbour and
    0xC000 stays zero. Asserting the neighbour is untouched is the only way to
    tell the two orderings apart.
    """
    cpu = cpu_running(opcode)
    cpu.registers.hl = 0xC000
    cpu.registers.a = 0x5A

    cpu.step()

    assert cpu.bus.read(0xC000) == 0x5A
    assert cpu.bus.read(0xC000 + delta) == 0x00


@pytest.mark.parametrize("opcode, delta", HL_MOVE_LOADS)
def test_hl_move_load_reads_the_address_it_started_on(
    cpu_running: CpuRunning, opcode: int, delta: int
) -> None:
    """The same ordering check, from the read side.

    Both addresses hold a byte, so a pointer that moved too early reads the
    neighbour's value instead of failing against an empty cell.
    """
    cpu = cpu_running(opcode)
    cpu.registers.hl = 0xC000
    cpu.bus.write(0xC000, 0x5A)
    cpu.bus.write(0xC000 + delta, 0xB6)

    cpu.step()

    assert cpu.registers.a == 0x5A


@pytest.mark.parametrize(
    "opcode, start, expected",
    [
        (0x22, 0xFFFF, 0x0000),
        (0x2A, 0xFFFF, 0x0000),
        (0x32, 0x0000, 0xFFFF),
        (0x3A, 0x0000, 0xFFFF),
    ],
)
def test_hl_move_wraps_at_the_edges_of_the_address_space(
    cpu_running: CpuRunning, opcode: int, start: int, expected: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.hl = start

    cpu.step()

    assert cpu.registers.hl == expected


def test_hl_move_block_is_present_and_named() -> None:
    assert OPCODES[0x22].name == "LD (HL+), A"
    assert OPCODES[0x32].name == "LD (HL-), A"
    assert OPCODES[0x2A].name == "LD A, (HL+)"
    assert OPCODES[0x3A].name == "LD A, (HL-)"


def test_ld_a16_a_writes_a_to_the_absolute_address(cpu_running: CpuRunning) -> None:
    # 0x34 then 0x12 is little-endian for 0x1234. Asserting the byte-swapped
    # address is untouched is what catches a fetch that reads them the wrong
    # way round: every other assertion here would still pass.
    cpu = cpu_running(0xEA, 0x34, 0x12)
    cpu.registers.a = 0x5A

    cycles = cpu.step()

    assert cpu.bus.read(0x1234) == 0x5A
    assert cpu.bus.read(0x3412) == 0x00
    assert cpu.registers.a == 0x5A  # a store copies, it does not move
    assert cycles == 16
    assert cpu.registers.pc == 0x0103  # three bytes consumed
    assert cpu.registers.f == 0x00


def test_ld_a_a16_reads_a_from_the_absolute_address(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xFA, 0x34, 0x12)
    cpu.bus.write(0x1234, 0x5A)
    cpu.bus.write(0x3412, 0xB6)  # the byte-swapped address holds something else
    cpu.registers.a = 0xFF

    cycles = cpu.step()

    assert cpu.registers.a == 0x5A
    assert cpu.bus.read(0x1234) == 0x5A  # the source is left alone
    assert cycles == 16
    assert cpu.registers.pc == 0x0103
    assert cpu.registers.f == 0x00


def test_the_two_bytes_after_an_a16_opcode_are_not_decoded(
    cpu_running: CpuRunning,
) -> None:
    """Both immediate bytes are consumed, so step two reaches the real opcode.

    0x12 on its own is a valid instruction (LD (DE), A), so a partially
    consumed address executes silently instead of crashing.
    """
    #                 LD (0x1234), A    LD A, 0x7E
    cpu = cpu_running(0xEA, 0x34, 0x12, 0x3E, 0x7E)
    cpu.registers.a = 0x5A

    cpu.step()
    cpu.step()

    assert cpu.bus.read(0x1234) == 0x5A
    assert cpu.registers.a == 0x7E
    assert cpu.registers.pc == 0x0105


def test_a16_block_is_present_and_named() -> None:
    assert OPCODES[0xEA].name == "LD (a16), A"
    assert OPCODES[0xFA].name == "LD A, (a16)"


# (offset, resulting address). Includes both ends of the page, so an
# implementation that masks or wraps the sum fails at 0xFF.
FF00_PAGE_OFFSETS = [(0x00, 0xFF00), (0x47, 0xFF47), (0xFF, 0xFFFF)]


@pytest.mark.parametrize("offset, address", FF00_PAGE_OFFSETS)
def test_ldh_store_writes_into_the_ff00_page(
    cpu_running: CpuRunning, offset: int, address: int
) -> None:
    cpu = cpu_running(0xE0, offset)
    cpu.registers.a = 0x5A

    cycles = cpu.step()

    assert cpu.bus.read(address) == 0x5A
    assert cpu.bus.read(offset) == 0x00  # the base was added, not ignored
    assert cpu.registers.a == 0x5A
    assert cycles == 12
    assert cpu.registers.pc == 0x0102  # opcode plus one immediate
    assert cpu.registers.f == 0x00


@pytest.mark.parametrize("offset, address", FF00_PAGE_OFFSETS)
def test_ldh_load_reads_from_the_ff00_page(
    cpu_running: CpuRunning, offset: int, address: int
) -> None:
    cpu = cpu_running(0xF0, offset)
    cpu.bus.write(address, 0x5A)
    cpu.bus.write(offset, 0xB6)  # what a missing 0xFF00 base would find instead
    cpu.registers.a = 0xFF

    cycles = cpu.step()

    assert cpu.registers.a == 0x5A
    assert cpu.bus.read(address) == 0x5A
    assert cycles == 12
    assert cpu.registers.pc == 0x0102
    assert cpu.registers.f == 0x00


@pytest.mark.parametrize("offset, address", FF00_PAGE_OFFSETS)
def test_c_offset_store_writes_into_the_ff00_page(
    cpu_running: CpuRunning, offset: int, address: int
) -> None:
    """`LD (C), A` carries no immediate: the offset comes from C.

    The parens here do not mean what they mean in `LD (HL), A` — the address is
    0xFF00 + C, not C.
    """
    cpu = cpu_running(0xE2)
    cpu.registers.c = offset
    cpu.registers.a = 0x5A

    cycles = cpu.step()

    assert cpu.bus.read(address) == 0x5A
    assert cpu.bus.read(offset) == 0x00
    assert cpu.registers.c == offset  # the offset register is not consumed
    assert cycles == 8
    assert cpu.registers.pc == 0x0101  # one byte, no immediate
    assert cpu.registers.f == 0x00


@pytest.mark.parametrize("offset, address", FF00_PAGE_OFFSETS)
def test_c_offset_load_reads_from_the_ff00_page(
    cpu_running: CpuRunning, offset: int, address: int
) -> None:
    cpu = cpu_running(0xF2)
    cpu.registers.c = offset
    cpu.bus.write(address, 0x5A)
    cpu.bus.write(offset, 0xB6)
    cpu.registers.a = 0xFF

    cycles = cpu.step()

    assert cpu.registers.a == 0x5A
    assert cpu.registers.c == offset
    assert cycles == 8
    assert cpu.registers.pc == 0x0101
    assert cpu.registers.f == 0x00


def test_the_byte_after_an_ldh_opcode_is_not_decoded(cpu_running: CpuRunning) -> None:
    """LDH consumes its immediate; LD (C), A has none to consume.

    Run one of each back to back. If LDH left its offset in the stream, step two
    decodes 0x47 (LD B, A) instead of reaching 0xE2.
    """
    #                 LDH (0x47), A  LD (C), A
    cpu = cpu_running(0xE0, 0x47, 0xE2)
    cpu.registers.a = 0x5A
    cpu.registers.c = 0x80

    cpu.step()
    cpu.step()

    assert cpu.bus.read(0xFF47) == 0x5A
    assert cpu.bus.read(0xFF80) == 0x5A
    assert cpu.registers.pc == 0x0103


def test_ff00_page_block_is_present_and_named() -> None:
    assert OPCODES[0xE0].name == "LDH (a8), A"
    assert OPCODES[0xF0].name == "LDH A, (a8)"
    assert OPCODES[0xE2].name == "LD (C), A"
    assert OPCODES[0xF2].name == "LD A, (C)"


#
# --- ALU BLOCK ---
#

# 10 ooo sss: the operation index in bits 5 to 3, the source in bits 2 to 0.
# The destination is always A.
ALU_BLOCK = [
    (opcode, (opcode >> 3) & 0b111, Operand(opcode & 0b111))
    for opcode in range(0x80, 0xC0)
]

# One row per operation index, all against source B, with the carry set. This
# way ADC and SBC are distinguishable from ADD and SUB. Values are computed by
# hand from the flag table.
ALU_OPERATIONS: list[tuple[int, str, int, int]] = [
    # opcode, name, resulting A, resulting F
    (0x80, "ADD", 0x4B, 0x20),  # 0x3C + 0x0F,     nibble carry
    (0x88, "ADC", 0x4C, 0x20),  # 0x3C + 0x0F + 1, nibble carry
    (0x90, "SUB", 0x2D, 0x60),  # 0x3C - 0x0F,     nibble borrow
    (0x98, "SBC", 0x2C, 0x60),  # 0x3C - 0x0F - 1, nibble borrow
    (0xA0, "AND", 0x0C, 0x20),  # AND always sets H
    (0xA8, "XOR", 0x33, 0x00),
    (0xB0, "OR", 0x3F, 0x00),
    (0xB8, "CP", 0x3C, 0x60),  # A unchanged, flags as SUB
]

# A distinct value per source, so the result maps which one was read. H and L
# are seeded before (HL).
ALU_SOURCE_SEEDS: list[tuple[Operand, int]] = [
    (Operand.B, 0x01),
    (Operand.C, 0x02),
    (Operand.D, 0x03),
    (Operand.E, 0x04),
    (Operand.H, 0x05),
    (Operand.L, 0x06),
    (Operand.HL_POINTER, 0x07),
    (Operand.A, 0x10),
]


def test_alu_block_covers_every_opcode() -> None:
    block = set(range(0x80, 0xC0))

    assert OPCODES.keys() & block == block


@pytest.mark.parametrize(
    "opcode, operation, src",
    ALU_BLOCK,
    ids=[f"{opcode:#04x}" for opcode, _, _ in ALU_BLOCK],
)
def test_alu_block_cycle_costs_follow_the_access_rule(
    opcode: int, operation: int, src: Operand
) -> None:
    assert OPCODES[opcode].cycles == count_cycles(src)
    assert OPCODES[opcode].cycles == (8 if src is Operand.HL_POINTER else 4)


@pytest.mark.parametrize(
    "opcode, name, expected_a, expected_f",
    ALU_OPERATIONS,
    ids=[name for _, name, _, _ in ALU_OPERATIONS],
)
def test_alu_applies_the_operation_its_opcode_names(
    cpu_running: CpuRunning, opcode: int, name: str, expected_a: int, expected_f: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.a = 0x3C
    cpu.registers.b = 0x0F
    cpu.registers.c_flag = True

    cycles = cpu.step()

    assert OPCODES[opcode].name == f"{name} A, B"
    assert cpu.registers.a == expected_a
    assert cpu.registers.f == expected_f
    assert cycles == 4
    assert cpu.registers.b == 0x0F  # source != destination
    assert cpu.registers.pc == 0x0101


@pytest.mark.parametrize(
    "src, seed",
    ALU_SOURCE_SEEDS,
    ids=[src.name for src, _ in ALU_SOURCE_SEEDS],
)
def test_alu_reads_the_source_its_opcode_names(
    cpu_running: CpuRunning, src: Operand, seed: int
) -> None:
    cpu = cpu_running(0x80 + src)  # ADD A, src
    for operand, value in ALU_SOURCE_SEEDS:
        write_operand(cpu, operand, value)

    cpu.step()

    assert cpu.registers.a == (0x20 if src is Operand.A else 0x10 + seed)


def test_cp_sets_flags_without_touching_the_accumulator(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xB8)  # CP A, B
    cpu.registers.a = 0x0F
    cpu.registers.b = 0x01

    cpu.step()

    assert cpu.registers.a == 0x0F
    assert cpu.registers.f == 0x40  # N alone: no borrow at boundaries


def test_cp_reports_equality_through_the_zero_flag(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xB8)  # CP A, B
    cpu.registers.a = 0x42
    cpu.registers.b = 0x42

    cpu.step()

    assert cpu.registers.a == 0x42
    assert cpu.registers.f == 0xC0  # Z and N


@pytest.mark.parametrize(
    "opcode, without_carry, with_carry",
    [
        (0x88, 0x4B, 0x4C),  # ADC A, B
        (0x98, 0x2D, 0x2C),  # SBC A, B
    ],
    ids=["ADC", "SBC"],
)
def test_adc_and_sbc_read_the_carry_flag(
    cpu_running: CpuRunning, opcode: int, without_carry: int, with_carry: int
) -> None:
    # The carry has to reach the ALU from the register file.
    for carry, expected in ((False, without_carry), (True, with_carry)):
        cpu = cpu_running(opcode)
        cpu.registers.a = 0x3C
        cpu.registers.b = 0x0F
        cpu.registers.c_flag = carry

        cpu.step()

        assert cpu.registers.a == expected


def test_alu_block_names_read_as_assembly() -> None:
    assert OPCODES[0x80].name == "ADD A, B"
    assert OPCODES[0x86].name == "ADD A, (HL)"
    assert OPCODES[0x90].name == "SUB A, B"
    assert OPCODES[0xA8].name == "XOR A, B"
    assert OPCODES[0xB0].name == "OR A, B"
    assert OPCODES[0xBF].name == "CP A, A"


# The immediate ALU block, 0xC6 to 0xFE on the `11 ooo 110` pattern.
# ALU_OPERATIONS is reused and translated to the immediate opcode, following
# this pattern:
# register, source B:  10 ooo 000
# immediate:           11 ooo 110
#                       ^      ^
#                       |      +-- source field: 000 -> 110   = +0x06
#                       +--------- block bit:     10 ->  11   = +0x40


@pytest.mark.parametrize(
    "opcode, name, expected_a, expected_f",
    ALU_OPERATIONS,
    ids=[name for _, name, _, _ in ALU_OPERATIONS],
)
def test_alu_immediate_applies_the_operation_its_opcode_names(
    cpu_running: CpuRunning, opcode: int, name: str, expected_a: int, expected_f: int
) -> None:
    imm_opcode = opcode + 0x46  # see chart above
    value = 0x0F
    cpu = cpu_running(imm_opcode, value)

    cpu.registers.a = 0x3C
    cpu.registers.c_flag = True

    cycles = cpu.step()

    assert OPCODES[imm_opcode].name == f"{name} A, d8"
    assert cpu.registers.a == expected_a
    assert cpu.registers.f == expected_f
    assert cycles == 8
    assert cpu.registers.pc == 0x0102


def test_the_byte_after_an_alu_immediate_is_the_next_opcode(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xC6, 0x01, 0xC6, 0x02)

    write_operand(cpu, Operand.A, 0xF0)  # seed value

    cpu.step()

    assert read_operand(cpu, Operand.A) == 0xF1

    cpu.step()

    assert read_operand(cpu, Operand.A) == 0xF3
    assert cpu.registers.pc == 0x0104


def test_cp_immediate_leaves_the_accumulator_alone(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xFE, 0x01)
    write_operand(cpu, Operand.A, 0xF0)  # seed value

    cpu.step()

    assert read_operand(cpu, Operand.A) == 0xF0
    # Flags still have to move, or a CP that did nothing at all would pass:
    # N and H, borrowing out of the low nibble but not out of the byte.
    assert cpu.registers.f == 0x60


def test_alu_immediate_block_names_read_as_assembly() -> None:
    assert OPCODES[0xC6].name == "ADD A, d8"
    assert OPCODES[0xCE].name == "ADC A, d8"
    assert OPCODES[0xD6].name == "SUB A, d8"
    assert OPCODES[0xDE].name == "SBC A, d8"
    assert OPCODES[0xE6].name == "AND A, d8"
    assert OPCODES[0xEE].name == "XOR A, d8"
    assert OPCODES[0xF6].name == "OR A, d8"
    assert OPCODES[0xFE].name == "CP A, d8"


#
# --- INC / DEC r ---
#


def test_inc_dec_block_covers_every_opcode() -> None:
    inc_block = set(range(0x04, 0x40, 8))
    dec_block = set(range(0x05, 0x40, 8))

    assert OPCODES.keys() & inc_block == inc_block
    assert OPCODES.keys() & dec_block == dec_block


def test_inc_dec_block_names_read_as_assembly() -> None:
    assert OPCODES[0x04].name == "INC B"
    assert OPCODES[0x05].name == "DEC B"
    assert OPCODES[0x14].name == "INC D"
    assert OPCODES[0x15].name == "DEC D"


# Every opcode in the block, with the operation and the operand it decodes to.
INC_DEC_BLOCK: list[tuple[int, str, Operand]] = [
    (opcode, name, Operand((opcode >> 3) & 0b111))
    for name, base in (("INC", 0x04), ("DEC", 0x05))
    for opcode in range(base, 0x40, 8)
]

INC_DEC_BOUNDARIES: list[tuple[int, int, int, int]] = [
    # opcode, starting value, result, resulting F
    (0x04, 0x00, 0x01, 0x00),  # INC, nothing interesting
    (0x04, 0x0F, 0x10, 0x20),  # INC, low nibble overflowed -> H
    (0x04, 0xFF, 0x00, 0xA0),  # INC, wrapped -> Z and H
    (0x05, 0x01, 0x00, 0xC0),  # DEC, landed on zero -> Z and N
    (0x05, 0x10, 0x0F, 0x60),  # DEC, low nibble borrowed -> N and H
    (0x05, 0x00, 0xFF, 0x60),  # DEC, wrapped -> N and H
]


@pytest.mark.parametrize(
    "opcode, name, operand",
    INC_DEC_BLOCK,
    ids=[f"{name} {operand.assembly_name}" for _, name, operand in INC_DEC_BLOCK],
)
def test_inc_dec_cycle_costs_follow_the_access_rule(
    cpu_running: CpuRunning, opcode: int, name: str, operand: Operand
) -> None:
    cpu = cpu_running(opcode)

    assert cpu.step() == (12 if operand is Operand.HL_POINTER else 4)
    assert OPCODES[opcode].name == f"{name} {operand.assembly_name}"


@pytest.mark.parametrize(
    "opcode, start, expected, expected_f",
    INC_DEC_BOUNDARIES,
    ids=[f"{op:#04x}-{start:#04x}" for op, start, _, _ in INC_DEC_BOUNDARIES],
)
def test_inc_and_dec_flag_boundaries(
    cpu_running: CpuRunning, opcode: int, start: int, expected: int, expected_f: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.b = start

    cpu.step()

    assert cpu.registers.b == expected
    assert cpu.registers.f == expected_f


@pytest.mark.parametrize(
    "opcode, start, carry_in, expected_f",
    [
        (0x04, 0x0F, True, 0x30),  # INC: H set by the nibble, C carried in
        (0x04, 0x0F, False, 0x20),  # ... and still clear when it started clear
        (0x05, 0x10, True, 0x70),  # DEC: N and H, C carried in
        (0x05, 0x10, False, 0x60),
    ],
    ids=["INC-carry-set", "INC-carry-clear", "DEC-carry-set", "DEC-carry-clear"],
)
def test_inc_and_dec_leave_the_carry_flag_alone(
    cpu_running: CpuRunning, opcode: int, start: int, carry_in: bool, expected_f: int
) -> None:
    # Checks the `None` branch of Registers.apply: alu.inc and alu.dec never
    # name `c`, so it defaults to None and apply() skips it.

    cpu = cpu_running(opcode)
    cpu.registers.b = start
    cpu.registers.c_flag = carry_in

    cpu.step()

    assert cpu.registers.c_flag is carry_in
    assert cpu.registers.f == expected_f


@pytest.mark.parametrize(
    "opcode, start, expected",
    [(0x34, 0x41, 0x42), (0x35, 0x41, 0x40)],
    ids=["INC (HL)", "DEC (HL)"],
)
def test_inc_dec_hl_read_and_write_through_the_bus(
    cpu_running: CpuRunning, opcode: int, start: int, expected: int
) -> None:
    address = 0xC000
    cpu = cpu_running(opcode)
    cpu.registers.hl = address
    cpu.bus.write(address, start)

    cycles = cpu.step()

    assert cpu.bus.read(address) == expected
    # INC (HL) is not INC HL:
    assert cpu.registers.hl == address
    assert cycles == 12


# --- 16-BIT LOADS AND ARITHMETIC ---
#

PAIRS: list[tuple[int, RegisterPair]] = [
    (0x00, RegisterPair.BC),
    (0x10, RegisterPair.DE),
    (0x20, RegisterPair.HL),
    (0x30, RegisterPair.SP),
]

# base opcode, mnemonic template, cycles
PAIR_FAMILIES: list[tuple[int, str, int]] = [
    (0x01, "LD {}, d16", 12),
    (0x03, "INC {}", 8),
    (0x0B, "DEC {}", 8),
    (0x09, "ADD HL, {}", 8),
]


@pytest.mark.parametrize("offset, pair", PAIRS, ids=[p.name for _, p in PAIRS])
def test_pair_accessors_round_trip(
    cpu_running: CpuRunning, offset: int, pair: RegisterPair
) -> None:
    cpu = cpu_running(0x00)
    write_pair(cpu, pair, 0xBEEF)

    assert read_pair(cpu, pair) == 0xBEEF
    assert getattr(cpu.registers, pair.name.lower()) == 0xBEEF


@pytest.mark.parametrize(
    "base, template, cycles",
    PAIR_FAMILIES,
    ids=[template.format("rr") for _, template, _ in PAIR_FAMILIES],
)
def test_pair_family_covers_its_four_opcodes(
    base: int, template: str, cycles: int
) -> None:
    # Per family, not one set of sixteen: the failure mode these loops invite is
    # one family overwriting another, and a combined set would not see it.
    family = {base + offset for offset, _ in PAIRS}

    assert OPCODES.keys() & family == family


@pytest.mark.parametrize(
    "base, template, cycles",
    PAIR_FAMILIES,
    ids=[template.format("rr") for _, template, _ in PAIR_FAMILIES],
)
def test_pair_family_names_and_cycles(base: int, template: str, cycles: int) -> None:
    for offset, pair in PAIRS:
        instruction = OPCODES[base + offset]

        assert instruction.name == template.format(pair.name)
        assert instruction.cycles == cycles


@pytest.mark.parametrize(
    "opcode, pair",
    [(0x01 + offset, pair) for offset, pair in PAIRS],
    ids=[pair.name for _, pair in PAIRS],
)
def test_ld_pair_immediate_is_little_endian(
    cpu_running: CpuRunning, opcode: int, pair: RegisterPair
) -> None:
    cpu = cpu_running(opcode, 0x34, 0x12)

    cycles = cpu.step()

    assert read_pair(cpu, pair) == 0x1234
    assert cycles == 12
    assert cpu.registers.pc == 0x0103  # opcode plus two immediate bytes
    assert cpu.registers.f == 0x00  # no flags touched


@pytest.mark.parametrize(
    "opcode, pair, start, expected",
    # Mid-range first. The wrap cases alone cannot tell a 16-bit increment from
    # an 8-bit one, because 0xFFFF + 1 and 0x00 + 1 both land on zero.
    [(0x03 + offset, pair, 0x1234, 0x1235) for offset, pair in PAIRS]
    + [(0x03 + offset, pair, 0xFFFF, 0x0000) for offset, pair in PAIRS]
    + [(0x0B + offset, pair, 0x1234, 0x1233) for offset, pair in PAIRS]
    + [(0x0B + offset, pair, 0x0000, 0xFFFF) for offset, pair in PAIRS],
    ids=[f"INC {p.name} mid" for _, p in PAIRS]
    + [f"INC {p.name} wrap" for _, p in PAIRS]
    + [f"DEC {p.name} mid" for _, p in PAIRS]
    + [f"DEC {p.name} wrap" for _, p in PAIRS],
)
def test_inc_dec_pair_wrap_and_touch_no_flags(
    cpu_running: CpuRunning,
    opcode: int,
    pair: RegisterPair,
    start: int,
    expected: int,
) -> None:
    # Unlike INC r, these write no flags
    cpu = cpu_running(opcode)
    write_pair(cpu, pair, start)
    cpu.registers.f = 0xF0

    cycles = cpu.step()

    assert read_pair(cpu, pair) == expected
    assert cpu.registers.f == 0xF0
    assert cycles == 8


@pytest.mark.parametrize(
    "opcode, pair, hl, operand, expected, expected_f",
    [
        # 0xA23 + 0x605 = 0x1028, so the carry crosses bit 11 but not bit 15.
        # Z starts and ends set
        (0x09, RegisterPair.BC, 0x8A23, 0x0605, 0x9028, 0xA0),
        # Exactly the bit-11 boundary, Z starts clear
        (0x19, RegisterPair.DE, 0x0FFF, 0x0001, 0x1000, 0x20),
        # Carry out of bit 15 with no half-carry
        (0x39, RegisterPair.SP, 0x8000, 0x8000, 0x0000, 0x10),
    ],
    ids=["ADD HL, BC", "ADD HL, DE", "ADD HL, SP"],
)
def test_add_hl_writes_its_flags_and_keeps_zero(
    cpu_running: CpuRunning,
    opcode: int,
    pair: RegisterPair,
    hl: int,
    operand: int,
    expected: int,
    expected_f: int,
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.hl = hl
    write_pair(cpu, pair, operand)
    cpu.registers.z_flag = bool(expected_f & 0x80)

    cycles = cpu.step()

    assert cpu.registers.hl == expected
    assert cpu.registers.f == expected_f
    assert cycles == 8


def test_add_hl_hl_doubles_the_pointer(cpu_running: CpuRunning) -> None:
    # 0x29 is ADD HL, HL: the pair can be HL itself, so the same register is
    # both operands and the destination.
    cpu = cpu_running(0x29)
    cpu.registers.hl = 0x1234

    cpu.step()

    assert cpu.registers.hl == 0x2468


def test_ld_a16_sp_writes_the_low_byte_first(cpu_running: CpuRunning) -> None:
    address = 0xC000
    cpu = cpu_running(0x08, 0x00, 0xC0)  # LD (0xC000), SP
    cpu.registers.sp = 0xFFFE

    cycles = cpu.step()

    assert cpu.bus.read(address) == 0xFE  # low byte at the address
    assert cpu.bus.read(address + 1) == 0xFF  # high byte after it
    assert cpu.bus.read16(address) == 0xFFFE
    assert cycles == 20
    assert cpu.registers.pc == 0x0103
    assert cpu.registers.f == 0x00


#
# --- DAA, CPL, SCF, CCF ---
#

# Four opcodes sharing no bit pattern, so all four are written by hand. Each
# costs 4 cycles: one fetch, no operand, no bus access.
FLAG_OPS: list[tuple[int, str]] = [
    (0x27, "DAA"),
    (0x2F, "CPL"),
    (0x37, "SCF"),
    (0x3F, "CCF"),
]


@pytest.mark.parametrize("opcode, name", FLAG_OPS, ids=[n for _, n in FLAG_OPS])
def test_flag_ops_are_present_named_and_cost_four(opcode: int, name: str) -> None:
    assert OPCODES[opcode].name == name
    assert OPCODES[opcode].cycles == 4


@pytest.mark.parametrize(
    "start_f, expected_f",
    [
        # Z and C are carried through untouched; N and H are always set.
        (0x00, 0x60),
        (0x90, 0xF0),  # Z and C set going in, still set coming out
    ],
    ids=["flags-clear", "z-and-c-set"],
)
def test_cpl_flips_every_bit(
    cpu_running: CpuRunning, start_f: int, expected_f: int
) -> None:
    cpu = cpu_running(0x2F)
    cpu.registers.a = 0x35
    cpu.registers.f = start_f

    cycles = cpu.step()

    assert cpu.registers.a == 0xCA  # 0b0011_0101 -> 0b1100_1010
    assert cpu.registers.f == expected_f
    assert cycles == 4


def test_cpl_twice_restores_the_accumulator(cpu_running: CpuRunning) -> None:
    # One's complement is its own inverse. A test that only checked a single
    # flip would also pass against `a ^ 0x0F` or a stray mask.
    cpu = cpu_running(0x2F, 0x2F)
    cpu.registers.a = 0x35

    cpu.step()
    cpu.step()

    assert cpu.registers.a == 0x35


@pytest.mark.parametrize(
    "start_f, expected_f",
    [
        (0x00, 0x10),  # C set, Z stays clear
        (0xF0, 0x90),  # N and H cleared, Z and C survive as set
    ],
    ids=["flags-clear", "flags-set"],
)
def test_scf_sets_the_carry_and_clears_n_and_h(
    cpu_running: CpuRunning, start_f: int, expected_f: int
) -> None:
    cpu = cpu_running(0x37)
    cpu.registers.f = start_f

    cycles = cpu.step()

    assert cpu.registers.f == expected_f
    assert cycles == 4


@pytest.mark.parametrize(
    "start_f, expected_f",
    [
        (0x00, 0x10),  # carry was clear, now set
        (0xF0, 0x80),  # carry was set, now clear; N and H cleared, Z survives
    ],
    ids=["carry-clear", "carry-set"],
)
def test_ccf_flips_the_carry_and_clears_n_and_h(
    cpu_running: CpuRunning, start_f: int, expected_f: int
) -> None:
    cpu = cpu_running(0x3F)
    cpu.registers.f = start_f

    cycles = cpu.step()

    assert cpu.registers.f == expected_f
    assert cycles == 4


@pytest.mark.parametrize("carry", [False, True], ids=["from-clear", "from-set"])
def test_ccf_twice_restores_the_carry(cpu_running: CpuRunning, carry: bool) -> None:
    # A property rather than a case: this cannot pass against an implementation
    # that sets the carry instead of complementing it.
    cpu = cpu_running(0x3F, 0x3F)
    cpu.registers.c_flag = carry

    cpu.step()
    cpu.step()

    assert cpu.registers.c_flag is carry


# alu.daa already has twenty thousand cases, so these are end-to-end instead:
# a small program per row, proving the whole chain works -- immediate load,
# ALU block, flags reaching the registers, and DAA reading them back out.
DAA_PROGRAMS: list[tuple[tuple[int, ...], int, int, str]] = [
    # program bytes, resulting A, resulting F, what it computes
    ((0x3E, 0x37, 0xC6, 0x05, 0x27), 0x42, 0x00, "37 + 5 = 42"),
    ((0x3E, 0x91, 0xC6, 0x11, 0x27), 0x02, 0x10, "91 + 11 = 102, carry out"),
    ((0x3E, 0x50, 0xC6, 0x50, 0x27), 0x00, 0x90, "50 + 50 = 100, Z and carry"),
    ((0x3E, 0x32, 0xD6, 0x05, 0x27), 0x27, 0x40, "32 - 5 = 27, N kept"),
]


@pytest.mark.parametrize(
    "program, expected_a, expected_f, note",
    DAA_PROGRAMS,
    ids=[note for *_, note in DAA_PROGRAMS],
)
def test_daa_corrects_a_bcd_program(
    cpu_running: CpuRunning,
    program: tuple[int, ...],
    expected_a: int,
    expected_f: int,
    note: str,
) -> None:
    cpu = cpu_running(*program)

    for _ in range(3):  # LD A, d8 ; ADD or SUB A, d8 ; DAA
        cpu.step()

    assert cpu.registers.a == expected_a
    assert cpu.registers.f == expected_f
    assert cpu.registers.pc == 0x0105  # 2 + 2 + 1 bytes


# --- JR ---


def test_jr_jumps_forward_relative_to_the_next_instruction(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0x18, 0x05)

    assert cpu.step() == 12
    # After both bytes are fetched PC is 0x0102, and the offset counts from
    # there: 0x0102 + 5.
    assert cpu.registers.pc == 0x0107


def test_jr_jumps_backward_on_a_negative_offset(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0x18, 0xFC, at=0x0216)

    assert cpu.step() == 12
    # 0xFC is -4 as a signed byte. PC is 0x0218 after the fetch, so 0x0214.
    assert cpu.registers.pc == 0x0214


@pytest.mark.parametrize(
    ("opcode", "z", "c", "expected_pc", "expected_cycles"),
    [
        (0x20, False, False, 0x0107, 12),  # JR NZ, Z clear -> taken
        (0x20, True, False, 0x0102, 8),  # JR NZ, Z set     -> not taken
        (0x28, True, False, 0x0107, 12),  # JR Z,  Z set    -> taken
        (0x28, False, False, 0x0102, 8),  # JR Z,  Z clear  -> not taken
        (0x30, False, False, 0x0107, 12),  # JR NC, C clear -> taken
        (0x30, False, True, 0x0102, 8),  # JR NC, C set     -> not taken
        (0x38, False, True, 0x0107, 12),  # JR C,  C set    -> taken
        (0x38, False, False, 0x0102, 8),  # JR C,  C clear  -> not taken
    ],
    ids=[
        "NZ-taken",
        "NZ-skipped",
        "Z-taken",
        "Z-skipped",
        "NC-taken",
        "NC-skipped",
        "C-taken",
        "C-skipped",
    ],
)
def test_conditional_jr_branches_only_when_its_condition_holds(
    cpu_running: CpuRunning,
    opcode: int,
    z: bool,
    c: bool,
    expected_pc: int,
    expected_cycles: int,
) -> None:
    cpu = cpu_running(opcode, 0x05)
    cpu.registers.z_flag = z
    cpu.registers.c_flag = c

    assert cpu.step() == expected_cycles
    assert cpu.registers.pc == expected_pc


def test_jr_does_not_touch_the_flags(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0x18, 0x05)
    cpu.registers.z_flag = True
    cpu.registers.c_flag = True
    cpu.registers.n_flag = True
    cpu.registers.h_flag = True

    cpu.step()

    assert cpu.registers.f == 0xF0


def test_jr_nz_runs_a_loop_to_completion(cpu_running: CpuRunning) -> None:
    # 0100  06 03   LD B, 3
    # 0102  05      DEC B
    # 0103  20 FD   JR NZ, -3   -> back to 0102 while B is not zero
    # 0105  00      NOP
    cpu = cpu_running(0x06, 0x03, 0x05, 0x20, 0xFD, 0x00)

    for _ in range(7):
        cpu.step()

    assert cpu.registers.b == 0x00
    assert cpu.registers.pc == 0x0105


@pytest.mark.parametrize(
    ("opcode", "name"),
    [
        (0x18, "JR e8"),
        (0x20, "JR NZ, e8"),
        (0x28, "JR Z, e8"),
        (0x30, "JR NC, e8"),
        (0x38, "JR C, e8"),
    ],
)
def test_the_jr_table_entries_are_named_and_costed(opcode: int, name: str) -> None:
    instruction = OPCODES[opcode]

    assert instruction.name == name
    if opcode == 0x18:
        assert instruction.cycles == 12
        assert instruction.cycles_when_taken is None
    else:
        assert instruction.cycles == 8
        assert instruction.cycles_when_taken == 12


@pytest.mark.parametrize(
    ("opcode", "z", "c"),
    [
        (0x18, False, False),  # JR e8,     always taken
        (0x20, False, False),  # JR NZ, e8, Z clear -> taken
        (0x28, True, False),  # JR Z, e8,  Z set    -> taken
        (0x30, False, False),  # JR NC, e8, C clear -> taken
        (0x38, False, True),  # JR C, e8,  C set    -> taken
    ],
    ids=["JR", "JR NZ", "JR Z", "JR NC", "JR C"],
)
def test_a_taken_jr_wraps_pc_at_the_bottom_of_memory(
    cpu_running: CpuRunning, opcode: int, z: bool, c: bool
) -> None:
    cpu = cpu_running(opcode, 0xFC, at=0x0000)
    cpu.registers.z_flag = z
    cpu.registers.c_flag = c

    cpu.step()

    assert cpu.registers.pc == 0xFFFE


# --- JP cc ---


@pytest.mark.parametrize(
    ("opcode", "z", "c", "expected_pc", "expected_cycles"),
    [
        (0xC2, False, False, 0x0150, 16),  # JP NZ, Z clear -> taken
        (0xC2, True, False, 0x0103, 12),  # JP NZ, Z set    -> not taken
        (0xCA, True, False, 0x0150, 16),  # JP Z,  Z set    -> taken
        (0xCA, False, False, 0x0103, 12),  # JP Z,  Z clear -> not taken
        (0xD2, False, False, 0x0150, 16),  # JP NC, C clear -> taken
        (0xD2, False, True, 0x0103, 12),  # JP NC, C set    -> not taken
        (0xDA, False, True, 0x0150, 16),  # JP C,  C set    -> taken
        (0xDA, False, False, 0x0103, 12),  # JP C,  C clear -> not taken
    ],
    ids=[
        "NZ-taken",
        "NZ-skipped",
        "Z-taken",
        "Z-skipped",
        "NC-taken",
        "NC-skipped",
        "C-taken",
        "C-skipped",
    ],
)
def test_conditional_jp_branches_only_when_its_condition_holds(
    cpu_running: CpuRunning,
    opcode: int,
    z: bool,
    c: bool,
    expected_pc: int,
    expected_cycles: int,
) -> None:
    cpu = cpu_running(opcode, 0x50, 0x01)
    cpu.registers.z_flag = z
    cpu.registers.c_flag = c

    assert cpu.step() == expected_cycles
    assert cpu.registers.pc == expected_pc


@pytest.mark.parametrize(
    ("opcode", "name"),
    [
        (0xC3, "JP a16"),
        (0xC2, "JP NZ, a16"),
        (0xCA, "JP Z, a16"),
        (0xD2, "JP NC, a16"),
        (0xDA, "JP C, a16"),
    ],
)
def test_the_jp_table_entries_are_named_and_costed(opcode: int, name: str) -> None:
    instruction = OPCODES[opcode]

    assert instruction.name == name
    if opcode == 0xC3:
        assert instruction.cycles == 16
        assert instruction.cycles_when_taken is None
    else:
        assert instruction.cycles == 12
        assert instruction.cycles_when_taken == 16


# --- JP HL ---


def test_jp_hl_jumps_to_the_value_of_hl_without_reading_memory(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xE9)
    cpu.registers.hl = 0x4000
    cpu.bus.write(0x4000, 0x99)

    assert cpu.step() == 4
    assert cpu.registers.pc == 0x4000


def test_the_jp_hl_table_entry_is_named_and_costed() -> None:
    instruction = OPCODES[0xE9]

    assert instruction.name == "JP HL"
    assert instruction.cycles == 4
    # Unconditional: there is no taken/not-taken pair to declare.
    assert instruction.cycles_when_taken is None


# --- CALL ---


def test_call_pushes_the_return_address_and_jumps(cpu_running: CpuRunning) -> None:
    # 0100  CD 10 01   CALL 0x0110
    # 0103             <- the return address, the instruction after the CALL
    cpu = cpu_running(0xCD, 0x10, 0x01)
    cpu.registers.sp = 0xFFFE

    assert cpu.step() == 24
    assert cpu.registers.pc == 0x0110
    assert cpu.registers.sp == 0xFFFC
    # This is the assertion that pins *which* address:
    # 0x0103, not 0x0100 (the CALL itself) and not 0x0102 (one byte less)
    assert cpu.bus.read16(0xFFFC) == 0x0103


def test_nested_calls_stack_their_return_addresses(cpu_running: CpuRunning) -> None:
    # 0100  CD 10 01   CALL 0x0110
    # 0110  CD 20 01   CALL 0x0120
    cpu = cpu_running(0xCD, 0x10, 0x01)
    cpu.registers.sp = 0xFFFE
    for offset, byte in enumerate((0xCD, 0x20, 0x01)):
        cpu.bus.write(0x0110 + offset, byte)

    cpu.step()
    cpu.step()

    assert cpu.registers.pc == 0x0120
    assert cpu.registers.sp == 0xFFFA
    assert cpu.bus.read16(0xFFFA) == 0x0113
    assert cpu.bus.read16(0xFFFC) == 0x0103


def test_call_does_not_touch_the_flags(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xCD, 0x10, 0x01)
    cpu.registers.sp = 0xFFFE
    cpu.registers.f = 0xF0

    cpu.step()

    assert cpu.registers.f == 0xF0


def test_the_call_table_entry_is_named_and_costed() -> None:
    instruction = OPCODES[0xCD]

    assert instruction.name == "CALL a16"
    assert instruction.cycles == 24
    assert instruction.cycles_when_taken is None


# --- CALL cc ---


@pytest.mark.parametrize(
    ("opcode", "z", "c", "taken"),
    [
        (0xC4, False, False, True),  # CALL NZ, Z clear  -> taken
        (0xC4, True, False, False),  # CALL NZ, Z set    -> not taken
        (0xCC, True, False, True),  # CALL Z,  Z set     -> taken
        (0xCC, False, False, False),  # CALL Z,  Z clear -> not taken
        (0xD4, False, False, True),  # CALL NC, C clear  -> taken
        (0xD4, False, True, False),  # CALL NC, C set    -> not taken
        (0xDC, False, True, True),  # CALL C,  C set     -> taken
        (0xDC, False, False, False),  # CALL C,  C clear -> not taken
    ],
    ids=[
        "NZ-taken",
        "NZ-skipped",
        "Z-taken",
        "Z-skipped",
        "NC-taken",
        "NC-skipped",
        "C-taken",
        "C-skipped",
    ],
)
def test_conditional_call_pushes_and_jumps_only_when_taken(
    cpu_running: CpuRunning, opcode: int, z: bool, c: bool, taken: bool
) -> None:
    cpu = cpu_running(opcode, 0x10, 0x01)
    cpu.registers.sp = 0xFFFE
    cpu.registers.z_flag = z
    cpu.registers.c_flag = c

    cycles = cpu.step()

    if taken:
        assert cycles == 24
        assert cpu.registers.pc == 0x0110
        assert cpu.registers.sp == 0xFFFC
        assert cpu.bus.read16(0xFFFC) == 0x0103
    else:
        assert cycles == 12
        assert cpu.registers.pc == 0x0103
        assert cpu.registers.sp == 0xFFFE


@pytest.mark.parametrize(
    ("opcode", "name"),
    [
        (0xC4, "CALL NZ, a16"),
        (0xCC, "CALL Z, a16"),
        (0xD4, "CALL NC, a16"),
        (0xDC, "CALL C, a16"),
    ],
)
def test_the_conditional_call_table_entries_are_named_and_costed(
    opcode: int, name: str
) -> None:
    instruction = OPCODES[opcode]

    assert instruction.name == name
    assert instruction.cycles == 12
    assert instruction.cycles_when_taken == 24


# --- RET ---


def test_ret_pops_the_return_address_into_pc(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xC9)
    cpu.registers.sp = 0xFFFC
    # Seeded a byte at a time rather than with write16, so this test states
    # the little-endian claim RET depends on.
    cpu.bus.write(0xFFFC, 0x50)
    cpu.bus.write(0xFFFD, 0x01)

    assert cpu.step() == 16
    assert cpu.registers.pc == 0x0150
    assert cpu.registers.sp == 0xFFFE


def test_call_and_ret_leave_sp_where_they_found_it(cpu_running: CpuRunning) -> None:
    # 0100  CD 10 01   CALL 0x0110
    # 0110  C9         RET
    cpu = cpu_running(0xCD, 0x10, 0x01)
    cpu.bus.write(0x0110, 0xC9)
    cpu.registers.sp = 0xFFFE

    cpu.step()
    cpu.step()

    assert cpu.registers.pc == 0x0103
    # The assertion worth making after every program test from here on: a
    # balanced program ends with SP exactly where it started.
    assert cpu.registers.sp == 0xFFFE


def test_two_levels_of_call_and_ret_unwind_in_order(cpu_running: CpuRunning) -> None:
    # 0100  CD 10 01   CALL 0x0110
    # 0110  CD 20 01   CALL 0x0120
    # 0113  C9         RET          -> back to 0103
    # 0120  C9         RET          -> back to 0113
    cpu = cpu_running(0xCD, 0x10, 0x01)
    for address, byte in (
        (0x0110, 0xCD),
        (0x0111, 0x20),
        (0x0112, 0x01),
        (0x0113, 0xC9),
        (0x0120, 0xC9),
    ):
        cpu.bus.write(address, byte)
    cpu.registers.sp = 0xFFFE

    for _ in range(4):
        cpu.step()

    assert cpu.registers.pc == 0x0103
    assert cpu.registers.sp == 0xFFFE


@pytest.mark.parametrize(
    ("opcode", "z", "c", "taken"),
    [
        (0xC0, False, False, True),  # RET NZ, Z clear  -> taken
        (0xC0, True, False, False),  # RET NZ, Z set    -> not taken
        (0xC8, True, False, True),  # RET Z,  Z set     -> taken
        (0xC8, False, False, False),  # RET Z,  Z clear -> not taken
        (0xD0, False, False, True),  # RET NC, C clear  -> taken
        (0xD0, False, True, False),  # RET NC, C set    -> not taken
        (0xD8, False, True, True),  # RET C,  C set     -> taken
        (0xD8, False, False, False),  # RET C,  C clear -> not taken
    ],
    ids=[
        "NZ-taken",
        "NZ-skipped",
        "Z-taken",
        "Z-skipped",
        "NC-taken",
        "NC-skipped",
        "C-taken",
        "C-skipped",
    ],
)
def test_conditional_ret_pops_only_when_taken(
    cpu_running: CpuRunning, opcode: int, z: bool, c: bool, taken: bool
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.sp = 0xFFFC
    cpu.bus.write16(0xFFFC, 0x0150)
    cpu.registers.z_flag = z
    cpu.registers.c_flag = c

    cycles = cpu.step()

    if taken:
        assert cycles == 20
        assert cpu.registers.pc == 0x0150
        assert cpu.registers.sp == 0xFFFE
    else:
        assert cycles == 8
        assert cpu.registers.pc == 0x0101
        assert cpu.registers.sp == 0xFFFC


@pytest.mark.parametrize(
    ("opcode", "name"),
    [
        (0xC0, "RET NZ"),
        (0xC8, "RET Z"),
        (0xD0, "RET NC"),
        (0xD8, "RET C"),
    ],
)
def test_the_ret_table_entries_are_named_and_costed(opcode: int, name: str) -> None:
    instruction = OPCODES[opcode]

    assert instruction.name == name
    assert instruction.cycles == 8
    assert instruction.cycles_when_taken == 20


def test_the_unconditional_ret_table_entry_is_named_and_costed() -> None:
    instruction = OPCODES[0xC9]

    assert instruction.name == "RET"
    assert instruction.cycles == 16
    assert instruction.cycles_when_taken is None


# --- PUSH / POP ---


@pytest.mark.parametrize(
    ("opcode", "pair", "value"),
    [
        (0xC5, "bc", 0x1234),
        (0xD5, "de", 0x1234),
        (0xE5, "hl", 0x1234),
        (0xF5, "af", 0x1230),  # F has no low nibble
    ],
    ids=["BC", "DE", "HL", "AF"],
)
def test_push_writes_the_pair_below_sp(
    cpu_running: CpuRunning, opcode: int, pair: str, value: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.sp = 0xFFFE
    setattr(cpu.registers, pair, value)

    assert cpu.step() == 16
    assert cpu.registers.sp == 0xFFFC
    assert cpu.bus.read(0xFFFC) == value & 0xFF
    assert cpu.bus.read(0xFFFD) == value >> 8


@pytest.mark.parametrize(
    ("opcode", "pair", "expected"),
    [
        (0xC1, "bc", 0x1234),
        (0xD1, "de", 0x1234),
        (0xE1, "hl", 0x1234),
        (0xF1, "af", 0x1230),
    ],
    ids=["BC", "DE", "HL", "AF"],
)
def test_pop_loads_the_pair_from_the_stack(
    cpu_running: CpuRunning, opcode: int, pair: str, expected: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.sp = 0xFFFC
    cpu.bus.write(0xFFFC, 0x34)
    cpu.bus.write(0xFFFD, 0x12)

    assert cpu.step() == 12
    assert getattr(cpu.registers, pair) == expected
    assert cpu.registers.sp == 0xFFFE


def test_pop_af_discards_the_low_nibble_of_f(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xF1)
    cpu.registers.sp = 0xFFFC
    cpu.bus.write(0xFFFC, 0x34)
    cpu.bus.write(0xFFFD, 0x12)

    cpu.step()

    assert cpu.registers.a == 0x12
    # F's bottom four bits do not exist on the hardware.
    assert cpu.registers.f == 0x30
    assert cpu.registers.z_flag is False
    assert cpu.registers.n_flag is False
    assert cpu.registers.h_flag is True
    assert cpu.registers.c_flag is True


def test_push_af_then_pop_af_restores_the_flags(cpu_running: CpuRunning) -> None:
    # F5 PUSH AF ; F1 POP AF
    cpu = cpu_running(0xF5, 0xF1)
    cpu.registers.sp = 0xFFFE
    cpu.registers.a = 0x42
    cpu.registers.z_flag = True
    cpu.registers.n_flag = False
    cpu.registers.h_flag = True
    cpu.registers.c_flag = False

    cpu.step()
    cpu.step()

    assert cpu.registers.a == 0x42
    assert cpu.registers.z_flag is True
    assert cpu.registers.n_flag is False
    assert cpu.registers.h_flag is True
    assert cpu.registers.c_flag is False
    assert cpu.registers.sp == 0xFFFE


def test_a_pair_can_be_pushed_and_popped_into_a_different_pair(
    cpu_running: CpuRunning,
) -> None:
    # C5 PUSH BC ; D1 POP DE
    cpu = cpu_running(0xC5, 0xD1)
    cpu.registers.sp = 0xFFFE
    cpu.registers.bc = 0xBEEF

    cpu.step()
    cpu.step()

    # Nothing on the stack records which register the bytes came from.
    assert cpu.registers.de == 0xBEEF
    assert cpu.registers.bc == 0xBEEF
    assert cpu.registers.sp == 0xFFFE


@pytest.mark.parametrize(
    ("opcode", "name", "cycles"),
    [
        (0xC5, "PUSH BC", 16),
        (0xD5, "PUSH DE", 16),
        (0xE5, "PUSH HL", 16),
        (0xF5, "PUSH AF", 16),
        (0xC1, "POP BC", 12),
        (0xD1, "POP DE", 12),
        (0xE1, "POP HL", 12),
        (0xF1, "POP AF", 12),
    ],
)
def test_the_push_pop_table_entries_are_named_and_costed(
    opcode: int, name: str, cycles: int
) -> None:
    instruction = OPCODES[opcode]

    assert instruction.name == name
    # PUSH costs one cycle more than POP for the same three accesses: the
    # 16-bit decrement of SP.
    assert instruction.cycles == cycles
    assert instruction.cycles_when_taken is None


# --- RST ---


@pytest.mark.parametrize(
    ("opcode", "target"),
    [
        (0xC7, 0x0000),
        (0xCF, 0x0008),
        (0xD7, 0x0010),
        (0xDF, 0x0018),
        (0xE7, 0x0020),
        (0xEF, 0x0028),
        (0xF7, 0x0030),
        (0xFF, 0x0038),
    ],
    ids=lambda value: f"{value:#04x}",
)
def test_rst_calls_its_fixed_target(
    cpu_running: CpuRunning, opcode: int, target: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.sp = 0xFFFE

    assert cpu.step() == 16
    assert cpu.registers.pc == target
    assert cpu.registers.sp == 0xFFFC
    assert cpu.bus.read16(0xFFFC) == 0x0101


def test_rst_returns_like_a_call(cpu_running: CpuRunning) -> None:
    # FF RST 0x38 ; (at 0x0038) C9 RET
    cpu = cpu_running(0xFF)
    cpu.bus.write(0x0038, 0xC9)
    cpu.registers.sp = 0xFFFE

    cpu.step()
    cpu.step()

    assert cpu.registers.pc == 0x0101
    assert cpu.registers.sp == 0xFFFE


def test_rst_does_not_touch_the_flags(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xFF)
    cpu.registers.sp = 0xFFFE
    cpu.registers.f = 0xF0

    cpu.step()

    assert cpu.registers.f == 0xF0


@pytest.mark.parametrize(
    ("opcode", "name"),
    [
        (0xC7, "RST 0x00"),
        (0xCF, "RST 0x08"),
        (0xD7, "RST 0x10"),
        (0xDF, "RST 0x18"),
        (0xE7, "RST 0x20"),
        (0xEF, "RST 0x28"),
        (0xF7, "RST 0x30"),
        (0xFF, "RST 0x38"),
    ],
)
def test_the_rst_table_entries_are_named_and_costed(opcode: int, name: str) -> None:
    instruction = OPCODES[opcode]

    assert instruction.name == name
    assert instruction.cycles == 16
    assert instruction.cycles_when_taken is None


# --- SP arithmetic ---

# sp, offset byte, result, H, C. The flags come from the unsigned low byte at
# bits 3 and 7, while the sum itself is signed and 16-bit.
SP_OFFSET_CASES = [
    (0x0000, 0x01, 0x0001, False, False),
    (0x000F, 0x01, 0x0010, True, False),
    (0x00FF, 0x01, 0x0100, True, True),
    (0xFFFF, 0x01, 0x0000, True, True),
    (0x0100, 0xFF, 0x00FF, False, False),
    (0x0002, 0xFE, 0x0000, True, True),
]
SP_OFFSET_IDS = [
    "no-flags",
    "half-carry",
    "half-carry-and-carry",
    "wraps-to-zero",
    "negative-offset",
    "negative-offset-carries",
]


@pytest.mark.parametrize(
    ("sp", "offset", "result", "h", "c"), SP_OFFSET_CASES, ids=SP_OFFSET_IDS
)
def test_add_sp_e8_moves_sp_and_sets_the_byte_flags(
    cpu_running: CpuRunning, sp: int, offset: int, result: int, h: bool, c: bool
) -> None:
    cpu = cpu_running(0xE8, offset)
    cpu.registers.sp = sp
    cpu.registers.f = 0xF0

    assert cpu.step() == 16
    assert cpu.registers.sp == result
    # Z is cleared even when the result is 0x0000: it is not a result flag here.
    assert cpu.registers.z_flag is False
    assert cpu.registers.n_flag is False
    assert cpu.registers.h_flag is h
    assert cpu.registers.c_flag is c


@pytest.mark.parametrize(
    ("sp", "offset", "result", "h", "c"), SP_OFFSET_CASES, ids=SP_OFFSET_IDS
)
def test_ld_hl_sp_e8_writes_hl_and_leaves_sp_alone(
    cpu_running: CpuRunning, sp: int, offset: int, result: int, h: bool, c: bool
) -> None:
    cpu = cpu_running(0xF8, offset)
    cpu.registers.sp = sp
    cpu.registers.f = 0xF0

    assert cpu.step() == 12
    assert cpu.registers.hl == result
    assert cpu.registers.sp == sp
    assert cpu.registers.z_flag is False
    assert cpu.registers.n_flag is False
    assert cpu.registers.h_flag is h
    assert cpu.registers.c_flag is c


def test_ld_sp_hl_copies_hl_without_touching_the_flags(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xF9)
    cpu.registers.hl = 0xBEEF
    cpu.registers.f = 0xF0

    assert cpu.step() == 8
    assert cpu.registers.sp == 0xBEEF
    assert cpu.registers.f == 0xF0


@pytest.mark.parametrize(
    ("opcode", "name", "cycles"),
    [
        (0xE8, "ADD SP, e8", 16),
        (0xF8, "LD HL, SP+e8", 12),
        (0xF9, "LD SP, HL", 8),
    ],
)
def test_the_sp_arithmetic_table_entries_are_named_and_costed(
    opcode: int, name: str, cycles: int
) -> None:
    instruction = OPCODES[opcode]

    assert instruction.name == name
    assert instruction.cycles == cycles
    assert instruction.cycles_when_taken is None


#
#  --- CB PREFIX DISPATCH ---
#


def test_the_cb_prefix_is_not_an_instruction_of_its_own() -> None:
    assert 0xCB not in OPCODES


def test_the_cb_prefix_decodes_from_the_second_table(cpu_running: CpuRunning) -> None:
    # 0x40 is LD B, B in the base table -- a copy that changes nothing at all.
    # In the CB table it is BIT 0, B, which writes flags. The flags are the only
    # thing that says which of the two tables was consulted.
    cpu = cpu_running(0xCB, 0x40, at=0x0100)
    cpu.registers.b = 0x00
    cpu.registers.f = 0x00

    cpu.step()

    assert OPCODES[0x40].name == "LD B, B"
    assert CB_OPCODES[0x40].name == "BIT 0, B"
    assert cpu.registers.z_flag is True
    assert cpu.registers.pc == 0x0102


def test_an_unprefixed_opcode_still_decodes_from_the_base_table(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0x00)

    assert cpu.step() == 4
    assert cpu.registers.pc == 0x0101


#
#  --- CB SHIFT BLOCK ---
#

# 00 ooo rrr: the operation index in bits 5 to 3, the operand in bits 2 to 0.
CB_SHIFT_BLOCK = [(opcode, Operand(opcode & 0b111)) for opcode in range(0x40)]

# One row per operation index, all against B. The encoding order is fixed by the
# hardware and does not follow alu.py's grouping by direction.
CB_SHIFT_OPERATIONS: list[tuple[int, str]] = [
    (0x00, "RLC"),
    (0x08, "RRC"),
    (0x10, "RL"),
    (0x18, "RR"),
    (0x20, "SLA"),
    (0x28, "SRA"),
    (0x30, "SWAP"),
    (0x38, "SRL"),
]


def test_the_cb_shift_block_covers_every_opcode() -> None:
    block = set(range(0x40))

    assert CB_OPCODES.keys() & block == block


@pytest.mark.parametrize(
    "opcode, name",
    CB_SHIFT_OPERATIONS,
    ids=[name for _, name in CB_SHIFT_OPERATIONS],
)
def test_the_cb_shift_block_names_each_operation_index(opcode: int, name: str) -> None:
    assert CB_OPCODES[opcode].name == f"{name} B"


@pytest.mark.parametrize(
    "opcode, name",
    [
        (0x00, "RLC B"),
        (0x06, "RLC (HL)"),
        (0x0F, "RRC A"),
        (0x30, "SWAP B"),
        (0x36, "SWAP (HL)"),
        (0x3F, "SRL A"),
    ],
)
def test_the_cb_shift_block_decodes_its_operand(opcode: int, name: str) -> None:
    assert CB_OPCODES[opcode].name == name


@pytest.mark.parametrize(
    "opcode, operand",
    CB_SHIFT_BLOCK,
    ids=[f"{opcode:#04x}" for opcode, _ in CB_SHIFT_BLOCK],
)
def test_the_cb_shift_block_cycle_costs_follow_the_access_rule(
    opcode: int, operand: Operand
) -> None:
    assert CB_OPCODES[opcode].cycles == count_cycles(operand, operand, prefixed=True)
    assert CB_OPCODES[opcode].cycles == (16 if operand is Operand.HL_POINTER else 8)


def test_the_cb_shift_block_binds_one_operand_per_entry(
    cpu_running: CpuRunning,
) -> None:
    # RLC 0x80 is 0x01
    cpu = cpu_running(0xCB, 0x00)  # RLC B
    cpu.registers.b = 0x80
    cpu.registers.c = 0x80

    cpu.step()

    assert (cpu.registers.b, cpu.registers.c) == (0x01, 0x80)

    cpu = cpu_running(0xCB, 0x01)  # RLC C
    cpu.registers.b = 0x80
    cpu.registers.c = 0x80

    cpu.step()

    assert (cpu.registers.b, cpu.registers.c) == (0x80, 0x01)


@pytest.mark.parametrize(
    "operand", REGISTER_OPERANDS, ids=[operand.name for operand in REGISTER_OPERANDS]
)
def test_a_shift_reads_and_writes_the_operand_its_opcode_names(
    cpu_running: CpuRunning, operand: Operand
) -> None:
    cpu = cpu_running(0xCB, 0x30 + operand)  # SWAP operand
    write_operand(cpu, operand, 0x4B)

    cycles = cpu.step()

    assert read_operand(cpu, operand) == 0xB4
    assert cycles == 8
    assert cpu.registers.pc == 0x0102


def test_a_shift_on_hl_pointer_writes_back_through_the_bus(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xCB, 0x36)  # SWAP (HL)
    cpu.registers.hl = 0xC000
    cpu.bus.write(0xC000, 0x4B)

    cycles = cpu.step()

    assert cpu.bus.read(0xC000) == 0xB4
    assert cpu.registers.hl == 0xC000
    assert cycles == 16


@pytest.mark.parametrize(
    "value, expected, expected_f",
    [
        (0x80, 0x00, 0x90),  # lands on zero, and bit 7 left: Z and C
        (0x01, 0x02, 0x00),  # nothing set
    ],
    ids=["0x80", "0x01"],
)
def test_a_shift_applies_its_flags_to_the_registers(
    cpu_running: CpuRunning, value: int, expected: int, expected_f: int
) -> None:
    cpu = cpu_running(0xCB, 0x20)  # SLA B
    cpu.registers.b = value

    cpu.step()

    assert cpu.registers.b == expected
    assert cpu.registers.f == expected_f


def test_rl_reads_the_carry_flag_out_of_the_registers(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xCB, 0x10)  # RL B
    cpu.registers.b = 0x00
    cpu.registers.c_flag = True

    cpu.step()

    assert cpu.registers.b == 0x01
    assert cpu.registers.c_flag is False


#
#  --- CB BIT, RES AND SET ---
#

# 01 bbb rrr is BIT, 10 bbb rrr is RES, 11 bbb rrr is SET: the bit index in bits
# 5 to 3, the operand in bits 2 to 0.
CB_BIT_BLOCK = [
    (opcode, (opcode >> 3) & 0b111, Operand(opcode & 0b111))
    for opcode in range(0x40, 0x80)
]
CB_WRITE_BACK_BLOCK = [
    (opcode, (opcode >> 3) & 0b111, Operand(opcode & 0b111))
    for opcode in range(0x80, 0x100)
]


def test_the_cb_table_is_complete() -> None:
    # The only table in the project with no holes: 256 defined, no illegal
    # opcodes, so no CB opcode can ever be unknown.
    assert CB_OPCODES.keys() == set(range(0x100))


@pytest.mark.parametrize(
    "opcode, name",
    [
        (0x40, "BIT 0, B"),
        (0x46, "BIT 0, (HL)"),
        (0x7E, "BIT 7, (HL)"),
        (0x7F, "BIT 7, A"),
        (0x80, "RES 0, B"),
        (0xBE, "RES 7, (HL)"),
        (0xC0, "SET 0, B"),
        (0xFF, "SET 7, A"),
    ],
)
def test_the_bit_families_decode_their_index_and_operand(
    opcode: int, name: str
) -> None:
    assert CB_OPCODES[opcode].name == name


@pytest.mark.parametrize(
    "family, base",
    [("BIT", 0x40), ("RES", 0x80), ("SET", 0xC0)],
)
def test_the_bit_families_decode_all_eight_indices(family: str, base: int) -> None:
    for bit in range(8):
        assert CB_OPCODES[base + bit * 8].name == f"{family} {bit}, B"


@pytest.mark.parametrize(
    "opcode, bit, operand",
    CB_BIT_BLOCK,
    ids=[f"{opcode:#04x}" for opcode, _, _ in CB_BIT_BLOCK],
)
def test_bit_costs_twelve_on_hl_because_it_never_writes_back(
    opcode: int, bit: int, operand: Operand
) -> None:
    assert CB_OPCODES[opcode].cycles == count_cycles(operand, prefixed=True)
    assert CB_OPCODES[opcode].cycles == (12 if operand is Operand.HL_POINTER else 8)


@pytest.mark.parametrize(
    "opcode, bit, operand",
    CB_WRITE_BACK_BLOCK,
    ids=[f"{opcode:#04x}" for opcode, _, _ in CB_WRITE_BACK_BLOCK],
)
def test_res_and_set_cycle_costs_follow_the_access_rule(
    opcode: int, bit: int, operand: Operand
) -> None:
    assert CB_OPCODES[opcode].cycles == count_cycles(operand, operand, prefixed=True)
    assert CB_OPCODES[opcode].cycles == (16 if operand is Operand.HL_POINTER else 8)


# BIT: Z is the *inverse* of the tested bit, N is cleared, H is set, C is left
# exactly as it was.


@pytest.mark.parametrize(
    "value, expected_z",
    [(0x00, True), (0x80, False)],
    ids=["bit clear", "bit set"],
)
def test_bit_sets_zero_when_the_tested_bit_is_clear(
    cpu_running: CpuRunning, value: int, expected_z: bool
) -> None:
    cpu = cpu_running(0xCB, 0x78)  # BIT 7, B
    cpu.registers.b = value

    cpu.step()

    assert cpu.registers.z_flag is expected_z


@pytest.mark.parametrize("carry", [False, True], ids=["c=0", "c=1"])
def test_bit_leaves_the_carry_alone(cpu_running: CpuRunning, carry: bool) -> None:
    cpu = cpu_running(0xCB, 0x40)  # BIT 0, B
    cpu.registers.b = 0x01
    cpu.registers.c_flag = carry

    cpu.step()

    assert cpu.registers.c_flag is carry


def test_bit_sets_the_half_carry_and_clears_n(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xCB, 0x40)  # BIT 0, B
    cpu.registers.b = 0x01
    cpu.registers.n_flag = True
    cpu.registers.h_flag = False

    cpu.step()

    assert cpu.registers.h_flag is True
    assert cpu.registers.n_flag is False


def test_bit_does_not_write_its_operand(cpu_running: CpuRunning) -> None:
    # 0xFF masked down to bit 0 would be 0x01, so writing the result back is
    # visible here and invisible with a value that already equals its mask.
    cpu = cpu_running(0xCB, 0x40)  # BIT 0, B
    cpu.registers.b = 0xFF

    cpu.step()

    assert cpu.registers.b == 0xFF


def test_bit_on_hl_pointer_reads_without_writing(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xCB, 0x7E)  # BIT 7, (HL)
    cpu.registers.hl = 0xC000
    cpu.bus.write(0xC000, 0xFF)

    cycles = cpu.step()

    assert cpu.bus.read(0xC000) == 0xFF
    assert cpu.registers.z_flag is False
    assert cycles == 12


# RES and SET write the operand back and touch no flag at all.


def test_res_clears_only_the_bit_its_opcode_names(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xCB, 0xB8)  # RES 7, B
    cpu.registers.b = 0xFF

    cpu.step()

    assert cpu.registers.b == 0x7F


def test_set_sets_only_the_bit_its_opcode_names(cpu_running: CpuRunning) -> None:
    cpu = cpu_running(0xCB, 0xF8)  # SET 7, B
    cpu.registers.b = 0x00

    cpu.step()

    assert cpu.registers.b == 0x80


@pytest.mark.parametrize("opcode", [0xB8, 0xF8], ids=["RES 7, B", "SET 7, B"])
def test_res_and_set_write_no_flags(cpu_running: CpuRunning, opcode: int) -> None:
    cpu = cpu_running(0xCB, opcode)
    cpu.registers.b = 0x0F
    cpu.registers.f = 0xF0

    cpu.step()

    assert cpu.registers.f == 0xF0


def test_set_on_hl_pointer_writes_back_through_the_bus(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xCB, 0xFE)  # SET 7, (HL)
    cpu.registers.hl = 0xC000
    cpu.bus.write(0xC000, 0x00)

    cycles = cpu.step()

    assert cpu.bus.read(0xC000) == 0x80
    assert cpu.registers.hl == 0xC000
    assert cycles == 16


def test_the_bit_families_bind_one_index_per_entry(cpu_running: CpuRunning) -> None:
    # Two entries of the same family, differing only in the bit field.
    cpu = cpu_running(0xCB, 0xC0)  # SET 0, B
    cpu.registers.b = 0x00

    cpu.step()

    assert cpu.registers.b == 0x01

    cpu = cpu_running(0xCB, 0xF8)  # SET 7, B
    cpu.registers.b = 0x00

    cpu.step()

    assert cpu.registers.b == 0x80


#
#  --- RLCA, RRCA, RLA, RRA ---
#

# The second byte of each CB twin is the same value as the base opcode: 0x07 is
# RLCA in the base table and RLC A in the CB one.
ACCUMULATOR_ROTATES = [(0x07, "RLCA"), (0x0F, "RRCA"), (0x17, "RLA"), (0x1F, "RRA")]
ROTATE_IDS = [name for _, name in ACCUMULATOR_ROTATES]


@pytest.mark.parametrize("opcode, name", ACCUMULATOR_ROTATES, ids=ROTATE_IDS)
def test_the_accumulator_rotates_are_one_byte_and_four_cycles(
    cpu_running: CpuRunning, opcode: int, name: str
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.a = 0x80

    cycles = cpu.step()

    assert OPCODES[opcode].name == name
    assert cycles == 4
    assert cpu.registers.pc == 0x0101


@pytest.mark.parametrize("opcode, name", ACCUMULATOR_ROTATES, ids=ROTATE_IDS)
def test_the_accumulator_rotates_always_clear_zero(
    cpu_running: CpuRunning, opcode: int, name: str
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.a = 0x00
    cpu.registers.c_flag = False

    cpu.step()

    assert cpu.registers.a == 0x00
    assert cpu.registers.z_flag is False


@pytest.mark.parametrize("opcode, name", ACCUMULATOR_ROTATES, ids=ROTATE_IDS)
def test_the_cb_twins_take_zero_from_the_result(
    cpu_running: CpuRunning, opcode: int, name: str
) -> None:
    # Same byte, same arithmetic, opposite answer on Z. This pair is the whole
    # reason these four were held back from Step 05.
    cpu = cpu_running(0xCB, opcode)
    cpu.registers.a = 0x00
    cpu.registers.c_flag = False

    cpu.step()

    assert cpu.registers.a == 0x00
    assert cpu.registers.z_flag is True


@pytest.mark.parametrize("opcode, name", ACCUMULATOR_ROTATES, ids=ROTATE_IDS)
@pytest.mark.parametrize("carry", [False, True], ids=["c=0", "c=1"])
def test_each_accumulator_rotate_matches_its_cb_twin_except_on_zero(
    cpu_running: CpuRunning, opcode: int, name: str, carry: bool
) -> None:
    for value in range(0x100):
        base = cpu_running(opcode)
        base.registers.a = value
        base.registers.c_flag = carry
        base.step()

        twin = cpu_running(0xCB, opcode)
        twin.registers.a = value
        twin.registers.c_flag = carry
        twin.step()

        assert base.registers.a == twin.registers.a, f"{name} {value:#04x}"
        assert base.registers.c_flag == twin.registers.c_flag, f"{name} {value:#04x}"
        assert base.registers.z_flag is False, f"{name} {value:#04x}"
        assert twin.registers.z_flag is (twin.registers.a == 0), f"{name} {value:#04x}"


@pytest.mark.parametrize("opcode, name", ACCUMULATOR_ROTATES, ids=ROTATE_IDS)
def test_the_accumulator_rotates_clear_n_and_h(
    cpu_running: CpuRunning, opcode: int, name: str
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.a = 0x55
    cpu.registers.n_flag = True
    cpu.registers.h_flag = True

    cpu.step()

    assert cpu.registers.n_flag is False
    assert cpu.registers.h_flag is False


@pytest.mark.parametrize(
    "opcode, value, expected_a",
    [
        (0x07, 0x80, 0x01),  # RLCA: bit 7 goes to C *and* around to bit 0
        (0x0F, 0x01, 0x80),  # RRCA: bit 0 goes to C *and* around to bit 7
        (0x17, 0x80, 0x00),  # RLA: bit 7 to C, bit 0 takes the old carry
        (0x1F, 0x01, 0x00),  # RRA: bit 0 to C, bit 7 takes the old carry
    ],
    ids=ROTATE_IDS,
)
def test_the_accumulator_rotates_send_the_departing_bit_to_the_carry(
    cpu_running: CpuRunning, opcode: int, value: int, expected_a: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.a = value
    cpu.registers.c_flag = False

    cpu.step()

    assert cpu.registers.a == expected_a
    assert cpu.registers.c_flag is True


@pytest.mark.parametrize(
    "opcode, expected_a",
    [(0x17, 0x01), (0x1F, 0x80)],
    ids=["RLA", "RRA"],
)
def test_rla_and_rra_bring_the_incoming_carry_into_the_vacated_end(
    cpu_running: CpuRunning, opcode: int, expected_a: int
) -> None:
    cpu = cpu_running(opcode)
    cpu.registers.a = 0x00
    cpu.registers.c_flag = True

    cpu.step()

    assert cpu.registers.a == expected_a
    assert cpu.registers.c_flag is False


def test_the_base_table_is_complete_but_for_step_08_and_the_illegal_opcodes() -> None:
    # These are the missing opcodes to finish the base table:
    step_08 = {0x10, 0x76, 0xD9, 0xF3, 0xFB}  # STOP, HALT, RETI, DI, EI
    illegal = {0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD}

    assert OPCODES.keys() == set(range(0x100)) - step_08 - illegal - {0xCB}
    assert len(OPCODES) == 239
    assert len(OPCODES) + 1 + len(step_08) + len(illegal) == 0x100
