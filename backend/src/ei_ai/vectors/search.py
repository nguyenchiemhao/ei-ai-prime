"""Nearest-neighbour search in the vectors of one Organization (tenant plane).

The Organization comes from the verified context only (D32): a ``TenantContext`` in a route or a
``JobContext`` in a job; anything else raises ``TypeError``. The session must be the tenant
session of that Organization. ``NEAREST_SQL`` filters on the partition key explicitly (layer 1),
so PostgreSQL prunes the scan to the Organization's own partition; row-level security is layer 2.
Nothing here logs.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text

from ei_ai.db.tenant import TenantExecutor
from ei_ai.jobs.envelope import JobContext
from ei_ai.tenancy.context import TenantContext

# bge-m3 (local-models.json, ADR-001).
EMBEDDING_DIMENSIONS = 1024
MAX_K = 40

# A module constant, so the AC4 test explains exactly the statement ``nearest`` runs.
NEAREST_SQL = (
    "SELECT id, embedding <=> CAST(:q AS vector) AS distance FROM chunk_embeddings"
    " WHERE org_id = :org ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
)


@dataclass(frozen=True)
class VectorHit:
    id: uuid.UUID
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
) -> list[VectorHit]:
    """The ``k`` vectors of the context's Organization nearest to ``query`` (cosine distance)."""
    if not isinstance(tenant, TenantContext | JobContext):
        raise TypeError(
            f"nearest needs the verified TenantContext or JobContext, got {type(tenant).__name__}"
        )
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise ValueError(f"k must be an integer from 1 to {MAX_K}")
    literal = _vector_literal(query)
    result = await session.execute(text(NEAREST_SQL), {"q": literal, "org": tenant.org_id, "k": k})
    return [VectorHit(id=row.id, distance=float(row.distance)) for row in result]
