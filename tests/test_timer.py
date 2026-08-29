import pytest

from gameboy.bits import get_bit
from gameboy.cartridge import Cartridge
from gameboy.cpu import CPU, Registers
from gameboy.interrupts import Interrupt
from gameboy.memory import Bus
from gameboy.memory_map import (
    DIVIDER,
    INTERRUPT_FLAG,
    TIMER_CONTROL,
    TIMER_COUNTER,
    TIMER_MODULO,
)
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


#
# --- The three consequences of the falling-edge rule
#
# `timer.tick(N)` is how each of these arms the detector: it leaves the counter
# where the test wants it *and* leaves `last_and` true, which is the half that a
# direct assignment to `counter` would skip. Without it there is no 1 to fall
# from and every one of these tests passes for the wrong reason.


def test_writing_div_ticks_tima_when_the_watched_bit_was_set(timer: Timer) -> None:
    timer.tac = 0b100  # 4096 Hz, watches bit 9
    timer.tick(0x200)  # bit 9 goes up on this last sample

    assert timer.tima == 0

    timer.write(DIVIDER, 0x00)

    assert timer.tima == 1


def test_writing_div_does_not_tick_tima_when_the_watched_bit_was_clear(
    timer: Timer,
) -> None:
    timer.tac = 0b100
    timer.tick(0x100)  # bit 9 still down

    timer.write(DIVIDER, 0x00)

    assert timer.tima == 0


def test_changing_the_tac_rate_can_tick_tima(timer: Timer) -> None:
    timer.tac = 0b100
    timer.tick(0x200)  # bit 9 up, bit 3 down

    timer.write(TIMER_CONTROL, 0b101)  # now watching bit 3

    assert timer.tima == 1


def test_changing_the_tac_rate_does_not_tick_tima_when_the_new_bit_is_set_too(
    timer: Timer,
) -> None:
    timer.tac = 0b100
    timer.tick(0x208)  # bit 9 and bit 3 both up

    timer.write(TIMER_CONTROL, 0b101)

    assert timer.tima == 0


def test_disabling_the_timer_ticks_tima_one_last_time(timer: Timer) -> None:
    timer.tac = 0b100
    timer.tick(0x200)

    timer.write(TIMER_CONTROL, 0b000)  # the switch opens, the gate output drops

    assert timer.tima == 1


def test_disabling_the_timer_does_not_tick_tima_when_the_watched_bit_was_clear(
    timer: Timer,
) -> None:
    timer.tac = 0b100
    timer.tick(0x100)

    timer.write(TIMER_CONTROL, 0b000)

    assert timer.tima == 0


def test_writing_tima_or_tma_never_touches_the_gate(timer: Timer) -> None:
    timer.tac = 0b100
    timer.tick(0x200)

    timer.write(TIMER_COUNTER, 0x40)
    timer.write(TIMER_MODULO, 0x40)

    assert timer.tima == 0x40  # what was written, not 0x41


def test_an_overflow_caused_by_a_write_is_reported(timer: Timer) -> None:
    timer.tac = 0b100
    timer.tima = 0xFF
    timer.tma = 0x30
    timer.tick(0x200)

    assert timer.write(DIVIDER, 0x00) is True
    assert timer.tima == 0x30


def test_an_overflow_is_reported_even_when_it_is_not_the_last_edge(
    timer: Timer,
) -> None:
    # 24 cycles is six samples at 262144 Hz and the edge lands on the fourth.
    # A tick that assigns its result instead of accumulating it loses the report.
    timer.tac = 0b101
    timer.tima = 0xFF
    timer.tma = 0x30

    assert timer.tick(24) is True
    assert timer.tima == 0x30


#
# --- The bus seam: an overflow has to reach IF
#


def _timer_interrupt_requested(bus: Bus) -> bool:
    return get_bit(bus.read(INTERRUPT_FLAG), Interrupt.TIMER)


def test_the_bus_hands_elapsed_time_to_the_timer(bus: Bus) -> None:
    bus.tick(256)

    assert bus.read(DIVIDER) == 0x01


def test_an_overflow_during_a_tick_requests_the_timer_interrupt(bus: Bus) -> None:
    bus.write(TIMER_CONTROL, 0b101)
    bus.write(TIMER_COUNTER, 0xFF)

    assert not _timer_interrupt_requested(bus)

    bus.tick(16)

    assert _timer_interrupt_requested(bus)


def test_a_tick_without_an_overflow_requests_nothing(bus: Bus) -> None:
    bus.write(TIMER_CONTROL, 0b101)

    bus.tick(16)

    assert bus.timer.tima == 1
    assert not _timer_interrupt_requested(bus)


def test_an_overflow_caused_by_a_write_also_requests_the_interrupt(bus: Bus) -> None:
    bus.write(TIMER_CONTROL, 0b100)  # 4096 Hz, watches bit 9
    bus.write(TIMER_COUNTER, 0xFF)
    bus.tick(0x200)  # arms the detector with the watched bit high

    assert not _timer_interrupt_requested(bus)

    bus.write(DIVIDER, 0x00)

    assert _timer_interrupt_requested(bus)


def test_a_halted_cpu_is_woken_by_the_timer_and_runs_its_handler() -> None:
    """The payoff of step 09: nothing here writes IF.

    Every interrupt test before this one played the part of the hardware by
    setting 0xFF0F itself. This one arms the timer the way a ROM does, halts,
    and waits for time to pass.
    """
    program = [
        0x3E,
        0x04,  # LD A, 0x04
        0xE0,
        0xFF,  # LDH (0xFF), A   -> IE = the timer interrupt only
        0x3E,
        0xFF,  # LD A, 0xFF
        0xE0,
        0x05,  # LDH (0x05), A   -> TIMA, one edge short of overflowing
        0x3E,
        0x05,  # LD A, 0x05
        0xE0,
        0x07,  # LDH (0x07), A   -> TAC = enabled, 262144 Hz
        0xFB,  # EI
        0x76,  # HALT
        0x18,
        0xFE,  # JR -2           -> spin once we are back
    ]
    handler = [0x04, 0xD9]  # INC B ; RETI

    image = bytearray(0x8000)
    image[0x0050 : 0x0050 + len(handler)] = bytes(handler)
    image[0x0100 : 0x0100 + len(program)] = bytes(program)

    bus = Bus(Cartridge.from_bytes(bytes(image)), Timer())
    cpu = CPU(bus, Registers.post_boot())

    for _ in range(100):  # bounded: a halted CPU with nothing pending never wakes
        bus.tick(cpu.step())

    assert cpu.registers.b == 1  # the handler ran, exactly once
    assert cpu.halted is False
    assert cpu.registers.sp == 0xFFFE  # RETI put the stack back
    assert cpu.registers.pc == 0x010E  # spinning on the JR after the HALT
