"""The flag rules.

Expected values come from the table in `docs/STEP_05.md`, section 5, which was
cross-checked against https://gbdev.io/gb-opcodes/optables/.

`Flags` is a frozen dataclass, so `==` compares all four fields at once.
"""

from collections.abc import Callable

import pytest

from gameboy import alu
from gameboy.alu import Flags
from gameboy.bits import get_bit, to_signed8, u8

type BinaryOp = Callable[[int, int], tuple[int, Flags]]


def test_flags_default_to_writing_nothing() -> None:
    assert Flags() == Flags(z=None, n=None, h=None, c=None)


# --- ADD ----------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,result,flags",
    [
        (0x00, 0x00, 0x00, Flags(z=True, n=False, h=False, c=False)),
        (0x3C, 0x18, 0x54, Flags(z=False, n=False, h=True, c=False)),
        # Carries out of bit 7 without ever carrying out of bit 3: the case that
        # separates H from C.
        (0xF0, 0x10, 0x00, Flags(z=True, n=False, h=False, c=True)),
        # And the mirror: the low nibble overflows, the byte does not.
        (0x0F, 0x01, 0x10, Flags(z=False, n=False, h=True, c=False)),
        (0xFF, 0x01, 0x00, Flags(z=True, n=False, h=True, c=True)),
    ],
)
def test_add(a: int, b: int, result: int, flags: Flags) -> None:
    assert alu.add(a, b) == (result, flags)


# --- SUB ----------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,result,flags",
    [
        (0x00, 0x00, 0x00, Flags(z=True, n=True, h=False, c=False)),
        (0x3C, 0x3C, 0x00, Flags(z=True, n=True, h=False, c=False)),
        (0x54, 0x18, 0x3C, Flags(z=False, n=True, h=True, c=False)),
        # Borrows out of the low nibble without borrowing out of the byte.
        (0x10, 0x01, 0x0F, Flags(z=False, n=True, h=True, c=False)),
        # Borrows out of both, and wraps: the result is 0xFF, not -1.
        (0x00, 0x01, 0xFF, Flags(z=False, n=True, h=True, c=True)),
    ],
)
def test_sub(a: int, b: int, result: int, flags: Flags) -> None:
    assert alu.sub(a, b) == (result, flags)


# --- ADC ----------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,carry,result,flags",
    [
        (0x00, 0x00, False, 0x00, Flags(z=True, n=False, h=False, c=False)),
        # With carry clear, ADC is ADD.
        (0x3C, 0x18, False, 0x54, Flags(z=False, n=False, h=True, c=False)),
        (0x3C, 0x18, True, 0x55, Flags(z=False, n=False, h=True, c=False)),
        # The carry is the reason the low nibbles overflow.
        (0x0F, 0x00, True, 0x10, Flags(z=False, n=False, h=True, c=False)),
        # The carry is the reason the byte wraps.
        (0xFF, 0x00, True, 0x00, Flags(z=True, n=False, h=True, c=True)),
        # carry in is clear, carry out is set.
        (0x80, 0x80, False, 0x00, Flags(z=True, n=False, h=False, c=True)),
        # And the reverse:
        (0x00, 0x00, True, 0x01, Flags(z=False, n=False, h=False, c=False)),
    ],
)
def test_adc(a: int, b: int, carry: bool, result: int, flags: Flags) -> None:
    assert alu.adc(a, b, carry) == (result, flags)


# --- SBC ----------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,carry,result,flags",
    [
        (0x00, 0x00, False, 0x00, Flags(z=True, n=True, h=False, c=False)),
        (0x3C, 0x18, False, 0x24, Flags(z=False, n=True, h=False, c=False)),
        (0x3C, 0x18, True, 0x23, Flags(z=False, n=True, h=False, c=False)),
        # The carry is the reason the low nibble borrows.
        (0x10, 0x00, True, 0x0F, Flags(z=False, n=True, h=True, c=False)),
        # The carry is the reason the byte borrows.
        (0x00, 0x00, True, 0xFF, Flags(z=False, n=True, h=True, c=True)),
        # Borrow in is set, and equal operands still end up borrowing because of
        # it.
        (0x01, 0x01, True, 0xFF, Flags(z=False, n=True, h=True, c=True)),
        # Borrow in is set and the result is still zero.
        (0x01, 0x00, True, 0x00, Flags(z=True, n=True, h=False, c=False)),
    ],
)
def test_sbc(a: int, b: int, carry: bool, result: int, flags: Flags) -> None:
    assert alu.sbc(a, b, carry) == (result, flags)


# --- AND, OR, XOR -------------------------------------------------------

# The three bitwise operations share a flag shape: N and C are always clear, Z
# comes from the result, and only H tells them apart. AND sets it, the other two
# clear it. There is no arithmetic reason for that, the hardware does it.


