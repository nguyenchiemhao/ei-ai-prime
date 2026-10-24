"""Citation filter (EA-37, AC2, R21)."""

import pytest

from ei_ai.knowledge.answers.citations import CitationFilter, cited_numbers


def _run(text: str, k: int = 3) -> tuple[str, int]:
    flt = CitationFilter(k)
    out = flt.feed(text) + flt.flush()
    return out, flt.removed


@pytest.mark.parametrize(
    ("text", "expected", "removed"),
    [
        ("a [1] b", "a [1] b", 0),
        ("[1, 2]", "[1][2]", 0),
        ("[1,2]", "[1][2]", 0),
        ("[ 1 ]", "[1]", 0),
        ("[1, 9]", "[1]", 1),
        ("[0]", "", 1),
        ("[01]", "", 1),
        ("[7]", "", 1),
        ("[1-3]", "[1-3]", 0),
        ("[see section 4]", "[see section 4]", 0),
        ("【1】", "【1】", 0),
        ("[1][1]", "[1][1]", 0),
        ("x [123456789012345", "x [123456789012345", 0),
        ("[[1]", "[[1]", 0),
        ("a [", "a [", 0),
    ],
)
def test_citation_filter_cases(text: str, expected: str, removed: int) -> None:
    assert _run(text) == (expected, removed)


def test_citation_filter_split_across_deltas() -> None:
    flt = CitationFilter(3)
    pieces = [flt.feed(d) for d in ["Nghỉ 3 ngày ", "[", "1", "]", " và [", "9]."]]
    assert pieces[1] == "" and pieces[2] == ""
    assert pieces[3] == "[1]"
    assert pieces[5] == "."
    assert "".join(pieces) + flt.flush() == "Nghỉ 3 ngày [1] và ."
    assert flt.removed == 1


def test_cited_numbers() -> None:
    assert cited_numbers("[2] a [1] [2] [9]", 3) == (1, 2)
    assert cited_numbers("no citations", 3) == ()
