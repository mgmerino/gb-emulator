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
from typing import Self

from gameboy import memory_map
from gameboy.bits import get_bit
from gameboy.memory_map import NR10, NR11, NR52, WAVE_RAM

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


@dataclass(slots=True)
class APU:
    registers: bytearray = field(default_factory=lambda: bytearray(0x20))
    wave_ram: bytearray = field(default_factory=lambda: bytearray(16))

    @classmethod
    def post_boot(cls) -> Self:
        apu = cls()
        apu.registers[NR10] = 0x80
        apu.registers[NR11] = 0xBF
        # ... añadir los que faltan

        return apu

    @property
    def powered(self) -> bool:
        value = self.registers[NR52 - memory_map.APU.start]

        return get_bit(value, 7)

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

    def _write_to_apu_register(self, address: int, value: int) -> None:
        self.registers[address - memory_map.APU.start] = value
