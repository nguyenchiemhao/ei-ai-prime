"""Strict-mode "not found" rules (EA-37, R5, R20)."""

from collections.abc import Sequence

from ei_ai.knowledge.retrieval.service import Passage

NOT_FOUND_SENTINEL = "NOT_FOUND"
MIN_RELEVANCE = 0.35
"""Assumption (bge-m3 is not calibrated yet): recalibrate with EVL-02."""


def has_relevant_passage(passages: Sequence[Passage]) -> bool:
    """Gate on the best cosine score, whatever order a reranker gave (R5)."""
    return max((p.retrieval_score for p in passages), default=-1.0) >= MIN_RELEVANCE


class SentinelDetector:
    """Withholds a leading ``NOT_FOUND`` reply from the stream (R20).

    Leading whitespace is ignored. While the text so far is a proper prefix of the sentinel it is
    withheld; once it starts with the sentinel everything is dropped; once it diverges the buffer
    is released and the text is never checked again.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._passing = False
        self.matched = False

    def feed(self, text: str) -> str:
        if self._passing:
            return text
        if self.matched:
            return ""
        self._buffer += text
        stripped = self._buffer.lstrip()
        if stripped.startswith(NOT_FOUND_SENTINEL):
            self.matched = True
            self._buffer = ""
            return ""
        if NOT_FOUND_SENTINEL.startswith(stripped):
            return ""
        self._passing = True
        released, self._buffer = self._buffer, ""
        return released

    def flush(self) -> str:
        released, self._buffer = self._buffer, ""
        return released
