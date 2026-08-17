import pytest
from conftest import CpuRunning

from gameboy.alu import Flags
from gameboy.cpu import (
    OPCODES,
    Operand,
    Registers,
    UnknownOpcodeError,
    count_cycles,
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
