"""Vector search with both isolation layers (D46)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from stack_spike.tenant import tenant_transaction
from stack_spike.vectors import to_vector_literal

# pgvector hnsw.ef_search default: an HNSW scan returns at most this many candidates. Larger k or
# post-filtering (KB-05) needs hnsw.ef_search / hnsw.iterative_scan set inside the transaction.
MAX_K = 40


@dataclass(frozen=True)
class ChunkHit:
    org_id: uuid.UUID
    id: uuid.UUID
    document_id: uuid.UUID
    distance: float


def search_chunks(
    conn: psycopg.Connection, org_id: uuid.UUID, query: Sequence[float], k: int = 5
) -> list[ChunkHit]:
    """Return the k nearest chunks of one Organization (cosine distance).

    Layer 1: the explicit `WHERE org_id` filter, which also prunes the search to that
    Organization's partition and HNSW index. Layer 2: row-level security through the tenant context.
    """
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be between 1 and {MAX_K}, got {k}")
    literal = to_vector_literal(query)
    with tenant_transaction(conn, org_id):
        rows = conn.execute(
            "SELECT org_id, id, document_id, embedding <=> %s::vector AS distance"
            " FROM chunk_embeddings WHERE org_id = %s"
            " ORDER BY embedding <=> %s::vector LIMIT %s",
            (literal, org_id, literal, k),
        ).fetchall()
    return [ChunkHit(*row) for row in rows]
