"""CLI entry point: `python -m gameboy <rom>` prints a cartridge summary."""

import argparse
from collections.abc import Iterator
from itertools import batched
from pathlib import Path

from gameboy.cartridge import (
    Cartridge,
    InvalidCartridgeError,
    compute_global_checksum,
    compute_header_checksum,
)
from gameboy.cpu import CPU, OPCODES, Registers, UnknownOpcodeError
from gameboy.memory import Bus, MemoryDevice

type Row = tuple[int, int, str]
BYTES_PER_ROW = 16
# 16 groups of two hex digits, 15 separators, plus the extra space at the gutter.
HEX_WIDTH = BYTES_PER_ROW * 3 - 1 + 1
# Widest mnemonic in the table today is "ADD A, (HL)".
NAME_WIDTH = 11


def format_size(size: int) -> str:
    if size == 0:
        return "none"
    if size >= 1024 * 1024:
        return f"{size // (1024 * 1024)} MiB"
    return f"{size // 1024} KiB"


def parse_address(text: str) -> int:
    return int(text, 0)  # base 0 means "infer from the prefix"


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


def printable(value: int) -> str:
    return chr(value) if 0x20 <= value < 0x7F else "."


def hex_field(values: list[int]) -> str:
    left = " ".join(f"{value:02X}" for value in values[:8])
    right = " ".join(f"{value:02X}" for value in values[8:])
    return f"{left}  {right}"


def dump(bus: MemoryDevice, start: int, length: int) -> str:
    lines = []

    for chunk in batched(range(start, start + length), BYTES_PER_ROW):
        row = [bus.read(address) for address in chunk]
        text = "".join(printable(value) for value in row)

        lines.append(f"{chunk[0]:04X}: {hex_field(row):<{HEX_WIDTH}}  {text}")

    return "\n".join(lines)


def trace_line(
    address: int, opcode: int, name: str, registers: Registers, cycles: int
) -> str:
    state = (
        f"A:{registers.a:02X} F:{registers.f:02X} "
        f"BC:{registers.bc:04X} DE:{registers.de:04X} "
        f"HL:{registers.hl:04X} SP:{registers.sp:04X}"
    )

    return f"{address:04X}  {opcode:02X}  {name:<{NAME_WIDTH}}  {state}  {cycles}"


def trace(bus: MemoryDevice, instructions: int) -> Iterator[str]:
    """Run the machine for `instructions` steps, yielding one line each."""
    cpu = CPU(bus, Registers.post_boot())

    for _ in range(instructions):
        # The address and the opcode have to be captured before stepping,
        # because it moves the pc. The register state and the cycle count only
        # exist after.
        address = cpu.registers.pc
        opcode = bus.read(address)

        cycles = cpu.step()

        # step() returned instead of raising, so the opcode is in the table by
        # definition. That is what makes `[...]` safe here where `step` needs
        # `.get`.
        yield trace_line(address, opcode, OPCODES[opcode].name, cpu.registers, cycles)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="gameboy", description="Inspect a Game Boy cartridge."
    )
    parser.add_argument("rom", type=Path, help="path to a .gb file")
    parser.add_argument("--dump", type=parse_address, default=None)
    parser.add_argument("--length", type=int, default=64)
    parser.add_argument("--trace", type=int, default=None)
    args = parser.parse_args()

    try:
        cartridge = Cartridge.from_path(args.rom)
    except FileNotFoundError:
        print(f"gameboy: no such file: {args.rom}")
        return 1
    except InvalidCartridgeError as error:
        print(f"gameboy: {args.rom} is not a valid cartridge: {error}")
        return 1

    if args.dump is not None:
        print(
            f"Dump from {args.dump:#06x} to "
            f"{args.dump + args.length:#06x} ({args.length} bytes)"
        )
        print("--- BEGIN ---")
        print(dump(Bus(cartridge), args.dump, args.length))
        print("--- END ---\n")
    elif args.trace is not None:
        try:
            for line in trace(Bus(cartridge), args.trace):
                print(line)
        except UnknownOpcodeError as error:
            # The expected stopping point, not a crash: report it the way the
            # other CLI errors are reported and leave the traceback out.
            print(f"gameboy: {error}")
            return 1
    else:
        print(describe(cartridge))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
