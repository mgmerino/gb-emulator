import pytest

from gameboy.timer import Timer


@pytest.fixture
def timer() -> Timer:
    return Timer()


def test_div_is_the_top_byte_of_the_internal_counter(timer: Timer) -> None:
    timer.counter = 0x0A32

    assert timer.divider == 0x0A


def test_div_increments_once_every_256_cycles(timer: Timer) -> None:
    timer.counter = 0x0000
    previous_div = timer.divider

    timer.tick(256)

    assert timer.divider == (previous_div + 1)


def test_divider_does_not_increment_before_256_cycles_have_passed(timer: Timer) -> None:
    timer.counter = 0x0000
    previous_div = timer.divider

    timer.tick(252)

    assert timer.divider == previous_div


def test_divider_wraps_from_ff_to_00(timer: Timer) -> None:
    # The counter is 16 bits; the wrap must not raise or leak into bit 16.
    timer.counter = 0xFF00

    assert timer.divider == 0xFF

    timer.tick(256)

    assert timer.divider == 0x00


def test_divider_keeps_counting_with_the_timer_disabled(timer: Timer) -> None:
    timer.tac = 0x00  # off
    timer.counter = 0x0F00

    assert timer.divider == 0x0F

    timer.tick(256)

    assert timer.divider == 0x10
