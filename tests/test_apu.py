import pytest

from gameboy.apu import APU, MASKS
from gameboy.cartridge import Cartridge
from gameboy.memory import Bus

NR10 = 0xFF10
NR11 = 0xFF11
NR21 = 0xFF16
NR22 = 0xFF17
NR23 = 0xFF18
NR24 = 0xFF19
NR50 = 0xFF24
NR51 = 0xFF25
NR52 = 0xFF26
WAVE_START = 0xFF30
WAVE_END = 0xFF3F

POWER_ON = 0x80


@pytest.fixture
def apu() -> APU:
    # A fresh APU has NR52 = 0, which is powered off and ignores writes.
    apu = APU()
    apu.write(NR52, POWER_ON)
    return apu


# --- read masks ---


def test_write_only_length_bits_read_as_one(apu: APU) -> None:
    apu.write(NR21, 0x80)

    assert apu.read(NR21) == 0xBF


@pytest.mark.parametrize("value", [0x00, 0x42, 0xFF])
def test_period_low_always_reads_ff(apu: APU, value: int) -> None:
    apu.write(NR23, value)

    assert apu.read(NR23) == 0xFF


@pytest.mark.parametrize("address", [0xFF15, 0xFF1F, 0xFF27, 0xFF2F], ids=hex)
def test_unused_addresses_read_ff(apu: APU, address: int) -> None:
    apu.write(address, 0x00)

    assert apu.read(address) == 0xFF


@pytest.mark.parametrize("address", range(NR10, WAVE_START), ids=hex)
def test_reading_zero_gives_the_mask(apu: APU, address: int) -> None:
    apu.write(address, 0x00)

    assert apu.read(address) == MASKS[address - NR10]


def test_fully_readable_register_reads_back_as_written(apu: APU) -> None:
    apu.write(NR22, 0xC3)

    assert apu.read(NR22) == 0xC3


# --- wave RAM ---


@pytest.mark.parametrize("address", [WAVE_START, 0xFF37, WAVE_END], ids=hex)
def test_wave_ram_reads_back_as_written(apu: APU, address: int) -> None:
    apu.write(address, 0x5A)

    assert apu.read(address) == 0x5A


def test_wave_ram_does_not_touch_the_registers(apu: APU) -> None:
    apu.write(WAVE_START, 0xAB)

    assert apu.read(NR10) == MASKS[0]


# --- NR52 power ---


def test_channel_status_bits_ignore_writes(apu: APU) -> None:
    apu.write(NR52, 0x8F)

    assert apu.read(NR52) == 0xF0


def test_power_off_clears_the_registers(apu: APU) -> None:
    apu.write(NR50, 0x77)
    apu.write(NR22, 0xC3)

    apu.write(NR52, 0x00)
    apu.write(NR52, POWER_ON)

    assert apu.read(NR50) == 0x00
    assert apu.read(NR22) == 0x00


def test_power_off_reads_nr52_as_its_mask(apu: APU) -> None:
    apu.write(NR52, 0x00)

    assert apu.read(NR52) == 0x70


def test_writes_are_ignored_while_powered_off(apu: APU) -> None:
    apu.write(NR52, 0x00)

    apu.write(NR22, 0xC3)

    assert apu.read(NR22) == 0x00


def test_power_off_keeps_wave_ram(apu: APU) -> None:
    apu.write(WAVE_START, 0x12)

    apu.write(NR52, 0x00)

    assert apu.read(WAVE_START) == 0x12


def test_wave_ram_is_writable_while_powered_off(apu: APU) -> None:
    apu.write(NR52, 0x00)

    apu.write(WAVE_START, 0x34)

    assert apu.read(WAVE_START) == 0x34


def test_nr52_is_writable_while_powered_off() -> None:
    apu = APU()

    apu.write(NR52, POWER_ON)

    assert apu.read(NR52) == 0xF0


# --- post-boot ---


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (NR10, 0x80),
        (NR11, 0xBF),
        (NR50, 0x77),
        (NR51, 0xF3),
        # The boot ROM leaves channel 1 on, but channels do not exist until 17C.
        (NR52, 0xF0),
    ],
)
def test_post_boot_values(address: int, expected: int) -> None:
    assert APU.post_boot().read(address) == expected


# --- bus routing ---


def test_bus_routes_sound_registers_to_the_apu(bus: Bus) -> None:
    bus.write(NR52, POWER_ON)
    bus.write(NR21, 0x80)

    assert bus.read(NR21) == 0xBF


def test_bus_routes_wave_ram_to_the_apu(bus: Bus) -> None:
    bus.write(WAVE_END, 0x9C)

    assert bus.read(WAVE_END) == 0x9C


