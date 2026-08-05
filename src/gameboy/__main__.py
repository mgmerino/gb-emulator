"""CLI entry point: `python -m gameboy <rom>` prints a cartridge summary."""

import argparse
from pathlib import Path

from gameboy.cartridge import (
    Cartridge,
    InvalidCartridgeError,
    compute_global_checksum,
    compute_header_checksum,
)


def format_size(size: int) -> str:
    if size == 0:
        return "none"
    if size >= 1024 * 1024:
        return f"{size // (1024 * 1024)} MiB"
    return f"{size // 1024} KiB"


def describe(cartridge: Cartridge) -> str:
    header = cartridge.header
    computed_header = compute_header_checksum(cartridge.raw_bytes)
    computed_global = compute_global_checksum(cartridge.raw_bytes)

    ram = format_size(header.ram_size)
    if header.ram_banks:
        ram = f"{ram} ({header.ram_banks} banks)"

    kind = f"{header.cartridge_type.name} (0x{header.cartridge_type.value:02X})"
    rom = f"{format_size(header.rom_size)} ({header.rom_banks} banks)"
    destination = "Japan" if header.destination == 0x00 else "overseas"

    if cartridge.header_checksum_valid:
        header_sum = f"0x{header.header_checksum:02X}  valid"
    else:
        header_sum = (
            f"0x{header.header_checksum:02X}  INVALID "
            f"(computed 0x{computed_header:02X})"
        )

    global_sum = f"0x{header.global_checksum:04X}  (computed 0x{computed_global:04X})"

    lines = [
        f"Title:            {header.title}",
        f"Cartridge:        {kind}",
        f"ROM:              {rom}",
        f"RAM:              {ram}",
        f"CGB:              {header.cgb_flag.name}",
        f"SGB:              {'yes' if header.sgb_flag else 'no'}",
        f"Destination:      {destination}",
        f"Version:          {header.version}",
        f"Header checksum:  {header_sum}",
        f"Global checksum:  {global_sum}",
    ]

    if not cartridge.declared_size_matches_file:
        lines.append(
            f"Warning:          header declares {format_size(header.rom_size)} "
            f"but the file is {len(cartridge.raw_bytes)} bytes"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="gameboy", description="Inspect a Game Boy cartridge."
    )
    parser.add_argument("rom", type=Path, help="path to a .gb file")
    args = parser.parse_args()

    try:
        cartridge = Cartridge.from_path(args.rom)
    except FileNotFoundError:
        print(f"gameboy: no such file: {args.rom}")
        return 1
    except InvalidCartridgeError as error:
        print(f"gameboy: {args.rom} is not a valid cartridge: {error}")
        return 1

    print(describe(cartridge))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
