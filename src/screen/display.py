"""The seam between the emulator and whatever is showing it.

This module never imports pygame, on purpose. The Protocol is how the loop
avoids depending on pygame, so it cannot live in the module that imports
pygame: naming the seam would install the thing it hides. Importing from
`gameboy` is fine; the seam carries its types.
"""

from typing import Protocol

from gameboy.joypad import Button


class Display(Protocol):
    def present(self, frame: memoryview) -> None: ...
    def wants_to_close(self) -> bool: ...
    def show_rate(self, rate: float) -> None: ...
    def held(self) -> frozenset[Button]: ...
