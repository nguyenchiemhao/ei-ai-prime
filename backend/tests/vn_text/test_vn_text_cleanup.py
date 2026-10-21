"""``clean``: invisible characters removed, exotic spaces mapped, layout and emoji kept (R5)."""

import pytest

from ei_ai.vn_text import normalize
from ei_ai.vn_text.cleanup import clean
from vn_text.cases import CLEANUP_CASES


@pytest.mark.parametrize(("src", "expected"), CLEANUP_CASES)
def test_cleanup_table(src: str, expected: str) -> None:
    assert clean(src) == expected


def test_reordered_marks_compose() -> None:
    assert normalize("e\u0301\u0302") == "ế"
    assert normalize("é\u0302") == "ế"
