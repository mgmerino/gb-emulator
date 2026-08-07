from typing import Final

# Cartridge ROM full range
ROM: Final = range(0x0000, 0x8000)  # noqa: PIE808

# Memory Bank Controllers
# ROM is composed of two banks:
ROM_BANK_0: Final = range(0x0000, 0x4000)  # noqa: PIE808
ROM_BANK_1: Final = range(0x4000, 0x8000)
# Video RAM, owned by PPU: tiles and tile maps
VRAM: Final = range(0x8000, 0xA000)
# Cartridge's external RAM
EXTERNAL_RAM: Final = range(0xA000, 0xC000)
# Console: WRAM bank switching only exists on CGB
# For now, we won't make a difference
WRAM: Final = range(0xC000, 0xE000)
# Console: Mirror of `0xC000–0xDDFF`
ECHO_RAM: Final = range(0xE000, 0xFE00)
ECHO_OFFSET: Final = ECHO_RAM.start - WRAM.start
# Object Attribute Memory, owned by PPU: 40 sprite entries of 4 bytes
OAM: Final = range(0xFE00, 0xFEA0)

PROHIBITED: Final = range(0xFEA0, 0xFF00)
IO: Final = range(0xFF00, 0xFF80)
# Console: high RAM
HRAM: Final = range(0xFF80, 0xFFFF)
INTERRUPT_ENABLE: Final = 0xFFFF

# Hardware mapping states
OPEN_BUS: Final = 0xFF
PROHIBITED_READ: Final = 0x00
