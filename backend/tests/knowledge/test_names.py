"""The shared text rules of collections and folders."""

import pytest

from ei_ai.knowledge.errors import InvalidKnowledgeInput
from ei_ai.knowledge.names import clean_name


def test_clean_name_trims_and_keeps_unicode() -> None:
    assert clean_name("  Quy trình nhân sự ") == "Quy trình nhân sự"


@pytest.mark.parametrize("bad", ["\u0000", "\x07", "a\tb", "a\nb", "a\x7fb"])
def test_clean_name_rejects_control_characters(bad: str) -> None:
    with pytest.raises(InvalidKnowledgeInput):
        clean_name(f"A{bad}B")
