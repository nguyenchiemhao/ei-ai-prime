"""R1-4: no code may weaken row-level security (the product must never copy an owner bypass).

``NO FORCE ROW LEVEL SECURITY`` and ``DISABLE ROW LEVEL SECURITY`` must not appear under ``src`` at
all, and under ``tests`` only in the files that assert the application role is refused them.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"NO\s+FORCE\s+ROW\s+LEVEL\s+SECURITY|DISABLE\s+ROW\s+LEVEL\s+SECURITY", re.I)

# Tests that intentionally attempt it, as the application role inside a rolled-back transaction.
ALLOWED_IN_TESTS = {"tests/integration/db/test_roles.py", "tests/test_no_rls_bypass.py"}


def _offenders(folder: str, allowed: set[str]) -> list[str]:
    found = []
    for path in sorted((BACKEND / folder).rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        if relative not in allowed and PATTERN.search(path.read_text(encoding="utf-8")):
            found.append(relative)
    return found


def test_no_code_under_src_weakens_row_level_security() -> None:
    assert _offenders("src", set()) == []


def test_tests_weaken_row_level_security_only_to_assert_that_it_is_refused() -> None:
    assert _offenders("tests", ALLOWED_IN_TESTS) == []
