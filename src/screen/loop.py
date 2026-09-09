"""The loop a window drives, and the instrument that measures it.

No pygame here. Task 5 wants the loop tested against a fake display on a
checkout with no extra installed, and an import is enough to break that.
"""

import time
from collections import deque

from gameboy.cpu import CPU
from gameboy.machine import FRAME_CYCLES, run_frame
from gameboy.memory import Bus
from screen.display import Display

# How often the rate is reported. A number that changes sixty times a second is
# unreadable, and setting a window title asks the window manager for something.
REPORT_EVERY: float = 1.0


class FrameRate:
    """Frames per second, averaged over the last `window` seconds.

    A single frame's time swings with whatever the ROM is doing on that line,
    so one measurement is noise. What 13B needs is a number that holds still
    enough to compare a before and an after.

    The window is by age and not by count. `deque(maxlen=N)` would be less
    code, but N frames is a different amount of time at 9 fps than at 60, and
    the number this reports has to mean the same thing before and after an
    optimisation.
    """

    _window: float
    _ticks: deque[float]

    def __init__(self, window: float = REPORT_EVERY) -> None:
        self._window = window
        # A deque, not a list: appending on the right and dropping on the left
        # are both O(1) here, where `list.pop(0)` shifts every element along.
        self._ticks = deque()

    def tick(self) -> None:
        """Record that a frame just finished."""
        # `perf_counter` and not `time.time`: it is monotonic, so it cannot
        # jump backwards when the system clock is adjusted mid-measurement.
        now = time.perf_counter()

        self._ticks.append(now)
        self._forget_before(now - self._window)

    @property
    def per_second(self) -> float:
        """The rate over the window, or 0.0 before there is enough to divide.

        Reading this drops timestamps that have aged out, so a meter nobody has
        ticked in a while reports 0.0 rather than the last rate it saw.
        """
        self._forget_before(time.perf_counter() - self._window)

        # n timestamps are n-1 gaps. Dividing by n instead reads about 10% high
        # at 10 fps, and the error grows as the window empties.
        if len(self._ticks) < 2:
            return 0.0

        span = self._ticks[-1] - self._ticks[0]

        return (len(self._ticks) - 1) / span if span > 0 else 0.0

    def _forget_before(self, cutoff: float) -> None:
        while self._ticks and self._ticks[0] < cutoff:
            self._ticks.popleft()


def run(
    display: Display, cpu: CPU, bus: Bus, budget: int = FRAME_CYCLES * 4
) -> FrameRate:
    """Run frames into `display` until it says to stop. Returns the meter, so
    the caller can print a last number on the way out.

    Typed against the Protocol and not against `PygameDisplay`: this is the
    function task 5 drives with a fake that counts calls and stops after a few.
    """
    rate = FrameRate()
    reported_at = time.perf_counter()

    try:
        while not display.wants_to_close():
            # Present either way. A `False` here means the ROM has the LCD off,
            # which is a normal thing for it to do, and the last good frame is
            # what a real Game Boy would still be showing.
            if run_frame(cpu, bus, budget):
                rate.tick()

            display.present(bus.ppu.frame)

            now = time.perf_counter()
            if now - reported_at >= REPORT_EVERY:
                display.show_rate(rate.per_second)
                reported_at = now
    except KeyboardInterrupt:
        # Ctrl-C in the terminal that launched the window. Returning the meter
        # means the caller still gets to print its number.
        pass

    return rate
