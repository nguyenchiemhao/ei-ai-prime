"""Permission-filtered retrieval (EA-36, spec section 4): the shared API of answers, chat and
evaluation.

Steps: validate; embed the question before any statement; resolve the scope (nothing readable =
no vector query); the nearest permitted chunks, the permission filter inside the index query (AC4);
load their passages (a second permission check); optionally rerank the permitted texts; cut to k.
Runs inside the caller's tenant transaction with plain SELECTs only. Logs ids, counts, codes and
timings only, never the question or any text (D52).
"""

import logging
import math
import time
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.db.tenant import TenantExecutor
from ei_ai.jobs.envelope import JobContext
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
from ei_ai.knowledge.indexing.query import embed_query
from ei_ai.knowledge.retrieval.access import permission_filter
from ei_ai.knowledge.retrieval.passage_rows import PassageRow, load_passages
from ei_ai.knowledge.retrieval.principal import AnonymousPrincipal, RetrievalPrincipal
from ei_ai.knowledge.retrieval.reranker import Reranker, RerankShapeError
from ei_ai.knowledge.retrieval.scope import KnowledgeScope, ResolvedScope, resolve_scope
from ei_ai.knowledge.retrieval.trace import RetrievalTrace, TraceHit
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.tenancy.context import TenantContext
from ei_ai.vectors.search import nearest

logger = logging.getLogger("ei_ai.knowledge.retrieval")

CANDIDATES = 20
DEFAULT_K = 4
MAX_K = 10
MAX_QUESTION_CHARS = 2000

RerankStatus = Literal["off", "applied", "unavailable"]


@dataclass(frozen=True)
class Passage:
    chunk_id: UUID
    document_id: UUID
    collection_id: UUID
    folder_id: UUID
    document_name: str
    page: int | None
    heading_path: tuple[str, ...]
    ordinal: int
    text: str
    retrieval_score: float
    rerank_score: float | None


@dataclass(frozen=True)
class RetrievalResult:
    passages: tuple[Passage, ...]
    trace: RetrievalTrace


@dataclass(frozen=True)
class _Ranked:
    row: PassageRow
    retrieval_score: float
    rerank_score: float | None = None


def _validated_question(question: str, k: int) -> str:
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise ValueError(f"k must be an integer from 1 to {MAX_K}")
    stripped = question.strip() if isinstance(question, str) else ""
    if not 1 <= len(stripped) <= MAX_QUESTION_CHARS:
        raise ValueError(f"question must be 1 to {MAX_QUESTION_CHARS} characters")
    return stripped


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


async def _candidates(
    session: TenantExecutor,
    tenant: TenantContext | JobContext,
    vector: list[float],
    principal: RetrievalPrincipal,
    resolved: ResolvedScope,
    model: ModelRef,
) -> list[tuple[UUID, float]]:
    """The permitted candidate chunks, best first, with ``1 - cosine distance``.

    The seam EA-95 extends with keyword candidates and RRF. The folder clause of the filter, not
    the passage load, is what narrows a folder scope.
    """
    where = permission_filter(principal, resolved.searched_collection_ids, resolved.folder_ids)
    hits = await nearest(session, tenant, vector, CANDIDATES, model=model, where=where)
    return [(hit.chunk_id, 1.0 - hit.distance) for hit in hits]


async def _rerank(
    reranker: Reranker | None,
    ctx: ModelCallContext,
    question: str,
    ranked: list[_Ranked],
) -> tuple[list[_Ranked], RerankStatus]:
    """Reorder by rerank score (ties: retrieval score). A failure keeps the vector order."""
    if reranker is None:
        return ranked, "off"
    if not ranked:
        return ranked, "off"  # nothing to score: the reranker is not called
    try:
        scores = await reranker.rerank(ctx, question, [item.row.text for item in ranked])
        if len(scores) != len(ranked) or not all(math.isfinite(score) for score in scores):
            raise RerankShapeError
    except (ModelError, RerankShapeError) as error:
        code = str(error.code) if isinstance(error, ModelError) else type(error).__name__
        logger.warning("retrieval_rerank_failed org_id=%s error=%s", ctx.org_id, code)
        return ranked, "unavailable"
    scored = sorted(
        zip((float(score) for score in scores), ranked, strict=True),
        key=lambda pair: (-pair[0], -pair[1].retrieval_score),
    )
    return [replace(item, rerank_score=score) for score, item in scored], "applied"


