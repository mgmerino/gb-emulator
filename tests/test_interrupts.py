import pytest
from conftest import CpuRunning

from gameboy.bits import get_bit
from gameboy.cpu import CPU
from gameboy.interrupts import Interrupt, pending
from gameboy.memory import Bus
from gameboy.memory_map import INTERRUPT_ENABLE, INTERRUPT_FLAG


def test_interrupt_table_vectors() -> None:
    assert Interrupt.VBLANK.vector == 0x40
    assert Interrupt.LCD_STAT.vector == 0x48
    assert Interrupt.TIMER.vector == 0x50
    assert Interrupt.SERIAL.vector == 0x58
    assert Interrupt.JOYPAD.vector == 0x60


@pytest.mark.parametrize(
    ("ie", "i_flag", "expected"),
    [
        (0b00000, 0b00000, None),  # Nothing
        (0b00100, 0b00000, None),  # Enabled, but it didn't happen
        (0b00000, 0b00001, None),  # It happened, but it was not enabled
        (0b11111111, 0b11100000, None),  # Noise, masked
        (0b10101, 0b00001, Interrupt.VBLANK),
        (0b10110, 0b00010, Interrupt.LCD_STAT),
        (0b11111, 0b10100, Interrupt.TIMER),  # priority over joypad
        (0b11111, 0b01000, Interrupt.SERIAL),
        (0b11111, 0b10000, Interrupt.JOYPAD),
    ],
)
def test_pending(bus: Bus, ie: int, i_flag: int, expected: Interrupt | None) -> None:
    bus.write(0xFFFF, ie)  # ie
    bus.write(0xFF0F, i_flag)  # if

    assert pending(bus) is expected


def _armed(cpu_running: CpuRunning, *program: int, ie: int, if_: int) -> CPU:
    """A CPU at 0x0100 with a stack, IME on, and both interrupt registers set."""
    cpu = cpu_running(*program)
    cpu.registers.sp = 0xFFFE
    cpu.ime = True
    cpu.bus.write(INTERRUPT_ENABLE, ie)
    cpu.bus.write(INTERRUPT_FLAG, if_)

    return cpu


def test_a_dispatch_jumps_to_the_vector_and_costs_twenty(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, ie=0x04, if_=0x04)

    assert cpu.step() == 20
    assert cpu.registers.pc == Interrupt.TIMER.vector


def test_a_dispatch_pushes_the_address_the_cpu_was_about_to_execute(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, ie=0x04, if_=0x04)

    cpu.step()

    assert cpu.registers.sp == 0xFFFC
    assert cpu.bus.read16(0xFFFC) == 0x0100


def test_a_dispatch_closes_the_master_flag(cpu_running: CpuRunning) -> None:
    cpu = _armed(cpu_running, ie=0x04, if_=0x04)

    cpu.step()

    assert cpu.ime is False


def test_a_dispatch_acknowledges_the_source_by_clearing_its_flag(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, ie=0x04, if_=0x04)

    cpu.step()

    assert get_bit(cpu.bus.read(INTERRUPT_FLAG), Interrupt.TIMER) is False


def test_a_dispatch_leaves_the_sources_it_did_not_serve_pending(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, ie=0x1F, if_=0x14)

    cpu.step()

    assert pending(cpu.bus) is Interrupt.JOYPAD


def test_a_dispatch_executes_no_instruction(cpu_running: CpuRunning) -> None:
    cpu = _armed(cpu_running, 0x3C, ie=0x04, if_=0x04)  # INC A

    cpu.step()

    assert cpu.registers.a == 0x00


def test_a_handler_runs_once_and_the_interrupted_program_resumes(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, 0x3C, ie=0x04, if_=0x04)  # INC A
    cpu.bus.write(Interrupt.TIMER.vector, 0x04)  # INC B
    cpu.bus.write(Interrupt.TIMER.vector + 1, 0xD9)  # RETI

    for _ in range(4):  # dispatch, INC B, RETI, INC A
        cpu.step()

    assert cpu.registers.b == 0x01
    assert cpu.registers.a == 0x01
    assert cpu.registers.pc == 0x0101
    assert cpu.registers.sp == 0xFFFE


