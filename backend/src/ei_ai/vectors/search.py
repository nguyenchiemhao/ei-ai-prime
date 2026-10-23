"""Nearest-neighbour search in the vectors of one Organization (tenant plane).

The Organization comes from the verified context only (D32): a ``TenantContext`` in a route or a
``JobContext`` in a job; anything else raises ``TypeError``. The session must be the tenant
session of that Organization. ``NEAREST_SQL`` filters on the partition key explicitly (layer 1),
so PostgreSQL prunes the scan to the Organization's own partition; row-level security is layer 2.
The permission filter (collection, access level, groups) runs inside the same statement, so the
HNSW scan keeps going until ``k`` allowed rows are found. Nothing here logs.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text

from ei_ai.db.tenant import TenantExecutor
from ei_ai.jobs.envelope import JobContext
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.tenancy.context import TenantContext

# bge-m3 (local-models.json, ADR-001).
EMBEDDING_DIMENSIONS = 1024
MAX_K = 40

ACCESS_LEVELS = frozenset({"public", "authenticated", "restricted"})

# A module constant, so the AC4 test explains exactly the statement ``nearest`` runs. The optional
# clauses are switched by parameters (``:collections`` NULL = any collection; ``:filtered`` false =
# no access clause), so the statement and its plan stay the same.
NEAREST_SQL = (
    "SELECT id, chunk_id, document_id, collection_id,"
    " embedding <=> CAST(:q AS vector) AS distance FROM chunk_embeddings"
    " WHERE org_id = :org AND model_id = :model_id AND model_version = :model_version"
    " AND (CAST(:collections AS uuid[]) IS NULL"
    " OR collection_id = ANY(CAST(:collections AS uuid[]))"
    " OR folder_id = ANY(CAST(:folders AS uuid[])))"
    " AND (NOT :filtered OR access_level = ANY(CAST(:levels AS text[]))"
    " OR groups && CAST(:groups AS text[]))"
    " ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
)


@dataclass(frozen=True)
class VectorFilter:
    """Which vectors a caller may see (AC3).

    ``collection_ids`` None means any collection (an explicit choice; ``()`` matches nothing). An
    entry is in scope when its collection is in ``collection_ids`` or its folder is in
    ``folder_ids`` (folders need a collection list). It then matches when its access level is in
    ``access_levels`` or one of its groups is in ``groups``; with both empty nothing matches.
    """

    collection_ids: tuple[uuid.UUID, ...] | None = None
    access_levels: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    folder_ids: tuple[uuid.UUID, ...] = ()

    def __post_init__(self) -> None:
        if not ACCESS_LEVELS.issuperset(self.access_levels):
            raise ValueError("unknown access level")
        if self.collection_ids is None and self.folder_ids:
            raise ValueError("collection_ids must not be None when folder_ids are given")


@dataclass(frozen=True)
class VectorHit:
    id: uuid.UUID
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    collection_id: uuid.UUID
    distance: float  # cosine distance


def _vector_literal(query: Sequence[float]) -> str:
    if len(query) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"query must have {EMBEDDING_DIMENSIONS} dimensions")
    values = [float(value) for value in query]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("query values must be finite")
    return "[" + ",".join(repr(value) for value in values) + "]"


async def nearest(
    session: TenantExecutor,
    tenant: TenantContext | JobContext,
    query: Sequence[float],
    k: int,
    *,
    model: ModelRef,
    where: VectorFilter | None,
) -> list[VectorHit]:
    """The ``k`` vectors of the context's Organization nearest to ``query`` (cosine distance).

    Only vectors made by ``model`` count. With ``where`` the permission filter runs inside the
    query; ``where`` is required, and ``where=None`` means no permission filter and any collection
    (only for callers that have no principal).
    """
    if not isinstance(tenant, TenantContext | JobContext):
        raise TypeError(
            f"nearest needs the verified TenantContext or JobContext, got {type(tenant).__name__}"
        )
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise ValueError(f"k must be an integer from 1 to {MAX_K}")
    literal = _vector_literal(query)
    collections = where.collection_ids if where is not None else None
    params = {
        "q": literal,
        "org": tenant.org_id,
        "k": k,
        "model_id": model.model_id,
        "model_version": model.version,
        "collections": list(collections) if collections is not None else None,
        "filtered": where is not None,
        "levels": list(where.access_levels) if where is not None else [],
        "groups": list(where.groups) if where is not None else [],
        "folders": list(where.folder_ids) if where is not None else [],
    }
    # Keep scanning the HNSW index until k rows pass the filter (pgvector >= 0.8).
    await session.execute(text("SELECT set_config('hnsw.iterative_scan', 'strict_order', true)"))
    result = await session.execute(text(NEAREST_SQL), params)
    return [
        VectorHit(
            id=row.id,
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            collection_id=row.collection_id,
            distance=float(row.distance),
        )
        for row in result
    ]
