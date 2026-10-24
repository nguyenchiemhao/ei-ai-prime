"""What an answer stream yields (EA-37): passages, text deltas, then one end event."""

from dataclasses import dataclass
from typing import Literal

from ei_ai.vn_text.language import Language


@dataclass(frozen=True)
class PassageInfo:
    """What the user sees of a passage; never its text."""

    number: int
    title: str
    section: str | None
    page: int | None
    score: float


@dataclass(frozen=True)
class PassagesFound:
    language: Language
    passages: tuple[PassageInfo, ...]


@dataclass(frozen=True)
class AnswerDelta:
    text: str


@dataclass(frozen=True)
class AnswerDone:
    outcome: Literal["answered", "not_found"]
    answer: str
    citations: tuple[int, ...]


@dataclass(frozen=True)
class AnswerFailed:
    code: Literal["model_unavailable", "answer_failed"]


AnswerEvent = PassagesFound | AnswerDelta | AnswerDone | AnswerFailed
