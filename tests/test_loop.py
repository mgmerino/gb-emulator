"""The frontend loop and its instrument, both without pygame."""

import pytest

from gameboy.cartridge import Cartridge
from gameboy.cpu import CPU, Registers
from gameboy.joypad import Button
from gameboy.memory import Bus
from gameboy.ppu import PPU, SCREEN_HEIGHT, SCREEN_WIDTH
from gameboy.timer import Timer
from screen.loop import FRAME_PERIOD, REPORT_EVERY, FrameRate, Pacer, run

NOTHING: frozenset[Button] = frozenset()


class Clock:
    """A stand-in for `time.perf_counter` that only moves when told to."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeDisplay:
    """A `Display` that counts what it was asked to do and then gives up.

    No inheritance, like `FakeCartridge`: having the four methods is the whole
    contract.
    """

    def __init__(
        self,
        frames: int,
        clock: Clock | None = None,
        step: float = 0.0,
        buttons: frozenset[Button] = NOTHING,
    ):
        self.remaining = frames
        self.presented = 0
        self.last_frame: memoryview | None = None
        self.rates: list[float] = []
        self._clock = clock
        self._step = step
        self._buttons = buttons

    def present(self, frame: memoryview) -> None:
        self.presented += 1
        self.last_frame = frame

    def wants_to_close(self) -> bool:
        if self._clock is not None:
            self._clock.advance(self._step)

        if self.remaining == 0:
            return True

        self.remaining -= 1

        return False

    def show_rate(self, rate: float) -> None:
        self.rates.append(rate)

    def held(self) -> frozenset[Button]:
        return self._buttons


@pytest.fixture
def spinning() -> Cartridge:
    image = bytearray(0x8000)
    image[0x0100:0x0103] = bytes((0xC3, 0x00, 0x01))  # JP 0x0100

    return Cartridge.from_bytes(bytes(image))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr("time.perf_counter", clock)

    return clock


class Sleep:
    """A stand-in for `time.sleep` that moves the fake clock instead of waiting,
    and remembers what it was asked for.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self._clock.advance(seconds)


@pytest.fixture
def sleep(monkeypatch: pytest.MonkeyPatch, clock: Clock) -> Sleep:
    sleep = Sleep(clock)
    monkeypatch.setattr("time.sleep", sleep)

    return sleep


def machine(cartridge: Cartridge, *, lcd_on: bool) -> tuple[CPU, Bus]:
    bus = Bus.post_boot(cartridge) if lcd_on else Bus(cartridge, Timer(), PPU())

    return CPU(bus, Registers.post_boot()), bus


def test_the_loop_presents_one_frame_per_run_frame(spinning: Cartridge) -> None:
    cpu, bus = machine(spinning, lcd_on=True)
    display = FakeDisplay(frames=3)

    run(display, cpu, bus)

    assert display.presented == 3
    assert bus.ppu.frames == 3


def test_the_seam_carries_a_whole_framebuffer(spinning: Cartridge) -> None:
    cpu, bus = machine(spinning, lcd_on=True)
    display = FakeDisplay(frames=1)

    run(display, cpu, bus)

    assert display.last_frame is not None
    assert len(display.last_frame) == SCREEN_WIDTH * SCREEN_HEIGHT == 23040
    assert display.last_frame.readonly


def test_the_loop_keeps_presenting_while_the_lcd_is_off(spinning: Cartridge) -> None:
    """The last good frame is what real hardware would still be showing, and a
    window that stops presenting is a window that stops answering the desktop.
    """
    cpu, bus = machine(spinning, lcd_on=False)
    display = FakeDisplay(frames=3)

    rate = run(display, cpu, bus, budget=1_000)

    assert display.presented == 3
    assert bus.ppu.frames == 0
    assert rate.per_second == 0.0  # nothing was drawn, so nothing is counted


def test_the_rate_is_reported_about_once_a_second(
    spinning: Cartridge, clock: Clock
) -> None:
    cpu, bus = machine(spinning, lcd_on=True)
    display = FakeDisplay(frames=4, clock=clock, step=REPORT_EVERY / 2)

    run(display, cpu, bus)

    # Five calls to `wants_to_close` at half a second each is 2.5 seconds.
    assert len(display.rates) == 2


def test_the_rate_is_not_reported_every_frame(spinning: Cartridge) -> None:
    cpu, bus = machine(spinning, lcd_on=True)
    display = FakeDisplay(frames=3)

    run(display, cpu, bus)

    assert display.rates == []


