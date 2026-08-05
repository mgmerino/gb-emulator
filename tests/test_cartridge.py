"""Tests for cartridge header parsing.

`build_rom` produces a valid 32 KiB ROM-only cartridge by default and takes
keyword overrides for whichever field a test is about.
"""

import os
from pathlib import Path

import pytest

from gameboy.cartridge import (
    CARTRIDGE_TYPE,
    CGB_FLAG,
    DEST_CODE,
    GLOBAL_CHECKSUM,
    HEADER_CHECKSUM,
    RAM_SIZE,
    ROM_SIZE,
    ROM_VERSION,
    SGB_FLAG,
    TITLE,
    Cartridge,
    CartridgeType,
    ColorFlagType,
    InvalidCartridgeError,
    compute_global_checksum,
    compute_header_checksum,
    parse_header,
)

# The 48 bytes the boot ROM compares against its own copy before booting.
NINTENDO_LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D"
    "0008111F8889000EDCCC6EE6DDDDD999"
    "BBBB67636E0EECCCDDDC999FBBB9333E"
)


def build_rom(
    *,
    title: str = "SMARIOWATERPOLO",
    cartridge_type: int = 0x00,
    rom_size: int = 0x00,
    ram_size: int = 0x00,
    cgb_flag: int = 0x00,
    sgb_flag: int = 0x00,
    destination: int = 0x00,
    version: int = 0x01,
    length: int = 0x8000,
    valid_header_checksum: bool = True,
) -> bytes:
    """Build a synthetic cartridge image with a well-formed header.

    The header is always written into a full-size image and the result is
    truncated afterwards, so `length` may be shorter than a header.
    """
    rom = bytearray(max(length, 0x8000))

    rom[0x0100:0x0104] = bytes([0x00, 0xC3, 0x50, 0x01])  # NOP ; JP 0x0150
    rom[0x0104:0x0134] = NINTENDO_LOGO
    rom[TITLE] = title.encode("ascii").ljust(TITLE.stop - TITLE.start, b"\x00")
    rom[CGB_FLAG] = cgb_flag
    rom[SGB_FLAG] = sgb_flag
    rom[CARTRIDGE_TYPE] = cartridge_type
    rom[ROM_SIZE] = rom_size
    rom[RAM_SIZE] = ram_size
    rom[DEST_CODE] = destination
    rom[ROM_VERSION] = version

    rom[HEADER_CHECKSUM] = compute_header_checksum(bytes(rom))
    if not valid_header_checksum:
        rom[HEADER_CHECKSUM] ^= 0xFF

    total = compute_global_checksum(bytes(rom))
    rom[GLOBAL_CHECKSUM.start] = (total >> 8) & 0xFF
    rom[GLOBAL_CHECKSUM.start + 1] = total & 0xFF

    return bytes(rom[:length])


# --- parsing --------------------------------------------------------------


def test_parses_a_valid_rom_only_header() -> None:
    header = parse_header(build_rom())

    assert header.title == "SMARIOWATERPOLO"
    assert header.cartridge_type is CartridgeType.ROM_ONLY
    assert header.rom_size == 32 * 1024
    assert header.rom_banks == 2
    assert header.ram_size == 0
    assert header.cgb_flag is ColorFlagType.DMG
    assert header.sgb_flag is False
    assert header.version == 1


def test_title_stops_before_the_cgb_flag() -> None:
    """A Color cartridge must not leak 0x80 into the title string."""
    header = parse_header(build_rom(title="POKEMON", cgb_flag=0x80))

    assert header.title == "POKEMON"
    assert header.cgb_flag is ColorFlagType.COLOR_ENHANCED


def test_header_is_frozen() -> None:
    header = parse_header(build_rom())

    with pytest.raises(AttributeError):
        header.title = "OTHER"  # type: ignore[misc]


def test_truncated_file_raises() -> None:
    with pytest.raises(InvalidCartridgeError, match="at least"):
        parse_header(build_rom(length=0x100))


def test_unknown_cartridge_type_raises() -> None:
    with pytest.raises(ValueError, match="0x99|153"):
        parse_header(build_rom(cartridge_type=0x99))


