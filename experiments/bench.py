"""How fast does the emulator run, and does it still draw the same thing?

Step 13B judges every optimisation by those two questions, so this answers both
at once. It runs a ROM headless, with no window, so the number measures the
emulator and nothing else.

Run with:

    uv run python experiments/bench.py ~/games/TETRIS.gb
    uv run python experiments/bench.py ~/games/TETRIS.gb --profile

Sample run (Python 3.12.13, Tetris (World) Rev 1, before any optimisation):

    TETRIS  warmup 600  frame 600 sha256 4facb9a12a82
    runs      15.1   14.9   15.1  fps
    best      15.1 fps   25% of 59.73

Three invocations gave a best of 14.9, 15.1 and 16.2: the noise between
invocations is a fps or so, larger than between the runs inside one.

Four things to know when reading it:

1. The digest is taken right after the warm-up, before anything is timed. The
   timed runs go through as many frames as fit in the time, and that count is
   exactly what an optimisation changes. Frame 600 is frame 600 at any speed.
2. `hashlib`, not `hash()`. The built-in `hash()` of `bytes` is salted per
   process, so two runs print different values for the same frame.
3. The best run is reported, not the mean. Whatever disturbs a measurement, the
   rest of the machine being busy, only ever slows it down, so the fastest run
   is the least disturbed one.
4. `--profile` wraps one extra run in `cProfile`. Everything runs about three
   times slower under it, so it says where the time goes and never how much.
"""

import argparse
import cProfile
import hashlib
import pstats
import time
from pathlib import Path

from gameboy.cartridge import Cartridge
from gameboy.cpu import CPU, Registers
from gameboy.machine import CLOCK_HZ, FRAME_CYCLES, run_frame
from gameboy.memory import Bus

DMG_FPS = CLOCK_HZ / FRAME_CYCLES


def timed_run(cpu: CPU, bus: Bus, seconds: float) -> float:
    """Frames per second over one run of `seconds`."""
    start = time.perf_counter()
    frames = 0

    while time.perf_counter() - start < seconds:
        # A `False` is a frame the LCD did not draw. Counting it would credit
        # the emulator for time it spent with the screen off.
        if run_frame(cpu, bus):
            frames += 1

    # The last frame overshoots `seconds`, so divide by the time that passed.
    return frames / (time.perf_counter() - start)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure frames per second.")
    parser.add_argument("rom", type=Path, help="path to a .gb file")
    parser.add_argument(
        "--warmup", type=int, default=600, help="frames to run before measuring"
    )
    parser.add_argument(
        "--seconds", type=float, default=4.0, help="length of each timed run"
    )
    parser.add_argument("--runs", type=int, default=3, help="timed runs to take")
    parser.add_argument(
        "--profile", action="store_true", help="profile one more run and print it"
    )
    args = parser.parse_args()

    cartridge = Cartridge.from_path(args.rom)
    bus = Bus.post_boot(cartridge)
    cpu = CPU(bus, Registers.post_boot())

    for _ in range(args.warmup):
        run_frame(cpu, bus)

    digest = hashlib.sha256(bus.ppu.frame).hexdigest()[:12]
    title = cartridge.header.title or args.rom.stem
    print(f"{title}  warmup {args.warmup}  frame {args.warmup} sha256 {digest}")

    rates = [timed_run(cpu, bus, args.seconds) for _ in range(args.runs)]
    best = max(rates)

    print("runs   " + "".join(f"{rate:7.1f}" for rate in rates) + "  fps")
    print(f"best   {best:7.1f} fps   {best / DMG_FPS:.0%} of {DMG_FPS:.2f}")

    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        timed_run(cpu, bus, args.seconds)
        profiler.disable()

        stats = pstats.Stats(profiler)
        stats.sort_stats("cumulative").print_stats(25)
        stats.sort_stats("tottime").print_stats(15)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
