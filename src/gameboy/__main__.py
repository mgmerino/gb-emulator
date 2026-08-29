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
from gameboy.cpu import CPU, Registers, UnknownOpcodeError
from gameboy.encoding import Instruction
from gameboy.instructions import CB_OPCODES, OPCODES
from gameboy.memory import Bus, MemoryDevice
from gameboy.timer import Timer

type Row = tuple[int, int, str]
BYTES_PER_ROW = 16
# 16 groups of two hex digits, 15 separators, plus the extra space at the gutter.
HEX_WIDTH = BYTES_PER_ROW * 3 - 1 + 1
# Widest mnemonic in the table today is "LD HL, SP+e8". The widest CB one is
# "BIT 7, (HL)", one character shorter.
NAME_WIDTH = 12
# Two hex digits per byte and a separator: a prefixed opcode prints as "CB 7E".
OPCODE_WIDTH = 5


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


def decode(bus: MemoryDevice, address: int) -> tuple[Instruction, int]:
    opcode = bus.read(address)
    if opcode == 0xCB:
        opcode = bus.read(address + 1)
        instruction = CB_OPCODES[opcode]  # safe to use [] because runs after step
        size = 2
    else:
        instruction = OPCODES[opcode]
        size = 1

    return (instruction, size)


def opcode_bytes(bus: MemoryDevice, address: int, size: int) -> str:
    return " ".join(f"{bus.read(address + offset):02X}" for offset in range(size))


def trace_line(
    address: int, opcodes: str, name: str, registers: Registers, cycles: int
) -> str:
    state = (
        f"A:{registers.a:02X} F:{registers.f:02X} "
        f"BC:{registers.bc:04X} DE:{registers.de:04X} "
        f"HL:{registers.hl:04X} SP:{registers.sp:04X}"
    )

    return (
        f"{address:04X}  {opcodes:<{OPCODE_WIDTH}}  "
        f"{name:<{NAME_WIDTH}}  {state}  {cycles}"
    )


def trace_summary(instructions: int, cycles: int, reason: str) -> str:
    """One DMG frame is 70224 T-cycles, which is the yardstick this number is
    read against.
    """
    return f"--- {instructions} instructions, {cycles} T-cycles, {reason} ---"


def run(bus: Bus, instructions: int) -> Iterator[tuple[CPU, int, int]]:
    """Drive the machine, yielding the CPU, the address it fetched from, and
    what the step cost.

    Both CLI modes go through here, because two loops that tick differently is a
    bug nobody finds until the PPU is drawing.

    Typed against `Bus` and not `MemoryDevice`: the protocol describes what the
    CPU needs, which is four ways to move bytes. Driving the machine also means
    handing the elapsed time to the devices, and that is not the CPU's business
    — so it is this function, the one that assembles the machine, that has to
    know what it is holding.
    """
    cpu = CPU(bus, Registers.post_boot())

    for _ in range(instructions):
        # The address has to be captured before stepping, because it moves the
        # pc. The register state and the cycle count only exist after.
        address = cpu.registers.pc

        cycles = cpu.step()

        # The instruction has run; now everything else catches up by exactly the
        # time it took. This is the whole of "instruction-stepped" emulation.
        bus.tick(cycles)

        yield (cpu, address, cycles)


def trace(bus: Bus, instructions: int) -> Iterator[tuple[str, int]]:
    """Run the machine, yielding a formatted line and its cost.

    The caller sums the cycles rather than the generator tracking them: a
    generator that stops early through an exception cannot report a total, and
    the loop that consumes it can.
    """
    for cpu, address, cycles in run(bus, instructions):
        # step() returned instead of raising, so the opcode is in one of the two
        # tables by definition. That is what makes decode's `[...]` safe where
        # step itself needs `.get`.
        instruction, size = decode(bus, address)

        yield (
            trace_line(
                address,
                opcode_bytes(bus, address, size),
                instruction.name,
                cpu.registers,
                cycles,
            ),
            cycles,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="gameboy", description="Inspect a Game Boy cartridge."
    )
    parser.add_argument("rom", type=Path, help="path to a .gb file")
    parser.add_argument("--dump", type=parse_address, default=None)
    parser.add_argument("--length", type=int, default=64)
    parser.add_argument("--trace", type=int, default=None)
    parser.add_argument(
        "--run",
        type=int,
        default=None,
        help="run without per-instruction output, then print the serial log",
    )
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
        print(dump(Bus(cartridge, Timer()), args.dump, args.length))
        print("--- END ---\n")
    elif args.trace is not None:
        executed = 0
        total_cycles = 0
        reason = f"reached the {args.trace} instruction limit"
        exit_code = 0

        try:
            for line, cycles in trace(Bus(cartridge, Timer()), args.trace):
                print(line)
                executed += 1
                total_cycles += cycles
        except UnknownOpcodeError as error:
            # The expected stopping point, not a crash: report it the way the
            # other CLI errors are reported and leave the traceback out.
            reason = str(error)
            exit_code = 1

        print(trace_summary(executed, total_cycles, reason))
        return exit_code
    elif args.run is not None:
        bus = Bus(cartridge, Timer())
        executed = 0
        total_cycles = 0
        reason = f"reached the {args.run} instruction limit"
        exit_code = 0

        try:
            for _cpu, _address, cycles in run(bus, args.run):
                executed += 1
                total_cycles += cycles
        except UnknownOpcodeError as error:
            reason = str(error)
            exit_code = 1
        except KeyboardInterrupt:
            # A ROM that never finishes still has something to say.
            reason = "interrupted"

        if bus.serial.output:
            print("--- serial ---")
            print(bus.serial.text)

        print(trace_summary(executed, total_cycles, reason))
        return exit_code
    else:
        print(describe(cartridge))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