# --- size encodings -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_bytes", "expected_banks"),
    [
        (0x00, 32 * 1024, 2),
        (0x01, 64 * 1024, 4),
        (0x05, 1024 * 1024, 64),
        (0x08, 8 * 1024 * 1024, 512),
    ],
)
def test_rom_size_is_a_shift(
    raw: int, expected_bytes: int, expected_banks: int
) -> None:
    header = parse_header(build_rom(rom_size=raw))

    assert header.rom_size == expected_bytes
    assert header.rom_banks == expected_banks


@pytest.mark.parametrize(
    ("raw", "expected_bytes", "expected_banks"),
    [
        (0x00, 0, 0),
        (0x02, 8 * 1024, 1),
        (0x03, 32 * 1024, 4),
        (0x04, 128 * 1024, 16),
        (0x05, 64 * 1024, 8),
    ],
)
def test_ram_size_is_a_lookup_table(
    raw: int, expected_bytes: int, expected_banks: int
) -> None:
    """0x04 is larger than 0x05 — the table is not ordered."""
    header = parse_header(build_rom(ram_size=raw))

    assert header.ram_size == expected_bytes
    assert header.ram_banks == expected_banks


# --- checksums ------------------------------------------------------------


def test_header_checksum_matches_a_hand_computed_value() -> None:
    rom = build_rom()

    expected = 0
    for address in range(0x0134, 0x014D):
        expected = (expected - rom[address] - 1) & 0xFF

    assert compute_header_checksum(rom) == expected
    assert rom[HEADER_CHECKSUM] == expected


def test_header_checksum_is_always_a_byte() -> None:
    assert 0 <= compute_header_checksum(build_rom()) <= 0xFF


def test_corrupting_the_title_invalidates_the_checksum() -> None:
    rom = bytearray(build_rom())
    rom[TITLE.start] ^= 0xFF

    cartridge = Cartridge.from_bytes(bytes(rom))

    assert not cartridge.header_checksum_valid


def test_global_checksum_excludes_its_own_bytes() -> None:
    rom = build_rom()
    expected = (sum(rom) - rom[0x014E] - rom[0x014F]) & 0xFFFF

    assert compute_global_checksum(rom) == expected


def test_global_checksum_is_stored_big_endian() -> None:
    rom = build_rom()
    header = parse_header(rom)

    assert header.global_checksum == (rom[0x014E] << 8) | rom[0x014F]


# --- Cartridge ------------------------------------------------------------


def test_valid_cartridge_reports_valid_checksums() -> None:
    cartridge = Cartridge.from_bytes(build_rom())

    assert cartridge.header_checksum_valid
    assert cartridge.global_checksum_valid
    assert cartridge.declared_size_matches_file


def test_invalid_header_checksum_is_reported_not_raised() -> None:
    """Parsing must still succeed so a corrupt ROM can be inspected."""
    cartridge = Cartridge.from_bytes(build_rom(valid_header_checksum=False))

    assert not cartridge.header_checksum_valid
    assert cartridge.header.title == "SMARIOWATERPOLO"


def test_declared_size_can_disagree_with_the_file() -> None:
    cartridge = Cartridge.from_bytes(build_rom(rom_size=0x01))

    assert cartridge.header.rom_size == 64 * 1024
    assert not cartridge.declared_size_matches_file


def test_from_path_reads_the_file(tmp_path: Path) -> None:
    rom_path = tmp_path / "synthetic.gb"
    rom_path.write_bytes(build_rom())

    cartridge = Cartridge.from_path(rom_path)

    assert cartridge.header.title == "SMARIOWATERPOLO"
    assert cartridge.header_checksum_valid


# --- optional: run against a real cartridge -----------


@pytest.mark.skipif(
    not os.environ.get("GB_TEST_ROM"), reason="set GB_TEST_ROM to a real .gb file"
)
def test_real_rom_has_a_valid_header_checksum() -> None:
    cartridge = Cartridge.from_path(Path(os.environ["GB_TEST_ROM"]))

    assert cartridge.header_checksum_valid
    assert cartridge.header.title
