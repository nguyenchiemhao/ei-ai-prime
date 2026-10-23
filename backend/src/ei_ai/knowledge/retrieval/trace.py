"""The trace of one retrieval (EA-36 AC7): ids, counts, scores and timings only, never text.

No question, no chunk text, no collection or document names, no group names, no user id. It still
reveals which collections were skipped, so callers never show it to an end user.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ei_ai.knowledge.retrieval.scope import Skipped


@dataclass(frozen=True)
class TraceHit:
    chunk_id: UUID
    document_id: UUID
    collection_id: UUID
    retrieval_score: float  # 1 - cosine distance
    rerank_score: float | None


@dataclass(frozen=True)
class RetrievalTrace:
    principal: Literal["anonymous", "authenticated"]
    simulated: bool
    group_count: int
    retrieval: Literal["vector"]  # EA-95 adds "hybrid"
    embedding_model: str  # the ref, e.g. bge-m3@2026.10
    rerank: Literal["off", "applied", "unavailable"]
    rerank_model: str | None
    searched: tuple[UUID, ...]  # every readable collection touched (whole or via a folder)
    skipped: tuple[Skipped, ...]
    candidates: tuple[TraceHit, ...]  # the permitted candidates, in final order
    passage_chunk_ids: tuple[UUID, ...]  # the top-k
    timings_ms: Mapping[str, int]  # embed, search, rerank
