import pytest

from gameboy.bits import (
    clear_bit,
    get_bit,
    high_byte,
    join_bytes,
    low_byte,
    set_bit,
    to_signed8,
    u8,
    u16,
)


@pytest.mark.parametrize(
    ("raw", "expected"), [(0x1FF, 0xFF), (0xAAA, 0xAA), (0x102, 2), (-1, 255)]
)
def test_u8(raw: int, expected: int) -> None:
    assert u8(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [(0x10000, 0x0000), (0x10001, 0x0001)])
def test_u16(raw: int, expected: int) -> None:
    assert u16(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"), [(0x7F, 127), (0x00, 0), (0x80, -128), (0xFF, -1)]
)
def test_to_signed8(raw: int, expected: int) -> None:
    assert to_signed8(raw) == expected


@pytest.mark.parametrize(("value", "bit"), [(0b1010, 1), (0b1000, 3)])
def test_get_bit_on(value: int, bit: int) -> None:
    assert get_bit(value, bit)


@pytest.mark.parametrize(("value", "bit"), [(0b0010, 2), (0b1010, 0)])
def test_get_bit_off(value: int, bit: int) -> None:
    assert not get_bit(value, bit)


@pytest.mark.parametrize(
    ("value", "bit", "expected"), [(0b0010, 0, 0b0011), (0b0010, 1, 0b0010)]
)
def test_set_bit(value: int, bit: int, expected: int) -> None:
    assert set_bit(value, bit) == expected


@pytest.mark.parametrize(
    ("value", "bit", "expected"), [(0b0010, 1, 0b0000), (0b0010, 0, 0b0010)]
)
def test_clear_bit(value: int, bit: int, expected: int) -> None:
    assert clear_bit(value, bit) == expected


def test_high_byte() -> None:
    raw = 0x1234
    expected = 0x12

    assert high_byte(raw) == expected


def test_low_byte() -> None:
    raw = 0x1234
    expected = 0x34

    assert low_byte(raw) == expected


@pytest.mark.parametrize(
    ("high", "low", "expected"), [(0x12, 0x34, 0x1234), (0xA6, 0xFA, 0xA6FA)]
)
def test_join_bytes(high: int, low: int, expected: int) -> None:
    assert join_bytes(high, low) == expected


@pytest.mark.parametrize("value", [0x0000, 0x00FF, 0x1234, 0xABCD, 0xFF00, 0xFFFF])
def test_byte_round_trip(value: int) -> None:
    assert join_bytes(high_byte(value), low_byte(value)) == value
