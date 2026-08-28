import pytest

from gameboy.memory_map import DIVIDER, TIMER_CONTROL, TIMER_COUNTER, TIMER_MODULO
from gameboy.timer import Timer


@pytest.fixture
def timer() -> Timer:
    return Timer()


def test_divider_is_the_top_byte_of_the_internal_counter(timer: Timer) -> None:
    timer.counter = 0x0A32

    assert timer.divider == 0x0A


def test_divider_increments_once_every_256_cycles(timer: Timer) -> None:
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


#
# --- The four registers, read and write
#


def test_writing_div_resets_it_whatever_the_value(timer: Timer) -> None:
    timer.counter = 0x0FA0
    timer.write(DIVIDER, 0xF0)

    assert timer.counter == 0


def test_writing_div_clears_the_low_half_of_the_counter_too(timer: Timer) -> None:
    # The low half has no address, so assert it through behaviour: leave the
    # counter just short of a DIV increment, write DIV, and check that the next
    # few cycles do not push it over.
    timer.counter = 0xEFFF
    timer.write(DIVIDER, 0xF0)
    timer.tick(16)

    assert timer.counter == 0x0010


@pytest.mark.parametrize(
    ("address", "value"),
    [(TIMER_COUNTER, 0x11), (TIMER_MODULO, 0x22)],
)
def test_tima_and_tma_round_trip(timer: Timer, address: int, value: int) -> None:
    timer.write(address, value)

    assert timer.read(address) == value


def test_the_registers_do_not_share_storage(timer: Timer) -> None:
    # A round trip through one address passes even if all three are one field.
    timer.write(TIMER_COUNTER, 0x11)
    timer.write(TIMER_MODULO, 0x22)
    timer.write(TIMER_CONTROL, 0x03)

    assert timer.read(TIMER_COUNTER) == 0x11
    assert timer.read(TIMER_MODULO) == 0x22


def test_tac_reads_its_unused_bits_as_one(timer: Timer) -> None:
    timer.write(TIMER_CONTROL, 0x7A)

    assert timer.read(TIMER_CONTROL) == 0xFA
