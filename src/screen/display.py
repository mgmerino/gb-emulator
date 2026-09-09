"""The seam between the emulator and whatever is showing it.

This module imports nothing outside the stdlib on purpose. The Protocol is
how the loop avoids depending on pygame, so it cannot live in the module
that imports pygame: naming the seam would install the thing it hides.
"""

from typing import Protocol


class Display(Protocol):
    def present(self, frame: memoryview) -> None: ...
    def wants_to_close(self) -> bool: ...
    def show_rate(self, rate: float) -> None: ...
