"""Test-only ``Reranker``: scores from a function, no model, no network (EA-36).

``score(query, document)`` gives each document's score (default: 0.0 for every document, so the
service's tie-break decides). ``fail`` makes every call raise it. ``seen`` records every documents
list it was given, so a test can prove which texts reached the reranker.

Never imported by ``src``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.refs import ModelRef


@dataclass
class FakeReranker:
    ref: ModelRef = ModelRef("bge-reranker-v2-m3", "2026.10")
    score: Callable[[str, str], float] | None = None
    fail: Exception | None = None
    seen: list[list[str]] = field(default_factory=list)

    async def rerank(
        self, ctx: ModelCallContext, query: str, documents: Sequence[str]
    ) -> list[float]:
        self.seen.append(list(documents))
        if self.fail is not None:
            raise self.fail
        if self.score is None:
            return [0.0 for _ in documents]
        return [self.score(query, document) for document in documents]