@pytest.mark.parametrize(
    "op,a,b,result,flags",
    [
        (alu.and_, 0x5A, 0x0F, 0x0A, Flags(z=False, n=False, h=True, c=False)),
        (alu.and_, 0xF0, 0x0F, 0x00, Flags(z=True, n=False, h=True, c=False)),
        (alu.or_, 0x5A, 0x0F, 0x5F, Flags(z=False, n=False, h=False, c=False)),
        (alu.or_, 0x00, 0x00, 0x00, Flags(z=True, n=False, h=False, c=False)),
        (alu.xor, 0xFF, 0x0F, 0xF0, Flags(z=False, n=False, h=False, c=False)),
        (alu.xor, 0x5A, 0x5A, 0x00, Flags(z=True, n=False, h=False, c=False)),
    ],
)
def test_bitwise(op: BinaryOp, a: int, b: int, result: int, flags: Flags) -> None:
    assert op(a, b) == (result, flags)


def test_xor_with_itself_is_the_idiomatic_zero() -> None:
    # `XOR A` is how every Game Boy program writes 0 into A: one byte instead of
    # two, and it sets Z as a side effect.
    assert alu.xor(0x37, 0x37) == (0x00, Flags(z=True, n=False, h=False, c=False))


# --- INC and DEC --------------------------------------------------------


@pytest.mark.parametrize(
    "value,result,flags",
    [
        (0x00, 0x01, Flags(z=False, n=False, h=False, c=None)),
        (0x0F, 0x10, Flags(z=False, n=False, h=True, c=None)),
        (0xFF, 0x00, Flags(z=True, n=False, h=True, c=None)),
    ],
)
def test_inc(value: int, result: int, flags: Flags) -> None:
    assert alu.inc(value) == (result, flags)


@pytest.mark.parametrize(
    "value,result,flags",
    [
        (0x01, 0x00, Flags(z=True, n=True, h=False, c=None)),
        (0x10, 0x0F, Flags(z=False, n=True, h=True, c=None)),
        (0x00, 0xFF, Flags(z=False, n=True, h=True, c=None)),
    ],
)
def test_dec(value: int, result: int, flags: Flags) -> None:
    assert alu.dec(value) == (result, flags)


@pytest.mark.parametrize("value", [0x00, 0x0F, 0x7F, 0xFF])
def test_inc_and_dec_do_not_write_the_carry_flag(value: int) -> None:
    """This is what lets a loop counter be incremented in the middle of a
    multi-byte addition without destroying the carry being propagated.
    """
    _, inc_flags = alu.inc(value)
    _, dec_flags = alu.dec(value)

    assert inc_flags.c is None
    assert dec_flags.c is None


ADD16_CASES: list[tuple[int, int, int, bool, bool]] = [
    # a, b, result, H, C
    (0x0000, 0x0001, 0x0001, False, False),
    (0x0FFF, 0x0001, 0x1000, True, False),  # exactly the bit-11 boundary
    (0x00FF, 0x0001, 0x0100, False, False),  # bit-7 carry is NOT a half-carry
    (0x8A23, 0x0605, 0x9028, True, False),  # 0xA23 + 0x605 crosses bit 11
    (0x0800, 0x0800, 0x1000, True, False),
    (0x8000, 0x8000, 0x0000, False, True),  # carry out of bit 15, none at 11
    (0xFFFF, 0x0001, 0x0000, True, True),  # both, and it wraps
]


@pytest.mark.parametrize(
    "a, b, expected, half_carry, carry",
    ADD16_CASES,
    ids=[f"{a:#06x}+{b:#06x}" for a, b, _, _, _ in ADD16_CASES],
)
def test_add16_result_and_carries(
    a: int, b: int, expected: int, half_carry: bool, carry: bool
) -> None:
    result, flags = alu.add16(a, b)

    assert result == expected
    assert flags.h is half_carry
    assert flags.c is carry
    assert flags.n is False


def test_add16_never_writes_the_zero_flag() -> None:
    _, flags = alu.add16(0x8000, 0x8000)

    assert flags.z is None


