"""The window, and anything else that turns a framebuffer into something to look
at.

Imports run one way: this package may import `gameboy`, and `gameboy` may not
import this. That direction is what keeps the emulator runnable, and its tests
green, on a checkout with nothing installed.
"""
