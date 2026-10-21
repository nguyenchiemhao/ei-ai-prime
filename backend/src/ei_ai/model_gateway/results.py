"""What callers pass to and get from the gateway. Every result names the pinned ref and digest."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ChatCompleted:
    """The last event of a stream."""

    model_ref: str
    digest: str | None
    usage: Usage
    finish_reason: str | None
    attempts: int


StreamEvent = TextDelta | ChatCompleted


@dataclass(frozen=True)
class ChatResult:
    text: str
    model_ref: str
    digest: str | None
    usage: Usage
    attempts: int


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model_ref: str
    digest: str | None
    usage: Usage


@dataclass(frozen=True)
class RerankResult:
    # (document index, relevance score), as the server ranked them.
    results: list[tuple[int, float]]
    model_ref: str
    digest: str | None
