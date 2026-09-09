"""CLI entry point: `python -m screen <rom>` opens a window and runs it."""

import argparse
from pathlib import Path

from gameboy.cartridge import Cartridge, InvalidCartridgeError
from gameboy.cpu import CPU, Registers
from gameboy.machine import FRAME_CYCLES
from gameboy.memory import Bus
from screen.loop import run
from screen.pygame_display import PygameDisplay


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="screen", description="Run a Game Boy ROM in a window."
    )
    parser.add_argument("rom", type=Path, help="path to a .gb file")
    parser.add_argument(
        "--scale", type=int, default=3, help="window size, in whole pixels per dot"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=FRAME_CYCLES * 4,
        help="T-cycles to spend on one frame before giving up on it",
    )
    args = parser.parse_args()

    try:
        cartridge = Cartridge.from_path(args.rom)
    except FileNotFoundError:
        print(f"screen: no such file: {args.rom}")
        return 1
    except InvalidCartridgeError as error:
        print(f"screen: {args.rom} is not a valid cartridge: {error}")
        return 1

    bus = Bus.post_boot(cartridge)
    # One CPU for the whole run. `run_frame` takes it rather than building its
    # own precisely so that this line happens once and not sixty times a second.
    cpu = CPU(bus, Registers.post_boot())
    # Homebrew and test ROMs often leave the header title blank.
    title = cartridge.header.title or args.rom.stem
    display = PygameDisplay(scale=args.scale, title=title)

    rate = run(display, cpu, bus, args.budget)

    # The live number is gone with the window, and 13B needs a before and an
    # after it can paste somewhere.
    print(f"{rate.per_second:.1f} frames per second")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