def test_bus_post_boot_includes_the_apu(cartridge: Cartridge) -> None:
    assert Bus.post_boot(cartridge).read(NR50) == 0x77


# --- channel 2: trigger and DAC ---

TRIGGER = 0x80
DAC_ON = 0xF0  # volume 15, down, pace 0
DUTY_50 = 0x80  # NR21 bits 7-6 = 2


def set_period(apu: APU, period: int, *, trigger: bool = False) -> None:
    apu.write(NR23, period & 0xFF)
    apu.write(NR24, (TRIGGER if trigger else 0) | period >> 8)


@pytest.fixture
def playing(apu: APU) -> APU:
    """Channel 2 just triggered: duty 2, volume 15, period 1750."""
    apu.write(NR21, DUTY_50)
    apu.write(NR22, DAC_ON)
    set_period(apu, 1750, trigger=True)
    return apu


def test_trigger_turns_the_channel_on(playing: APU) -> None:
    assert playing.channel2.enabled
    assert playing.read(NR52) == 0xF2


def test_nr24_without_bit_7_does_not_trigger(apu: APU) -> None:
    apu.write(NR22, DAC_ON)

    set_period(apu, 1750)

    assert not apu.channel2.enabled


def test_trigger_with_the_dac_off_leaves_the_channel_off(apu: APU) -> None:
    apu.write(NR22, 0x01)

    set_period(apu, 1750, trigger=True)

    assert not apu.channel2.enabled
    assert apu.read(NR52) == 0xF0


def test_volume_zero_going_up_keeps_the_dac_on(apu: APU) -> None:
    apu.write(NR22, 0x08)

    set_period(apu, 1750, trigger=True)

    assert apu.channel2.enabled


def test_turning_the_dac_off_turns_the_channel_off(playing: APU) -> None:
    playing.write(NR22, 0x00)

    assert not playing.channel2.enabled


def test_turning_the_dac_back_on_does_not_restart_the_channel(playing: APU) -> None:
    playing.write(NR22, 0x00)

    playing.write(NR22, DAC_ON)

    assert not playing.channel2.enabled


def test_trigger_loads_the_initial_volume(apu: APU) -> None:
    apu.write(NR22, 0xC3)

    set_period(apu, 1750, trigger=True)

    assert apu.channel2.volume == 12


# --- channel 2: the period divider ---


def test_one_duty_step_takes_1192_cycles_at_period_1750(playing: APU) -> None:
    # 2048 - 1750 = 298 ticks of 4 T-cycles.
    playing.tick(1188)
    assert playing.channel2.duty_step == 0

    playing.tick(4)
    assert playing.channel2.duty_step == 1


def test_a_full_wave_takes_9536_cycles_at_period_1750(playing: APU) -> None:
    playing.tick(9532)
    assert playing.channel2.duty_step == 7

    playing.tick(4)
    assert playing.channel2.duty_step == 0


def test_one_tick_can_cross_several_steps(apu: APU) -> None:
    apu.write(NR22, DAC_ON)
    set_period(apu, 2047, trigger=True)

    apu.tick(24)

    assert apu.channel2.duty_step == 6


def test_a_new_period_waits_for_the_next_reload(playing: APU) -> None:
    set_period(playing, 2047)

    playing.tick(1188)
    assert playing.channel2.duty_step == 0

    playing.tick(4)
    playing.tick(4)
    assert playing.channel2.duty_step == 2


def test_trigger_does_not_restart_the_duty_step(playing: APU) -> None:
    playing.tick(3 * 1192)

    set_period(playing, 1750, trigger=True)

    assert playing.channel2.duty_step == 3


def test_trigger_restarts_the_divider(playing: APU) -> None:
    playing.tick(1000)

    set_period(playing, 1750, trigger=True)
    playing.tick(1188)

    assert playing.channel2.duty_step == 0


# --- channel 2: output ---


@pytest.mark.parametrize(
    ("step", "expected"),
    # Duty 2 is 1, 0, 0, 0, 0, 1, 1, 1, at volume 15.
    [(0, 15), (1, 0), (4, 0), (5, 15), (7, 15)],
)
def test_output_follows_the_duty_pattern(
    playing: APU, step: int, expected: int
) -> None:
    playing.tick(step * 1192)

    assert playing.channel2_output == expected


def test_a_duty_change_applies_at_once(playing: APU) -> None:
    playing.tick(1192)
    assert playing.channel2_output == 0

    playing.write(NR21, 0xC0)  # duty 3: 0, 1, 1, 1, 1, 1, 1, 0

    assert playing.channel2_output == 15


def test_output_is_zero_with_the_channel_off(playing: APU) -> None:
    playing.write(NR22, 0x00)

    assert playing.channel2_output == 0


