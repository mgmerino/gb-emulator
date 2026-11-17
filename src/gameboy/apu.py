"""Ref table
0xFF10 ┌──────┬──────┬──────┬──────┬──────┐
       │ NR10 │ NR11 │ NR12 │ NR13 │ NR14 │  channel 1   pulse with sweep (17C)
0xFF15 ├──────┼──────┼──────┼──────┼──────┤
       │  --  │ NR21 │ NR22 │ NR23 │ NR24 │  channel 2   pulse            (this step)
0xFF1A ├──────┼──────┼──────┼──────┼──────┤
       │ NR30 │ NR31 │ NR32 │ NR33 │ NR34 │  channel 3   wave             (17C)
0xFF1F ├──────┼──────┼──────┼──────┼──────┤
       │  --  │ NR41 │ NR42 │ NR43 │ NR44 │  channel 4   noise            (17C)
0xFF24 ├──────┼──────┼──────┼──────┴──────┘
       │ NR50 │ NR51 │ NR52 │                 control      volume, panning, power
0xFF27 ├──────┴──────┴──────┴────────────────┐
       │ unused, reads 0xFF                  │  0xFF27–0xFF2F
0xFF30 ├─────────────────────────────────────┤
       │ wave RAM, 16 bytes                  │  0xFF30–0xFF3F, channel 3's samples
0xFF40 └─────────────────────────────────────┘
         NRx0   NRx1   NRx2   NRx3   NRx4
         other  length volume period period high,
                (duty) env.   low    trigger
"""

from array import array
from dataclasses import dataclass, field
from typing import Final, Self

from gameboy import memory_map
from gameboy.bits import get_bit
from gameboy.memory_map import (
    NR10,
    NR11,
    NR12,
    NR14,
    NR20,
    NR21,
    NR24,
    NR30,
    NR32,
    NR34,
    NR41,
    NR44,
    NR50,
    NR51,
    NR52,
    WAVE_RAM,
)

# fmt: off
MASKS = bytes([
    0x80, 0x3F, 0x00, 0xFF, 0xBF,  # NR10-NR14
    0xFF, 0x3F, 0x00, 0xFF, 0xBF,  # --, NR21-NR24
    0x7F, 0xFF, 0x9F, 0xFF, 0xBF,  # NR30-NR34
    0xFF, 0xFF, 0x00, 0x00, 0xBF,  # --, NR41-NR44
    0x00, 0x00, 0x70,              # NR50-NR52
    *[0xFF] * 9                    # 0xFF27–0xFF2F
])
# fmt: on

# Each channel access to five registers through a memoryview, using an offeset.
# Pan Docs names them NRx0 to NRx4, with x the channel number.
NRX0: Final = 0
NRX1: Final = 1
NRX2: Final = 2
NRX3: Final = 3
NRX4: Final = 4

DUTY_PATTERNS: Final[tuple[tuple[int, ...], ...]] = (
    (0, 0, 0, 0, 0, 0, 0, 1),  # 12.5% _______-
    (1, 0, 0, 0, 0, 0, 0, 1),  # 25%   -______-
    (1, 0, 0, 0, 0, 1, 1, 1),  # 50%   -____---
    (0, 1, 1, 1, 1, 1, 1, 0),  # 75%   _------_
)
DUTY_STEPS: Final = 8

# The period divider counts up from the period and reloads when it reaches 2048.
PERIOD_OVERFLOW: Final = 2048
MAX_LENGTH: Final = 64
MAX_VOLUME: Final = 15

SEQUENCER_STEPS: Final = 8
ENVELOPE_STEP: Final = 7

SAMPLE_RATE: Final = 48_000
CHANNEL_PEAK: Final = 8_000
CLOCK_HZ: Final = 4_194_304

# What the boot ROM leaves in the registers, from Pan Docs. NR52 goes first:
# `write` ignores the rest while the APU is off. The other registers read as 0.
POST_BOOT: Final = {
    NR52: 0xF1,
    NR10: 0x80,
    NR11: 0xBF,
    NR12: 0xF3,
    NR14: 0xBF,
    NR21: 0x3F,
    NR24: 0xBF,
    NR30: 0x7F,
    NR32: 0x9F,
    NR34: 0xBF,
    NR41: 0xFF,
    NR44: 0xBF,
    NR50: 0x77,
    NR51: 0xF3,
}


