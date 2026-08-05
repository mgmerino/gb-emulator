"""Masking cheatsheet:
_______________________________________________________________
 HEX   |    BIN    |  OPERATION   | WHY
0xFF   | 11111111  | value & mask | wraps the value to 8 bits/reveals the low byte
0x80   | 10000000  | value & mask | checks the leftmost bit
0x100  | 100000000 | value - mask | subtract from an unsigned byte whose bit 7 is set to get its signed value
"""


def u8(value: int) -> int:
    return value & 0xFF


def u16(value: int) -> int:
    return value & 0xFFFF


def to_signed8(value: int) -> int:
    if value & 0x80:
        return value - 0x100

    return value


def get_bit(value: int, bit: int) -> bool:
    mask = 1 << bit

    return bool(value & mask)


def set_bit(value: int, bit: int) -> int:
    mask = 1 << bit

    return value | mask


def clear_bit(value: int, bit: int) -> int:
    mask = ~(1 << bit)

    return value & mask


def high_byte(value: int) -> int:
    return (value >> 8) & 0xFF


def low_byte(value: int) -> int:
    return value & 0xFF


def join_bytes(high: int, low: int) -> int:
    return (high << 8) | low