def bcd(value: int) -> int:
    """Encode 0-99 as binary-coded decimal: one decimal digit per nibble."""
    return ((value // 10) << 4) | (value % 10)


DAA_CASES: list[tuple[int, bool, bool, bool, int, bool, str]] = [
    # a, n, h, c, result, carry out, what produced `a`
    (0x42, False, False, False, 0x42, False, "already valid BCD, nothing to fix"),
    (0x3C, False, False, False, 0x42, False, "0x37 + 0x05 -> 37 + 5 = 42"),
    (0x9A, False, False, False, 0x00, True, "0x99 + 0x01 -> 99 + 1 = 100"),
    (0x32, False, True, True, 0x98, True, "0x99 + 0x99 -> 99 + 99 = 198"),
    (0x0A, False, False, False, 0x10, False, "0x05 + 0x05 -> 5 + 5 = 10"),
    (0x2D, True, True, False, 0x27, False, "0x32 - 0x05 -> 32 - 5 = 27"),
    (0xE0, True, False, True, 0x80, True, "0x20 - 0x40 -> 20 - 40 = -20"),
]


@pytest.mark.parametrize(
    "a, n, h, c, expected, expected_carry, note",
    DAA_CASES,
    ids=[note for *_, note in DAA_CASES],
)
def test_daa_named_cases(
    a: int,
    n: bool,
    h: bool,
    c: bool,
    expected: int,
    expected_carry: bool,
    note: str,
) -> None:
    result, flags = alu.daa(a, n, h, c)

    assert result == expected
    assert flags.c is expected_carry


def test_daa_round_trips_every_bcd_addition() -> None:
    """For every pair of decimal values, ADD then DAA is decimal addition."""
    for x in range(100):
        for y in range(100):
            total, add_flags = alu.add(bcd(x), bcd(y))
            # add always writes H and C, but Flags cannot say so in its type:
            # the None is there for the operations that leave a flag alone.
            assert add_flags.h is not None and add_flags.c is not None

            result, flags = alu.daa(total, n=False, h=add_flags.h, c=add_flags.c)

            assert result == bcd((x + y) % 100), f"{x} + {y}"
            assert flags.c is (x + y >= 100), f"carry on {x} + {y}"


def test_daa_round_trips_every_bcd_subtraction() -> None:
    """The mirror: this branch must leave the carry alone."""
    for x in range(100):
        for y in range(100):
            difference, sub_flags = alu.sub(bcd(x), bcd(y))
            assert sub_flags.h is not None and sub_flags.c is not None

            result, flags = alu.daa(difference, n=True, h=sub_flags.h, c=sub_flags.c)

            assert result == bcd((x - y) % 100), f"{x} - {y}"
            assert flags.c is (y > x), f"borrow on {x} - {y}"


@pytest.mark.parametrize(
    "a, n, h, c, expected",
    [
        (0x42, False, False, False, 0x42),  # no adjustment, non-zero result
        (0xA0, False, False, False, 0x00),  # adjustment fires and lands on zero
        (0x9A, False, False, False, 0x00),  # both branches fire, lands on zero
        (0x00, False, False, False, 0x00),  # already zero, nothing to adjust
    ],
    ids=["0x42", "0xA0", "0x9A", "0x00"],
)
def test_daa_takes_the_zero_flag_from_the_result(
    a: int, n: bool, h: bool, c: bool, expected: int
) -> None:
    # Z describes the adjusted accumulator, not if an adjustment happened.
    result, flags = alu.daa(a, n, h, c)

    assert result == expected
    assert flags.z is (result == 0)


@pytest.mark.parametrize("n", [False, True], ids=["after-add", "after-sub"])
def test_daa_clears_the_half_carry_and_leaves_n_alone(n: bool) -> None:
    _, flags = alu.daa(0x9A, n=n, h=True, c=True)

    assert flags.h is False
    assert flags.n is None


#
# --- rotates, shifts and swap ---
#

type ShiftOp = Callable[[int, bool], tuple[int, Flags]]

# Normalised so every op takes the incoming carry; the six that never read it
# discard it. Same lambda-wrapping idiom as `_ALU_OPERATIONS` in cpu.py.
SHIFTS: dict[str, ShiftOp] = {
    "rlc": lambda value, _carry: alu.rlc(value),
    "rrc": lambda value, _carry: alu.rrc(value),
    "rl": alu.rl,
    "rr": alu.rr,
    "sla": lambda value, _carry: alu.sla(value),
    "sra": lambda value, _carry: alu.sra(value),
    "swap": lambda value, _carry: alu.swap(value),
    "srl": lambda value, _carry: alu.srl(value),
}

DEPARTING_BIT = {"rlc": 7, "rl": 7, "sla": 7, "rrc": 0, "rr": 0, "sra": 0, "srl": 0}

BYTES = range(0x100)


@pytest.mark.parametrize(
    "name, bit", list(DEPARTING_BIT.items()), ids=list(DEPARTING_BIT)
)
@pytest.mark.parametrize("carry_in", [False, True], ids=["c=0", "c=1"])
def test_carry_is_the_bit_that_left_the_byte(
    name: str, bit: int, carry_in: bool
) -> None:
    for value in BYTES:
        _, flags = SHIFTS[name](value, carry_in)
        assert flags.c is get_bit(value, bit), f"{name}({value:#04x})"


def test_swap_clears_the_carry() -> None:
    for value in BYTES:
        _, flags = alu.swap(value)
        assert flags.c is False, f"swap({value:#04x})"


def test_rlc_brings_the_departing_bit_around() -> None:
    for value in BYTES:
        result, _ = alu.rlc(value)
        assert get_bit(result, 0) is get_bit(value, 7), f"{value:#04x}"


def test_rrc_brings_the_departing_bit_around() -> None:
    for value in BYTES:
        result, _ = alu.rrc(value)
        assert get_bit(result, 7) is get_bit(value, 0), f"{value:#04x}"


@pytest.mark.parametrize("carry_in", [False, True], ids=["c=0", "c=1"])
def test_rl_brings_the_incoming_carry_in(carry_in: bool) -> None:
    for value in BYTES:
        result, _ = alu.rl(value, carry_in)
        assert get_bit(result, 0) is carry_in, f"{value:#04x}"


@pytest.mark.parametrize("carry_in", [False, True], ids=["c=0", "c=1"])
def test_rr_brings_the_incoming_carry_in(carry_in: bool) -> None:
    for value in BYTES:
        result, _ = alu.rr(value, carry_in)
        assert get_bit(result, 7) is carry_in, f"{value:#04x}"


def test_sla_fills_with_zero() -> None:
    for value in BYTES:
        result, _ = alu.sla(value)
        assert get_bit(result, 0) is False, f"{value:#04x}"


def test_srl_fills_with_zero() -> None:
    for value in BYTES:
        result, _ = alu.srl(value)
        assert get_bit(result, 7) is False, f"{value:#04x}"


def test_sra_preserves_the_sign_bit() -> None:
    for value in BYTES:
        result, _ = alu.sra(value)
        assert get_bit(result, 7) is get_bit(value, 7), f"{value:#04x}"


def test_sla_doubles() -> None:
    for value in BYTES:
        result, _ = alu.sla(value)
        assert result == u8(value * 2), f"{value:#04x}"


def test_srl_halves_as_unsigned() -> None:
    for value in BYTES:
        result, _ = alu.srl(value)
        assert result == value // 2, f"{value:#04x}"


def test_sra_halves_as_signed() -> None:
    # Floor division, so SRA(0xFF) is 0xFF: -1 // 2 is -1, not 0.
    for value in BYTES:
        result, _ = alu.sra(value)
        assert to_signed8(result) == to_signed8(value) // 2, f"{value:#04x}"


def test_swap_exchanges_the_nibbles() -> None:
    for value in BYTES:
        result, _ = alu.swap(value)
        assert (result >> 4, result & 0x0F) == (value & 0x0F, value >> 4), (
            f"{value:#04x}"
        )


# Round trips


def test_rlc_and_rrc_are_inverses() -> None:
    for value in BYTES:
        rotated, _ = alu.rlc(value)
        back, _ = alu.rrc(rotated)
        assert back == value, f"{value:#04x}"


def test_swap_is_its_own_inverse() -> None:
    for value in BYTES:
        once, _ = alu.swap(value)
        twice, _ = alu.swap(once)
        assert twice == value, f"{value:#04x}"


@pytest.mark.parametrize("carry_in", [False, True], ids=["c=0", "c=1"])
def test_rl_and_rr_are_inverses_including_the_carry(carry_in: bool) -> None:
    # If rl and rr are wrong in the same mirrored way, both halves still round
    # trip and this passes. The contract tests above are what catch that.
    for value in BYTES:
        rotated, out = alu.rl(value, carry_in)
        assert out.c is not None, f"rl left C untouched at {value:#04x}"
        back, back_out = alu.rr(rotated, out.c)
        assert (back, back_out.c) == (value, carry_in), f"{value:#04x}"


@pytest.mark.parametrize("name", list(SHIFTS), ids=list(SHIFTS))
@pytest.mark.parametrize("carry_in", [False, True], ids=["c=0", "c=1"])
def test_n_and_h_are_always_clear(name: str, carry_in: bool) -> None:
    for value in BYTES:
        _, flags = SHIFTS[name](value, carry_in)
        assert (flags.n, flags.h) == (False, False), f"{name}({value:#04x})"


@pytest.mark.parametrize("name", list(SHIFTS), ids=list(SHIFTS))
@pytest.mark.parametrize("carry_in", [False, True], ids=["c=0", "c=1"])
def test_z_is_set_exactly_when_the_result_is_zero(name: str, carry_in: bool) -> None:
    for value in BYTES:
        result, flags = SHIFTS[name](value, carry_in)
        assert flags.z is (result == 0), f"{name}({value:#04x})"
