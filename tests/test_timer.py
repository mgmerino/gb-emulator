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


#
# --- tick and the four rates
#


@pytest.mark.parametrize(
    ("tac", "expected_tima"),
    [
        # Same 1024 cycles for every row, so the four rates can be compared:
        # what changes is which bit of the counter is watched.
        (0b100, 1),  # 4096 Hz, bit 9
        (0b101, 64),  # 262144 Hz, bit 3
        (0b110, 16),  # 65536 Hz, bit 5
        (0b111, 4),  # 16384 Hz, bit 7
    ],
)
def test_each_tac_rate_ticks_tima_at_its_documented_period(
    timer: Timer, tac: int, expected_tima: int
) -> None:
    timer.tac = tac

    _ = timer.tick(1024)

    assert timer.tima == expected_tima


def test_a_disabled_tac_never_ticks_tima(timer: Timer) -> None:
    timer.tac = 0b001  # the fastest rate selected, but bit 2 is clear

    _ = timer.tick(4096)

    assert timer.tima == 0


def test_tima_does_not_tick_before_a_full_period_has_passed(timer: Timer) -> None:
    timer.tac = 0b101  # one falling edge every 16 cycles

    _ = timer.tick(12)

    assert timer.tima == 0

    _ = timer.tick(4)

    assert timer.tima == 1


def test_tick_advances_in_steps_small_enough_to_catch_every_edge() -> None:
    # Ten periods of 16 cycles, spent in one lump and in ten pieces. A tick that
    # adds the cycles in a single step samples neither end of eight of the edges
    # and reports zero.
    in_one_go = Timer(tac=0b101)
    in_pieces = Timer(tac=0b101)

    _ = in_one_go.tick(160)
    for _ in range(10):
        in_pieces.tick(16)

    assert in_one_go.tima == in_pieces.tima == 10


#
# --- Overflow
#


def test_tima_overflow_reloads_from_tma_and_not_from_zero(timer: Timer) -> None:
    timer.tac = 0b101
    timer.tima = 0xFF
    timer.tma = 0x30

    _ = timer.tick(16)

    assert timer.tima == 0x30


def test_tima_overflow_reports_itself_to_the_caller(timer: Timer) -> None:
    timer.tac = 0b101
    timer.tima = 0xFF

    assert timer.tick(16) is True


def test_a_tick_that_does_not_overflow_reports_nothing(timer: Timer) -> None:
    timer.tac = 0b101

    assert timer.tick(16) is False
    assert timer.tima == 1
