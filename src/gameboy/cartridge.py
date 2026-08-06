from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Final, Self

ENTRY_POINT: Final = 0x0100
LOGO: Final = slice(0x0104, 0x0134)
TITLE: Final = slice(0x0134, 0x0143)
CGB_FLAG: Final = 0x0143
NEW_LIC_CODE: Final = slice(0x0144, 0x0146)
SGB_FLAG: Final = 0x0146
CARTRIDGE_TYPE: Final = 0x0147
ROM_SIZE: Final = 0x0148
RAM_SIZE: Final = 0x0149
DEST_CODE: Final = 0x014A
OLD_LIC_CODE: Final = 0x014B
ROM_VERSION: Final = 0x014C
HEADER_CHECKSUM: Final = 0x014D
GLOBAL_CHECKSUM: Final = slice(0x014E, 0x0150)

# Smallest file that still contains a complete header.
HEADER_END: Final = 0x0150

# The byte at ROM_SIZE is a shift, not a size: 32 KiB doubled that many times.
# https://gbdev.io/pandocs/The_Cartridge_Header.html#0148--rom-size
SMALLEST_ROM: Final = 32 * 1024

# RAM size needs a literal table, see:
# https://gbdev.io/pandocs/The_Cartridge_Header.html#0149--ram-size
# 0x01 was 2 KiB on some prototypes and is considered unused today.
RAM_SIZES: Final[dict[int, tuple[int, int]]] = {
    0x00: (0, 0),
    0x01: (0, 0),
    0x02: (8 * 1024, 1),
    0x03: (32 * 1024, 4),
    0x04: (128 * 1024, 16),
    0x05: (64 * 1024, 8),
}

SGB_ENABLED: Final = 0x03


class InvalidCartridgeError(Exception):
    """Raised when a file cannot be interpreted as a cartridge."""


class ColorFlagType(IntEnum):
    DMG = 0x00
    COLOR_ENHANCED = 0x80
    COLOR_ONLY = 0xC0


class CartridgeType(IntEnum):
    ROM_ONLY = 0x00
    MBC1 = 0x01
    MBC1_RAM = 0x02
    MBC1_RAM_BATTERY = 0x03
    MBC3_TIMER_BATTERY = 0x0F
    MBC3_TIMER_RAM_BATTERY = 0x10
    MBC3 = 0x11
    MBC3_RAM = 0x12
    MBC3_RAM_BATTERY = 0x13
    MBC5 = 0x19
    MBC5_RAM = 0x1A
    MBC5_RAM_BATTERY = 0x1B
    MBC5_RUMBLE = 0x1C
    MBC5_RUMBLE_RAM = 0x1D
    MBC5_RUMBLE_RAM_BATTERY = 0x1E


@dataclass(frozen=True, slots=True)
class Header:
    title: str
    cartridge_type: CartridgeType
    rom_size: int
    rom_banks: int
    ram_size: int
    ram_banks: int
    cgb_flag: ColorFlagType
    sgb_flag: bool
    destination: int
    version: int
    header_checksum: int
    global_checksum: int


def compute_header_checksum(rom: bytes) -> int:
    """Running subtraction over 0x0134-0x014C inclusive, truncated to 8 bits.

    The boot ROM verifies this and halts the console on a mismatch.
    """
    checksum = 0
    for address in range(TITLE.start, HEADER_CHECKSUM):
        checksum = (checksum - rom[address] - 1) & 0xFF

    return checksum


def compute_global_checksum(rom: bytes) -> int:
    """Sum of every byte except the two that store the result itself.

    For the sake of reporting only (not enforced anywhere).
    """
    stored = rom[GLOBAL_CHECKSUM.start] + rom[GLOBAL_CHECKSUM.start + 1]

    return (sum(rom) - stored) & 0xFFFF


def parse_header(rom: bytes) -> Header:
    if len(rom) < HEADER_END:
        raise InvalidCartridgeError(
            f"file is {len(rom)} bytes, needs at least {HEADER_END} to hold a header"
        )

    ram_size, ram_banks = RAM_SIZES.get(rom[RAM_SIZE], (0, 0))

    return Header(
        title=rom[TITLE].decode("ascii", errors="replace").rstrip("\x00").strip(),
        cartridge_type=CartridgeType(rom[CARTRIDGE_TYPE]),
        rom_size=SMALLEST_ROM << rom[ROM_SIZE],
        rom_banks=2 << rom[ROM_SIZE],
        ram_size=ram_size,
        ram_banks=ram_banks,
        cgb_flag=ColorFlagType(rom[CGB_FLAG]),
        sgb_flag=rom[SGB_FLAG] == SGB_ENABLED,
        destination=rom[DEST_CODE],
        version=rom[ROM_VERSION],
        header_checksum=rom[HEADER_CHECKSUM],
        global_checksum=int.from_bytes(rom[GLOBAL_CHECKSUM], "big"),
    )


@dataclass(frozen=True, slots=True)
class Cartridge:
    raw_bytes: bytes
    header: Header

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        return cls(raw_bytes=data, header=parse_header(data))

    @classmethod
    def from_path(cls, path: Path) -> Self:
        return cls.from_bytes(path.read_bytes())

    @property
    def header_checksum_valid(self) -> bool:
        return self.header.header_checksum == compute_header_checksum(self.raw_bytes)

    @property
    def global_checksum_valid(self) -> bool:
        return self.header.global_checksum == compute_global_checksum(self.raw_bytes)

    @property
    def declared_size_matches_file(self) -> bool:
        return self.header.rom_size == len(self.raw_bytes)