@dataclass(slots=True)
class PulseChannel:
    regs: memoryview
    enabled: bool = False
    duty_step: int = 0
    ticks_left: int = 0
    volume: int = 0
    length: int = 0
    envelope_timer: int = 0

    @property
    def output(self) -> int:
        if not self.enabled:
            return 0
        bit = DUTY_PATTERNS[self._duty][self.duty_step]

        return bit * self.volume

    @property
    def sample(self) -> int:
        if not self.dac_on:
            return 0

        ch_out = self.output
        return CHANNEL_PEAK * (MAX_VOLUME - 2 * ch_out) // MAX_VOLUME

    # --- Events ---

    def clock_envelope(self) -> None:
        if self._pace == 0:
            return

        self.envelope_timer -= 1
        if self.envelope_timer == 0:
            self.envelope_timer = self._pace
            if self._volume_upwards:
                self.volume = min(self.volume + 1, MAX_VOLUME)
            else:
                self.volume = max(self.volume - 1, 0)

    def clock_length(self) -> None:
        if self._length_enabled and self.length > 0:
            self.length -= 1
            if self.length == 0:
                self.enabled = False

    def on_write(self, offset: int, value: int) -> None:
        if offset == NRX1:
            mask = 0b0011_1111
            self.length = MAX_LENGTH - (value & mask)
        if offset == NRX2 and not self.dac_on:
            self.enabled = False
        if offset == NRX4 and get_bit(value, 7):
            self.trigger()

    def tick(self, cycles: int) -> None:
        self.ticks_left -= cycles // 4
        while self.ticks_left <= 0:
            self.duty_step = (self.duty_step + 1) % DUTY_STEPS
            self.ticks_left += PERIOD_OVERFLOW - self.period

    def trigger(self) -> None:
        self.enabled = self.dac_on
        self.ticks_left = PERIOD_OVERFLOW - self.period
        self.volume = self.regs[NRX2] >> 4
        self.envelope_timer = self._pace
        if self.length == 0:
            self.length = MAX_LENGTH

    # --- NRX1 ---

    @property
    def _duty(self) -> int:
        return self.regs[NRX1] >> 6

    # NRX2 │ 7  6  5  4 │ 3 │ 2  1  0 │
    #      │ initial vol│dir│  pace   │ dir: 1 = upward,
    #                                        0 = downward
    #                                  pace: 0 = stopped envelope
    @property
    def dac_on(self) -> bool:
        mask = 0b1111_1000

        return (self.regs[NRX2] & mask) != 0

    @property
    def _pace(self) -> int:
        mask = 0b0000_0111

        return self.regs[NRX2] & mask

    @property
    def _volume_upwards(self) -> bool:
        mask = 0b0000_1000

        return (self.regs[NRX2] & mask) != 0

    # --- NRX3/NRX4 ---

    @property
    def _length_enabled(self) -> bool:
        mask = 0b0100_0000

        return (self.regs[NRX4] & mask) != 0

    @property
    def period(self) -> int:
        mask = 0b0000_0111

        return (self.regs[NRX4] & mask) << 8 | self.regs[NRX3]


@dataclass(slots=True)
class APU:
    registers: bytearray = field(default_factory=lambda: bytearray(0x20))
    wave_ram: bytearray = field(default_factory=lambda: bytearray(16))
    channel1: PulseChannel = field(init=False)
    channel2: PulseChannel = field(init=False)
    sequencer_step: int = 0
    samples: array[int] = field(default_factory=lambda: array("h"))
    sample_acc: int = 0

    def __post_init__(self) -> None:
        self.channel2 = PulseChannel(self._channel_regs(NR20))
        self.channel1 = PulseChannel(self._channel_regs(NR10))

    @classmethod
    def post_boot(cls) -> Self:
        apu = cls()
        for address, value in POST_BOOT.items():
            apu.write(address, value)

        return apu

    # --- The bus side ---

    @property
    def powered(self) -> bool:
        value = self.registers[NR52 - memory_map.APU.start]

        return get_bit(value, 7)

    def read(self, address: int) -> int:
        if address in WAVE_RAM:
            return self.wave_ram[address - WAVE_RAM.start]

        index = address - memory_map.APU.start
        masked = self.registers[index] | MASKS[index]
        if address == NR52:
            # Bits 3-0 are not stored, only signal which channels are on.
            return masked | int(self.channel1.enabled) | int(self.channel2.enabled) << 1

        return masked

    def write(self, address: int, value: int) -> None:
        if address in WAVE_RAM:
            self.wave_ram[address - WAVE_RAM.start] = value
        elif address == NR52:
            masked = value & 0b1000_0000
            # switch off the APU
            if not get_bit(masked, 7):
                self.registers[0:0x16] = bytes(0x16)
                self.channel2 = PulseChannel(self.channel2.regs)
                self.channel1 = PulseChannel(self.channel1.regs)
                # not 100% accurate, hardware quirck on poweroff are ignored
                # for now
                self.sequencer_step = 0

            self._write_to_apu_register(address, masked)
        else:
            if self.powered:
                self._write_to_apu_register(address, value)
                if NR10 <= address <= NR14:
                    self.channel1.on_write(address - NR10, value)
                elif NR21 <= address <= NR24:
                    self.channel2.on_write(address - NR20, value)

    # --- Time ---

    def frame_step(self) -> None:
        # step       0   1   2   3   4   5   6   7
        # length     ●       ●       ●       ●
        # envelope                               ●

        if self.sequencer_step % 2 == 0:
            self.channel1.clock_length()
            self.channel2.clock_length()

        if self.sequencer_step == ENVELOPE_STEP:
            self.channel1.clock_envelope()
            self.channel2.clock_envelope()

        self.sequencer_step = (self.sequencer_step + 1) % SEQUENCER_STEPS

    def tick(self, cycles: int) -> None:
        self.channel1.tick(cycles)
        self.channel2.tick(cycles)
        self.sample_acc += cycles * SAMPLE_RATE
        while self.sample_acc >= CLOCK_HZ:
            self.sample_acc -= CLOCK_HZ
            sum_sample = self.channel1.sample + self.channel2.sample
            self.samples.append(sum_sample)

    # --- Output ---

    def take_samples(self) -> array[int]:
        samples = self.samples
        self.samples = array("h")

        return samples

    def _channel_regs(self, base: int) -> memoryview:
        i = base - memory_map.APU.start
        return memoryview(self.registers)[i : i + 5]

    # --- Channel 2 ---
    @property
    def channel2_output(self) -> int:
        return self.channel2.output

    @property
    def channel2_sample(self) -> int:
        return self.channel2.sample

    # --- Raw register bytes ---

    def _write_to_apu_register(self, address: int, value: int) -> None:
        self.registers[address - memory_map.APU.start] = value
