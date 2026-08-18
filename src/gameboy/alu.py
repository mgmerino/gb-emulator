from dataclasses import dataclass

from gameboy.bits import u8, u16


@dataclass(frozen=True, slots=True)
class Flags:
    z: bool | None = None
    n: bool | None = None
    h: bool | None = None
    c: bool | None = None


def add(a: int, b: int) -> tuple[int, Flags]:
    total = a + b
    result = u8(total)

    flags = Flags(
        z=result == 0,
        n=False,
        h=(a & 0x0F) + (b & 0x0F) > 0x0F,
        c=total > 0xFF,
    )

    return result, flags


def sub(a: int, b: int) -> tuple[int, Flags]:
    total = a - b
    result = u8(total)

    flags = Flags(
        z=result == 0,
        n=True,
        h=(a & 0x0F) < (b & 0x0F),
        c=a < b,
    )

    return result, flags


def adc(a: int, b: int, carry: bool) -> tuple[int, Flags]:
    total = a + b + carry
    result = u8(total)

    flags = Flags(
        z=result == 0,
        n=False,
        h=(a & 0x0F) + (b & 0x0F) + carry > 0x0F,
        c=total > 0xFF,
    )

    return result, flags


def sbc(a: int, b: int, carry: bool) -> tuple[int, Flags]:
    total = a - b - carry
    result = u8(total)

    flags = Flags(
        z=result == 0,
        n=True,
        h=(a & 0x0F) < (b & 0x0F) + carry,
        c=a < b + carry,
    )

    return result, flags


def and_(a: int, b: int) -> tuple[int, Flags]:
    result = u8(a & b)

    flags = Flags(
        z=result == 0,
        n=False,
        h=True,
        c=False,
    )
    return result, flags


def or_(a: int, b: int) -> tuple[int, Flags]:
    result = u8(a | b)

    flags = Flags(
        z=result == 0,
        n=False,
        h=False,
        c=False,
    )
    return result, flags


def xor(a: int, b: int) -> tuple[int, Flags]:
    result = u8(a ^ b)

    flags = Flags(
        z=result == 0,
        n=False,
        h=False,
        c=False,
    )
    return result, flags


def inc(value: int) -> tuple[int, Flags]:
    result = u8(value + 1)

    flags = Flags(
        z=result == 0,
        n=False,
        h=(value & 0x0F) == 0xF,  # low nibble was 0xF
    )
    return result, flags


def dec(value: int) -> tuple[int, Flags]:
    result = u8(value - 1)

    flags = Flags(
        z=result == 0,
        n=True,
        h=(value & 0x0F) == 0x0,  # low nibble was 0x0
    )
    return result, flags


def add16(a: int, b: int) -> tuple[int, Flags]:
    total = a + b
    result = u16(total)

    flags = Flags(
        z=None,
        n=False,
        h=(a & 0x0FFF) + (b & 0x0FFF) > 0x0FFF,
        c=total > 0xFFFF,
    )

    return result, flags


# Decimal Adjust Accumulator
#
# A bit of explanation, because this is a tricky one. Games store scores and
# timers as binary-coded decimal: one decimal digit per nibble, so the byte
# 0x37 means thirty-seven, not fifty-five. Displaying such a number means
# splitting nibbles, which is cheap. The alternative is dividing by ten, and
# this CPU has no divide instruction.
#
# The problem: ADD and SUB work in binary. Nibbles wrap at 16, decimal digits
# wrap at 10, so adding two valid BCD bytes usually produces a byte that is
# *not* valid as a binary representation of a decimal:
#
#     0x37 + 0x05 = 0x3C     but 37 + 5 = 42, so the answer should be 0x42
#
# DAA converts A after the ADD/SUB. It is a separate instruction, the program
# runs ADD, then runs DAA, and _only_ then A is meaningful as a decimal number.
#
# The trick: add 0x06 to fix a broken low nibble and 0x60 to fix a broken high
# one. Six is the gap between the two wrap points, 16 - 10.
#
# It also fixes the carry, which is the half that is easy to forget. Binary
# carries out at 256, decimal should carry out at 100.
#
# 0x99 + 0x01 gives 0x9A with C clear, but 99 + 1 = 100 and there must be a
# carry out. DAA is what sets it:
#
#     0x91 + 0x11 = 0xA2         (intent: 91 + 11 = 102)
#     DAA: low nibble is 2, H clear   -> no 0x06
#          0xA2 > 0x99                -> add 0x60, set C
#          0xA2 + 0x60 = 0x102 -> 0x02 with carry.  Correct: "02" carry 1.
#
# The flags are inputs because the type cannot be infered only with A:
#
# 0x08 + 0x08 = 0x10, which reads as perfectly valid BCD for ten. Only H, left
# set by the add, reveals that the low nibble overflowed and the true  value is
# sixteen, 0x16. Same for N: A cannot say whether it got here by adding or
# subtracting.


def daa(a: int, n: bool, h: bool, c: bool) -> tuple[int, Flags]:
    adjust = 0
    if not n:
        if h or (a & 0x0F) > 0x9:
            adjust |= 0x06
        if c or a > 0x99:
            adjust |= 0x60
            c = True  # the decimal carry, out of 99
        result = u8(a + adjust)

    else:
        # C is preserved here
        if h:
            adjust |= 0x06
        if c:
            adjust |= 0x60
        result = u8(a - adjust)

    flags = Flags(z=result == 0, n=None, h=False, c=c)

    return result, flags