def _passage(item: _Ranked) -> Passage:
    row = item.row
    return Passage(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        collection_id=row.collection_id,
        folder_id=row.folder_id,
        document_name=row.document_name,
        page=row.page,
        heading_path=row.heading_path,
        ordinal=row.ordinal,
        text=row.text,
        retrieval_score=item.retrieval_score,
        rerank_score=item.rerank_score,
    )


def _hit(item: _Ranked) -> TraceHit:
    return TraceHit(
        chunk_id=item.row.chunk_id,
        document_id=item.row.document_id,
        collection_id=item.row.collection_id,
        retrieval_score=item.retrieval_score,
        rerank_score=item.rerank_score,
    )


async def retrieve(
    session: TenantExecutor,
    tenant: TenantContext | JobContext,
    question: str,
    principal: RetrievalPrincipal,
    scope: KnowledgeScope,
    *,
    embedder: ChunkEmbedder,
    ctx: ModelCallContext,
    reranker: Reranker | None = None,
    k: int = DEFAULT_K,
) -> RetrievalResult:
    """The top ``k`` passages of ``scope`` that ``principal`` may read, best first, and the trace.

    ``ValueError`` for an empty or over-long question or ``k`` outside 1-10; embedder errors
    (``ModelError``) pass through before anything is read. The Organization is the verified
    ``tenant``'s; ``session`` is its tenant transaction.
    """
    started = time.perf_counter()
    stripped = _validated_question(question, k)
    vector = await embed_query(embedder, ctx, stripped)
    embed_ms = _ms(started)

    search_start = time.perf_counter()
    conn = session if isinstance(session, AsyncConnection) else await session.connection()
    resolved = await resolve_scope(conn, tenant.org_id, scope, principal)
    ranked: list[_Ranked] = []
    if resolved.searched_collection_ids or resolved.folder_ids:
        candidates = await _candidates(session, tenant, vector, principal, resolved, embedder.ref)
        chunk_ids = [chunk for chunk, _ in candidates]
        # Only chunks the filtered query returned; the folder narrowing came from its filter.
        rows = await load_passages(conn, tenant.org_id, chunk_ids, resolved.readable_collection_ids)
        ranked = [_Ranked(rows[chunk], score) for chunk, score in candidates if chunk in rows]
    search_ms = _ms(search_start)

    rerank_start = time.perf_counter()
    ranked, status = await _rerank(reranker, ctx, stripped, ranked)
    rerank_ms = _ms(rerank_start) if reranker is not None else 0

    top = ranked[:k]
    anonymous = isinstance(principal, AnonymousPrincipal)
    trace = RetrievalTrace(
        principal="anonymous" if anonymous else "authenticated",
        simulated=principal.simulated,
        group_count=0 if isinstance(principal, AnonymousPrincipal) else len(principal.groups),
        retrieval="vector",
        embedding_model=str(embedder.ref),
        rerank=status,
        rerank_model=str(reranker.ref) if reranker is not None else None,
        searched=resolved.readable_collection_ids,
        skipped=resolved.skipped,
        candidates=tuple(_hit(item) for item in ranked),
        passage_chunk_ids=tuple(item.row.chunk_id for item in top),
        timings_ms={"embed": embed_ms, "search": search_ms, "rerank": rerank_ms},
    )
    logger.info(
        "retrieval_done org_id=%s principal=%s simulated=%s groups=%d searched=%d skipped=%d"
        " candidates=%d passages=%d retrieval=vector rerank=%s elapsed_ms=%d",
        tenant.org_id,
        trace.principal,
        "yes" if trace.simulated else "no",
        trace.group_count,
        len(trace.searched),
        len(trace.skipped),
        len(trace.candidates),
        len(top),
        status,
        _ms(started),
    )
    return RetrievalResult(passages=tuple(_passage(item) for item in top), trace=trace)