def test_a_fresh_meter_reads_zero(clock: Clock) -> None:
    assert FrameRate().per_second == 0.0


def test_one_frame_is_not_enough_to_divide(clock: Clock) -> None:
    rate = FrameRate()
    rate.tick()

    assert rate.per_second == 0.0


def test_ten_frames_a_tenth_of_a_second_apart(clock: Clock) -> None:
    rate = FrameRate(window=2.0)

    for _ in range(10):
        rate.tick()
        clock.advance(0.1)

    # Ten timestamps span nine gaps of 0.1s. Dividing by ten instead of nine
    # would read 11.1.
    assert rate.per_second == pytest.approx(10.0)


def test_frames_older_than_the_window_are_forgotten(clock: Clock) -> None:
    rate = FrameRate(window=1.0)

    for _ in range(10):
        rate.tick()
        clock.advance(0.1)

    clock.advance(5.0)

    assert rate.per_second == 0.0


def test_the_window_slides(clock: Clock) -> None:
    """Frames arrive at 100 fps for half a second, then at 10 fps."""
    rate = FrameRate(window=1.0)

    for _ in range(50):
        rate.tick()
        clock.advance(0.01)

    for _ in range(5):
        rate.tick()
        clock.advance(0.1)

    # The window now holds the tail of the fast run and all of the slow one.
    assert 10.0 < rate.per_second < 100.0


def test_the_held_buttons_reach_the_bus(spinning: Cartridge) -> None:
    cpu, bus = machine(spinning, lcd_on=True)
    display = FakeDisplay(frames=1, buttons=frozenset({Button.START}))

    run(display, cpu, bus)

    assert bus.joypad.held == frozenset({Button.START})


def test_the_first_frame_is_not_held_back(clock: Clock, sleep: Sleep) -> None:
    Pacer().wait()

    assert sleep.calls == []


def test_a_short_frame_waits_out_the_rest_of_its_period(
    clock: Clock, sleep: Sleep
) -> None:
    pacer = Pacer()
    pacer.wait()

    clock.advance(0.005)
    pacer.wait()

    assert sleep.calls == [pytest.approx(FRAME_PERIOD - 0.005)]


def test_a_frame_that_overruns_does_not_wait(clock: Clock, sleep: Sleep) -> None:
    pacer = Pacer()
    pacer.wait()

    clock.advance(FRAME_PERIOD * 2)
    pacer.wait()

    assert sleep.calls == []


def test_after_an_overrun_the_next_deadline_counts_from_now(
    clock: Clock, sleep: Sleep
) -> None:
    pacer = Pacer()
    pacer.wait()
    clock.advance(FRAME_PERIOD * 2)
    pacer.wait()

    clock.advance(0.005)
    pacer.wait()

    # Counting from the missed deadline would find this frame late too, and not
    # wait at all: the start of a burst.
    assert sleep.calls == [pytest.approx(FRAME_PERIOD - 0.005)]


def test_deadlines_do_not_drift_when_sleep_oversleeps(clock: Clock) -> None:
    """Each sleep wakes 1 ms late. The deadlines must still land a whole number
    of periods after the first one, rather than a millisecond later each frame.
    """
    pacer = Pacer()
    pacer.wait()
    start = clock.now

    def late_sleep(seconds: float) -> None:
        clock.advance(seconds + 0.001)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("time.sleep", late_sleep)

        for _ in range(10):
            pacer.wait()

    # Ten sleeps woke 1 ms late each, yet only the last one's lateness remains.
    assert clock.now - start == pytest.approx(10 * FRAME_PERIOD + 0.001)


def test_the_loop_waits_once_per_frame_when_paced(
    spinning: Cartridge, clock: Clock, sleep: Sleep
) -> None:
    cpu, bus = machine(spinning, lcd_on=True)
    display = FakeDisplay(frames=3)

    run(display, cpu, bus, pacer=Pacer())

    # The first frame sets the first deadline, so three frames wait twice.
    assert len(sleep.calls) == 2


def test_the_loop_never_waits_unpaced(
    spinning: Cartridge, clock: Clock, sleep: Sleep
) -> None:
    cpu, bus = machine(spinning, lcd_on=True)
    display = FakeDisplay(frames=3)

    run(display, cpu, bus)

    assert sleep.calls == []
