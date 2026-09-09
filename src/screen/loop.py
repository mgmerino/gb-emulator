"""The loop a window drives, and the instrument that measures it.

No pygame here. Task 5 wants the loop tested against a fake display on a
checkout with no extra installed, and an import is enough to break that.
"""

from gameboy.cpu import CPU
from gameboy.machine import FRAME_CYCLES, run_frame
from gameboy.memory import Bus
from screen.display import Display


class FrameRate:
    """Frames per second, averaged over the last `window` seconds.

    A single frame's time swings with whatever the ROM is doing on that line,
    so one measurement is noise. What 13B needs is a number that holds still
    enough to compare a before and an after.
    """

    def __init__(self, window: float = 1.0) -> None:
        # HOLE 1 — what you keep.
        #
        # The rolling window is a queue of timestamps, one per frame, with
        # everything older than `window` dropped. `collections.deque` is the
        # right container: appending and popping from the left are both O(1),
        # unlike a list, whose `pop(0)` shifts everything.
        #
        # `maxlen` caps a deque by count, not by age, so it does not do the job
        # on its own. Decide whether you drop old entries yourself in `tick`,
        # or cap by count and accept that the window is "the last N frames"
        # rather than "the last second". Both are defensible; say which you
        # chose.
        raise NotImplementedError

    def tick(self) -> None:
        """Record that a frame just finished."""
        # HOLE 2 — take a timestamp and drop what has aged out.
        #
        # Use `time.perf_counter`. It is monotonic and has the highest
        # resolution Python offers, and unlike `time.time` it cannot jump when
        # the system clock is adjusted.
        raise NotImplementedError

    @property
    def per_second(self) -> float:
        # HOLE 3 — frames divided by the time they took.
        #
        # Careful with the denominator. `len(timestamps) / window` is wrong
        # until the window has filled: for the first half second it reports
        # half the real rate. The honest span is newest minus oldest.
        #
        # Decide what to return with zero or one timestamp, where there is no
        # span to divide by yet.
        raise NotImplementedError


def run(
    display: Display, cpu: CPU, bus: Bus, budget: int = FRAME_CYCLES * 4
) -> FrameRate:
    """Run frames into `display` until it says to stop. Returns the meter, so
    the caller can print a last number on the way out.

    Typed against the Protocol and not against `PygameDisplay`: this is the
    function task 5 drives with a fake that counts calls and stops after a few.
    """
    # HOLE 4 — the loop itself, which is the four lines from the step doc:
    #
    #     rate = FrameRate()
    #     while not display.wants_to_close():
    #         run_frame(cpu, bus, budget)
    #         display.present(bus.ppu.frame)
    #
    # Two things that sketch leaves out.
    #
    # `run_frame` returns whether a frame arrived, and you decided in task 3
    # that `False` means "the LCD is off, show the last one again". So present
    # either way. But `rate.tick()` must only count real frames, or the meter
    # reads high exactly when the emulator is doing nothing.
    #
    # HOLE 5 — where does the number go?
    #
    # The doc says the window title, and the title belongs to pygame, which
    # this module cannot import. So the rate has to reach the display through
    # the seam. Three options:
    #   a) add a method to the Protocol, e.g. `show_rate(self, fps: float)`
    #   b) give `present` a second parameter
    #   c) let the display own the meter and call `tick` itself
    #
    # (c) moves the instrument into the thing being measured and makes the fake
    # implement it too. Between (a) and (b): which one still reads right when
    # the next frontend is a terminal that has no title bar?
    #
    # Whatever you pick, do not set the caption every frame. It is a syscall to
    # the window manager and the number is unreadable at 60 Hz anyway. Once a
    # second is what a human can read; the meter already knows what a second
    # is.
    raise NotImplementedError
