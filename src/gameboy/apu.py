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

from dataclasses import dataclass, field
from typing import Final, Self

from gameboy import memory_map
from gameboy.bits import get_bit
from gameboy.memory_map import (
    NR10,
    NR11,
    NR12,
    NR14,
    NR21,
    NR22,
    NR23,
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
    enabled: bool = False
    duty_step: int = 0
    ticks_left: int = 0
    volume: int = 0


@dataclass(slots=True)
class APU:
    registers: bytearray = field(default_factory=lambda: bytearray(0x20))
    wave_ram: bytearray = field(default_factory=lambda: bytearray(16))
    channel2: PulseChannel = field(default_factory=PulseChannel)

    @classmethod
    def post_boot(cls) -> Self:
        apu = cls()
        for address, value in POST_BOOT.items():
            apu.write(address, value)

        return apu

    @property
    def powered(self) -> bool:
        value = self.registers[NR52 - memory_map.APU.start]

        return get_bit(value, 7)

    @property
    def _period(self) -> int:
        mask = 0b00000111

        return (self._register(NR24) & mask) << 8 | self._register(NR23)

    @property
    def _duty(self) -> int:
        return self._register(NR21) >> 6

    @property
    def _dac_on(self) -> bool:
        mask = 0b11111000

        return (self._register(NR22) & mask) != 0
    
    def _trigger_channel2(self) -> None:
        channel = self.channel2
        channel.enabled = self._dac_on
        channel.ticks_left = 2048 - self._period
        channel.volume = self._register(NR22) >> 4

    def read(self, address: int) -> int:
        if address in WAVE_RAM:
            return self.wave_ram[address - WAVE_RAM.start]

        index = address - memory_map.APU.start
        masked = self.registers[index] | MASKS[index]

        return masked

    def write(self, address: int, value: int) -> None:
        if address in WAVE_RAM:
            self.wave_ram[address - WAVE_RAM.start] = value
        elif address == NR52:
            masked = value & 0b1000_0000
            if not get_bit(masked, 7):
                self.registers[0:0x16] = bytes(0x16)

            self._write_to_apu_register(address, masked)
        else:
            if self.powered:
                self._write_to_apu_register(address, value)

                if address == NR22 and not self._dac_on:
                    self.channel2.enabled = False
                if address == NR24 and get_bit(value, 7):
                    self._trigger_channel2()


    def _register(self, address: int) -> int:
        return self.registers[address - memory_map.APU.start]

    def _write_to_apu_register(self, address: int, value: int) -> None:
        self.registers[address - memory_map.APU.start] = value