def test_ei_is_promoted_by_a_taken_conditional_return(
    cpu_running: CpuRunning,
) -> None:
    cpu = cpu_running(0xFB, 0xC8)  # EI ; RET Z
    cpu.registers.sp = 0xFFFC
    cpu.registers.z_flag = True
    cpu.bus.write16(0xFFFC, 0x0200)

    cpu.step()
    assert cpu.ime is False

    cpu.step()

    assert cpu.registers.pc == 0x0200
    assert cpu.ime is True
    assert cpu.ime_pending is False


def test_halt_sets_the_halted_flag_and_costs_four_cycles(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, 0x76, ie=0x00, if_=0x00)  # HALT

    assert cpu.step() == 4
    assert cpu.halted is True


def test_a_halted_cpu_fetches_nothing_and_still_reports_time(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, 0x76, 0x3C, ie=0x00, if_=0x00)  # HALT ; INC A

    cpu.step()
    for _ in range(100):
        assert cpu.step() == 4

    assert cpu.registers.pc == 0x0101
    assert cpu.registers.a == 0x00


def test_a_source_the_program_did_not_enable_does_not_wake_the_cpu(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, 0x76, 0x3C, ie=0x00, if_=0x00)

    cpu.step()
    cpu.bus.write(INTERRUPT_FLAG, 0x04)  # the timer overflows, nobody cares

    for _ in range(100):
        cpu.step()

    assert cpu.halted is True
    assert cpu.registers.a == 0x00


def test_a_pending_source_wakes_the_cpu_and_dispatches_when_ime_is_set(
    cpu_running: CpuRunning,
) -> None:
    # IF stays clear while HALT runs: with a source already pending the CPU
    # would not halt at all, which is the HALT bug and not this test's subject.
    cpu = _armed(cpu_running, 0x76, 0x3C, ie=0x04, if_=0x00)

    cpu.step()
    cpu.bus.write(INTERRUPT_FLAG, 0x04)

    assert cpu.step() == 20
    assert cpu.halted is False
    assert cpu.registers.pc == Interrupt.TIMER.vector


def test_a_pending_source_wakes_the_cpu_without_dispatching_when_ime_is_clear(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, 0x76, 0x3C, ie=0x04, if_=0x00)  # HALT ; INC A
    cpu.ime = False

    cpu.step()
    cpu.bus.write(INTERRUPT_FLAG, 0x04)
    cpu.step()

    assert cpu.halted is False
    assert cpu.registers.a == 0x01
    assert cpu.registers.pc == 0x0102


def test_waking_leaves_the_source_pending_when_it_is_not_serviced(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, 0x76, 0x3C, ie=0x04, if_=0x00)
    cpu.ime = False

    cpu.step()
    cpu.bus.write(INTERRUPT_FLAG, 0x04)
    cpu.step()

    assert pending(cpu.bus) is Interrupt.TIMER


def test_stop_consumes_its_second_byte_and_costs_four_cycles(
    cpu_running: CpuRunning,
) -> None:
    cpu = _armed(cpu_running, 0x10, 0x00, ie=0x00, if_=0x00)  # STOP

    assert cpu.step() == 4
    assert cpu.registers.pc == 0x0102


def test_stop_does_not_execute_its_second_byte(cpu_running: CpuRunning) -> None:
    cpu = _armed(cpu_running, 0x10, 0x3C, ie=0x00, if_=0x00)  # STOP, then INC A

    cpu.step()

    assert cpu.registers.a == 0x00


def test_stop_leaves_the_cpu_asleep(cpu_running: CpuRunning) -> None:
    cpu = _armed(cpu_running, 0x10, 0x00, 0x3C, ie=0x00, if_=0x00)

    cpu.step()
    for _ in range(100):
        assert cpu.step() == 4

    assert cpu.halted is True
    assert cpu.registers.pc == 0x0102
    assert cpu.registers.a == 0x00


def test_a_stopped_cpu_wakes_like_a_halted_one(cpu_running: CpuRunning) -> None:
    # For now, we simply consume 1 byte after the instruction and behave like a HALT.
    # This test covers the stub.
    cpu = _armed(cpu_running, 0x10, 0x00, 0x3C, ie=0x04, if_=0x00)
    cpu.ime = False

    cpu.step()
    cpu.bus.write(INTERRUPT_FLAG, 0x04)
    cpu.step()

    assert cpu.halted is False
    assert cpu.registers.a == 0x01
