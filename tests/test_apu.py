import pytest

from gameboy.apu import APU, MASKS
from gameboy.cartridge import Cartridge
from gameboy.memory import Bus

NR10 = 0xFF10
NR11 = 0xFF11
NR21 = 0xFF16
NR22 = 0xFF17
NR23 = 0xFF18
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
