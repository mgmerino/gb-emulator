"""The flag rules.

Expected values come from the table in `docs/STEP_05.md`, section 5, which was
cross-checked against https://gbdev.io/gb-opcodes/optables/.

`Flags` is a frozen dataclass, so `==` compares all four fields at once.
"""

from collections.abc import Callable

import pytest

from gameboy import alu
from gameboy.alu import Flags

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
