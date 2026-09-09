"""`PLAN.md` constraint 1 is a rule about which way imports point, and nothing
else in the project enforces it. A grep is a poor test in general; here the
thing being asserted really is the text of the source.
"""

import re
from pathlib import Path

FRONTEND_IMPORT = re.compile(r"^\s*(?:import|from)\s+screen\b", re.MULTILINE)
PYGAME_IMPORT = re.compile(r"^\s*(?:import|from)\s+pygame\b", re.MULTILINE)
SRC = Path(__file__).resolve().parent.parent / "src"
CORE = SRC / "gameboy"

# The seam and the loop have to import on a checkout with no `gui` extra,
# because that is what CI has and what the tests below run under. Prove it
# with `uv run --exact pytest`, which prunes the extras from the venv.
HEADLESS = ("display.py", "loop.py")


def test_the_core_never_imports_the_frontend() -> None:
    offenders = [
        path.name
        for path in sorted(CORE.rglob("*.py"))
        if FRONTEND_IMPORT.search(path.read_text())
    ]

    assert offenders == []


def test_the_headless_frontend_modules_do_not_import_pygame() -> None:
    offenders = [
        name
        for name in HEADLESS
        if PYGAME_IMPORT.search((SRC / "screen" / name).read_text())
    ]

    assert offenders == []
