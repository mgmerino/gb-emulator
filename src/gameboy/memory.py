"""The general rule for this project: an unimplemented read returns `0xFF`, an
unimplemented write is dropped. Never raise. A raise means one missing feature
crashes the emulator instead of degrading it, and we lose the ability to see
how far a ROM gets.
"""

from typing import Protocol

from gameboy import bits, memory_map


class MemoryDevice(Protocol):
    def read(self, address: int) -> int: ...
    def write(self, address: int, value: int) -> None: ...
    def read16(self, address: int) -> int: ...
    def write16(self, address: int, value: int) -> None: ...


class Bus:
    def __init__(self, cartridge: MemoryDevice) -> None:
        self.cartridge = cartridge
        self.wram = bytearray(0x2000)
        self.hram = bytearray(0x7F)
        self.vram = bytearray(0x2000)
        self.oam = bytearray(0xA0)
        self.io = bytearray(0x80)
        self.ie = 0

    def read(self, address: int) -> int:
        masked_address = bits.u16(address)
        # Dispatch on the region. Order the branches by how often the CPU hits
        # them, ROM and WRAM dominate.
        match masked_address:
            case _ if (
                masked_address in memory_map.ROM
                or masked_address in memory_map.EXTERNAL_RAM
            ):
                return self.cartridge.read(masked_address)
            case _ if masked_address in memory_map.WRAM:
                return self.wram[masked_address - memory_map.WRAM.start]
            case _ if masked_address in memory_map.VRAM:
                return self.vram[masked_address - memory_map.VRAM.start]
            case _ if masked_address in memory_map.ECHO_RAM:
                return self.read(masked_address - memory_map.ECHO_OFFSET)
            case _ if masked_address in memory_map.OAM:
                return self.oam[masked_address - memory_map.OAM.start]
            case _ if masked_address in memory_map.IO:
                return self.io[masked_address - memory_map.IO.start]
            case _ if masked_address in memory_map.HRAM:
                return self.hram[masked_address - memory_map.HRAM.start]
            case memory_map.INTERRUPT_ENABLE:
                return self.ie
            case _ if masked_address in memory_map.PROHIBITED:
                return memory_map.PROHIBITED_READ
            case _:
                return memory_map.OPEN_BUS

    def write(self, address: int, value: int) -> None:
        masked_address = bits.u16(address)
        masked_value = bits.u8(value)
        match masked_address:
            case _ if (
                masked_address in memory_map.ROM
                or masked_address in memory_map.EXTERNAL_RAM
            ):
                return self.cartridge.write(masked_address, masked_value)
            case _ if masked_address in memory_map.WRAM:
                self.wram[masked_address - memory_map.WRAM.start] = masked_value
            case _ if masked_address in memory_map.VRAM:
                self.vram[masked_address - memory_map.VRAM.start] = masked_value
            case _ if masked_address in memory_map.ECHO_RAM:
                self.write(masked_address - memory_map.ECHO_OFFSET, masked_value)
            case _ if masked_address in memory_map.OAM:
                self.oam[masked_address - memory_map.OAM.start] = masked_value
            case _ if masked_address in memory_map.IO:
                self.io[masked_address - memory_map.IO.start] = masked_value
            case _ if masked_address in memory_map.HRAM:
                self.hram[masked_address - memory_map.HRAM.start] = masked_value
            case memory_map.INTERRUPT_ENABLE:
                self.ie = masked_value
            case _ if masked_address in memory_map.PROHIBITED:
                return
            case _:
                return

    def read16(self, address: int) -> int:
        return bits.join_bytes(self.read(address + 1), self.read(address))

    def write16(self, address: int, value: int) -> None:
        self.write(address, bits.low_byte(value))
        self.write(address + 1, bits.high_byte(value))