# --- channel 2: power off ---


def test_power_off_stops_channel_2(playing: APU) -> None:
    playing.tick(3 * 1192)

    playing.write(NR52, 0x00)

    assert not playing.channel2.enabled
    assert playing.channel2.duty_step == 0
    assert playing.read(NR52) == 0x70


# --- channel 2: on the bus ---


def test_bus_tick_drives_the_apu(bus: Bus) -> None:
    bus.write(NR52, POWER_ON)
    bus.write(NR22, DAC_ON)
    bus.write(NR23, 1750 & 0xFF)
    bus.write(NR24, TRIGGER | 1750 >> 8)

    bus.tick(1192)

    assert bus.apu.channel2.duty_step == 1


# --- frame sequencer ---

LENGTH_ENABLE = 0x40  # NR24 bit 6


def frame_steps(apu: APU, count: int) -> None:
    for _ in range(count):
        apu.frame_step()


def test_sequencer_wraps_after_step_7(apu: APU) -> None:
    frame_steps(apu, 8)

    assert apu.sequencer_step == 0


# --- channel 2: length ---


def test_nr21_loads_the_length(apu: APU) -> None:
    apu.write(NR21, 0x20)

    assert apu.channel2.length == 32


def test_length_runs_out_on_the_first_clock(apu: APU) -> None:
    apu.write(NR21, 0x3F)
    apu.write(NR22, DAC_ON)
    apu.write(NR24, TRIGGER | LENGTH_ENABLE)

    apu.frame_step()

    assert not apu.channel2.enabled
    assert apu.channel2.length == 0


def test_length_does_nothing_unless_enabled(apu: APU) -> None:
    apu.write(NR21, 0x3F)
    apu.write(NR22, DAC_ON)
    apu.write(NR24, TRIGGER)

    frame_steps(apu, 200)

    assert apu.channel2.enabled
    assert apu.channel2.length == 1


def test_length_clocks_on_even_steps_only(apu: APU) -> None:
    apu.write(NR21, 0x3E)
    apu.write(NR22, DAC_ON)
    apu.write(NR24, TRIGGER | LENGTH_ENABLE)

    frame_steps(apu, 2)
    assert apu.channel2.enabled

    apu.frame_step()
    assert not apu.channel2.enabled


def test_trigger_reloads_an_empty_length_with_64(apu: APU) -> None:
    apu.write(NR21, 0x3F)
    apu.write(NR22, DAC_ON)
    apu.write(NR24, TRIGGER | LENGTH_ENABLE)
    apu.frame_step()

    apu.write(NR24, TRIGGER | LENGTH_ENABLE)

    assert apu.channel2.enabled
    assert apu.channel2.length == 64


def test_trigger_keeps_a_running_length(apu: APU) -> None:
    apu.write(NR21, 0x20)
    apu.write(NR22, DAC_ON)

    apu.write(NR24, TRIGGER)

    assert apu.channel2.length == 32


# --- channel 2: envelope ---


def test_envelope_reaches_zero_after_120_frame_steps(apu: APU) -> None:
    apu.write(NR22, 0xF1)  # volume 15, down, pace 1
    apu.write(NR24, TRIGGER)

    frame_steps(apu, 119)
    assert apu.channel2.volume == 1

    apu.frame_step()
    assert apu.channel2.volume == 0
    assert apu.channel2.enabled


def test_envelope_goes_up_and_stops_at_15(apu: APU) -> None:
    apu.write(NR22, 0x09)  # volume 0, up, pace 1
    apu.write(NR24, TRIGGER)

    frame_steps(apu, 200)

    assert apu.channel2.volume == 15


def test_envelope_stops_at_0(apu: APU) -> None:
    apu.write(NR22, 0x11)  # volume 1, down, pace 1
    apu.write(NR24, TRIGGER)

    frame_steps(apu, 200)

    assert apu.channel2.volume == 0


def test_envelope_pace_3_steps_every_24_frame_steps(apu: APU) -> None:
    apu.write(NR22, 0xF3)
    apu.write(NR24, TRIGGER)

    frame_steps(apu, 23)
    assert apu.channel2.volume == 15

    apu.frame_step()
    assert apu.channel2.volume == 14


def test_trigger_restarts_the_envelope(apu: APU) -> None:
    apu.write(NR22, 0xF3)
    apu.write(NR24, TRIGGER)
    frame_steps(apu, 16)  # two clocks: timer at 1

    apu.write(NR24, TRIGGER)
    frame_steps(apu, 8)

    assert apu.channel2.volume == 15


def test_pace_0_keeps_the_volume(playing: APU) -> None:
    frame_steps(playing, 200)

    assert playing.channel2.volume == 15
