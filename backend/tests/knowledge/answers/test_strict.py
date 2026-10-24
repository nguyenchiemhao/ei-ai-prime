"""Strict-mode rules (EA-37, R5, R20)."""

from dataclasses import replace
from uuid import uuid4

import pytest

from ei_ai.knowledge.answers.strict import SentinelDetector, has_relevant_passage
from ei_ai.knowledge.retrieval.service import Passage


def _passage(retrieval: float, rerank: float | None = None) -> Passage:
    return Passage(
        chunk_id=uuid4(),
        document_id=uuid4(),
        collection_id=uuid4(),
        folder_id=uuid4(),
        document_name="a.md",
        page=None,
        heading_path=(),
        ordinal=0,
        text="t",
        retrieval_score=retrieval,
        rerank_score=rerank,
    )


def _run(pieces: list[str]) -> tuple[str, bool]:
    det = SentinelDetector()
    out = "".join(det.feed(p) for p in pieces) + det.flush()
    return out, det.matched


@pytest.mark.parametrize(
    "pieces",
    [
        ["  NOT_FOUND"],
        ["NOT_FOUND."],
        ["NOT_FOUND because the passages say nothing"],
        ["NOT", "_FO", "UND"],
    ],
)
def test_sentinel_matched(pieces: list[str]) -> None:
    assert _run(pieces) == ("", True)


@pytest.mark.parametrize(
    "pieces",
    [["NOTE: see [1]"], ["Answer NOT_FOUND"], ['"NOT_FOUND"'], ["not_found"], ["NOT", "E: x"]],
)
def test_sentinel_not_matched_returns_full_text(pieces: list[str]) -> None:
    out, matched = _run(pieces)
    assert not matched
    assert out == "".join(pieces)


def test_sentinel_withholds_prefix_until_divergence() -> None:
    det = SentinelDetector()
    assert det.feed("NOT") == ""
    assert det.feed("E") == "NOTE"
    assert det.feed(" NOT_FOUND") == " NOT_FOUND"
    assert not det.matched


def test_sentinel_prefix_at_end_is_flushed() -> None:
    det = SentinelDetector()
    assert det.feed("NOT") == ""
    assert det.flush() == "NOT"
    assert not det.matched


def test_has_relevant_passage() -> None:
    assert not has_relevant_passage([])
    assert not has_relevant_passage([_passage(0.2), _passage(0.34)])
    assert has_relevant_passage([_passage(0.1), _passage(0.35)])
    reranked = [_passage(0.1, 0.99), _passage(0.5, 0.2)]
    assert has_relevant_passage(reranked)
    assert not has_relevant_passage([replace(p, retrieval_score=0.1) for p in reranked])
