"""Passage title and section (EA-37, R13)."""

import pytest

from ei_ai.knowledge.answers.sources import source_section, source_title


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Leave Policy 2026.pdf", "Leave Policy 2026"),
        ("Leave Policy v1.2.DOCX", "Leave Policy v1.2"),
        ("notes.md", "notes"),
        ("a.txt", "a"),
        ("notes.v2", "notes.v2"),
    ],
)
def test_source_title(name: str, expected: str) -> None:
    assert source_title(name) == expected


def test_source_section() -> None:
    assert source_section(()) is None
    assert source_section(("Policies", "§4.1 Personal leave")) == "§4.1 Personal leave"
