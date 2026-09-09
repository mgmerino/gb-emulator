"""CLI entry point: `python -m screen <rom>` opens a window and runs it."""

import argparse
from pathlib import Path

from gameboy.cartridge import Cartridge, InvalidCartridgeError
from gameboy.cpu import CPU, Registers
from gameboy.machine import FRAME_CYCLES
from gameboy.memory import Bus
from screen.pygame_display import PygameDisplay
from screen.loop import run


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

    # HOLE 6 — load the cartridge.
    #
    # `gameboy/__main__.py` already does this, including the two failures worth
    # catching by hand: `FileNotFoundError` and `InvalidCartridgeError`. Copy
    # the shape, print with this prog's name, return 1. Six duplicated lines is
    # cheaper than a shared helper that both CLIs have to agree on, but if you
    # disagree, that is a fair place to extract one.

    # HOLE 7 — assemble the machine and hand it to the loop.
    #
    # `Bus.post_boot(cartridge)` and one CPU, built here and alive for the
    # whole run. That is the object `run_frame` refuses to build for itself.
    #
    # Then the display, then `run(...)`, then the last number: the doc wants it
    # printed on exit as well as shown live, because 13B needs a before and an
    # after to paste somewhere.

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
