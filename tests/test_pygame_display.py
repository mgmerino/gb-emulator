"""The one part of the frontend that needs the `gui` extra.

Skipped when it is absent, so `uv run --exact pytest` stays green on a checkout
with nothing installed. The dummy video driver is what lets it run with no
display server, here and in CI.
"""

import os
from collections.abc import Iterator

import pytest

from gameboy.ppu import PPU
from screen.display import Display

pygame = pytest.importorskip("pygame")

from screen.pygame_display import PygameDisplay


@pytest.fixture
def window() -> Iterator[PygameDisplay]:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    display = PygameDisplay(scale=2, title="TETRIS")

    yield display

    pygame.display.quit()


def test_it_satisfies_the_protocol(window: PygameDisplay) -> None:
    def takes(display: Display) -> None: ...

    takes(window)  # a type error here is the assertion


def test_it_presents_a_frame(window: PygameDisplay) -> None:
    window.present(PPU().frame)


def test_the_rate_goes_in_the_title(window: PygameDisplay) -> None:
    window.show_rate(9.04)

    assert pygame.display.get_caption()[0] == "TETRIS - 9.0 fps"


def test_it_reports_a_quit_event(window: PygameDisplay) -> None:
    assert not window.wants_to_close()

    pygame.event.post(pygame.event.Event(pygame.QUIT))

    assert window.wants_to_close()


def test_it_drains_the_queue(window: PygameDisplay) -> None:
    """A window nobody reads events from is one the desktop offers to kill."""
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))

    assert window.wants_to_close()
    assert not pygame.event.peek()
