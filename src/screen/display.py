"""The display: a display Protocol for the loop and a pygame implementation."""

from typing import Final, Protocol

import pygame
from pygame.surface import Surface

from gameboy.ppu import SCREEN_HEIGHT, SCREEN_WIDTH

GREENS: Final = (
    (0x9B, 0xBC, 0x0F),  # shade 0, lightest
    (0x8B, 0xAC, 0x0F),  # shade 1
    (0x30, 0x62, 0x30),  # shade 2
    (0x0F, 0x38, 0x0F),  # shade 3, darkest
)


class Display(Protocol):
    def present(self, frame: memoryview) -> None: ...
    def wants_to_close(self) -> bool: ...


class PygameDisplay:
    """A window, 160x144 scaled up, wearing the four greens."""

    _scale: int
    _screen: Surface

    def __init__(self, scale: int = 3, title: str = "gameboy") -> None:
        # The window is the scaled size and `present` does the scaling, rather
        # than asking `set_mode` for a 160x144 logical surface with
        # `pygame.SCALED` and letting SDL do it. With `SCALED` the platform
        # picks the backend and the cost moves somewhere this file cannot
        # measure. Step 13B is about measuring, so the step stays here.
        #
        # It is cheap either way: `present` takes 0.11 ms, against the ~110 ms
        # an emulated frame costs today.
        self._scale = scale
        self._screen = pygame.display.set_mode(
            (SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale)
        )
        pygame.display.set_caption(title)

    def present(self, frame: memoryview) -> None:
        """Puts one frame. A `frame` is 23040 read-only bytes, one per pixel,
        each containing a shade ranging from 0 to 3.
        """
        # `frombuffer` wraps the PPU's bytes instead of copying them, so this
        # costs one object, not 23040 assignments.
        #
        # The PPU writes into that buffer and never replaces it, so the Surface
        # could be built once in `__init__`. That would save 2 us a frame, and
        # cost a constructor that takes a framebuffer and a `present` that
        # ignores its own argument.
        frame_surface = pygame.image.frombuffer(
            frame, (SCREEN_WIDTH, SCREEN_HEIGHT), "P"
        )
        frame_surface.set_palette(GREENS)

        self._screen.blit(pygame.transform.scale_by(frame_surface, self._scale), (0, 0))
        pygame.display.flip()

    def wants_to_close(self) -> bool:
        # Drain the whole queue, even once the answer is known. SDL keeps
        # queueing events whether or not anyone reads them, and a window that
        # never reads is one the desktop reports as hung.
        should_close = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                should_close = True

        return should_close
