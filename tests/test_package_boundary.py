"""`PLAN.md` constraint 1 is a rule about which way imports point, and nothing
else in the project enforces it. A grep is a poor test in general; here the
thing being asserted really is the text of the source.
"""

import re
from pathlib import Path

FRONTEND_IMPORT = re.compile(r"^\s*(?:import|from)\s+screen\b", re.MULTILINE)
CORE = Path(__file__).resolve().parent.parent / "src" / "gameboy"


def test_the_core_never_imports_the_frontend() -> None:
    offenders = [
        path.name
        for path in sorted(CORE.rglob("*.py"))
        if FRONTEND_IMPORT.search(path.read_text())
    ]

    assert offenders == []
