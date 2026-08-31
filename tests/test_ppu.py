from gameboy.ppu import (
    PPU,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_DATA_UNSIGNED,
    TILE_MAP_0,
    TILE_SIZE,
    Mode,
)


def test_ppu_post_boot() -> None:
    ppu = PPU.post_boot()
    assert ppu.lcdc == 0x91
    assert ppu.bgp == 0xFC
    assert ppu.mode is Mode.VBLANK
    assert ppu.stat == 0x00  # the selects; STAT assembles 0x85 on read, in task 2


def test_ppu_constants() -> None:
    assert len(PPU().framebuffer) == 23040
    assert SCREEN_WIDTH * SCREEN_HEIGHT == 23040
    assert TILE_SIZE == 16
    # 384 tiles between the unsigned base and the first map
    assert (TILE_MAP_0 - TILE_DATA_UNSIGNED) // TILE_SIZE == 384
