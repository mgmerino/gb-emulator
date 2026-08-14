from dataclasses import dataclass

from gameboy.bits import u8


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
