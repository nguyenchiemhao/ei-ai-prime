"""Counts behind ``ei-ai index status`` (EA-35), read inside the caller's tenant transaction.

Every statement carries the explicit Organization filter on top of row-level security (D46) and
reads the parent ``chunk_embeddings``, never a partition.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.db.tenant import TenantExecutor
from ei_ai.model_gateway.refs import ModelRef

# Per ready document: its chunks, the vectors of the current model and the vectors of any other.
_COUNTS_SQL = (
    "WITH per_document AS ("
    " SELECT d.id,"
    "  (SELECT count(*) FROM document_chunks c"
    "   WHERE c.org_id = :org AND c.document_id = d.id) AS chunks,"
    "  (SELECT count(*) FROM chunk_embeddings e"
    "   WHERE e.org_id = :org AND e.document_id = d.id"
    "   AND e.model_id = :model_id AND e.model_version = :model_version) AS current_vectors,"
    "  (SELECT count(*) FROM chunk_embeddings e"
    "   WHERE e.org_id = :org AND e.document_id = d.id"
    "   AND (e.model_id <> :model_id OR e.model_version <> :model_version)) AS other_vectors"
    " FROM documents d WHERE d.org_id = :org AND d.status = 'ready'"
    " AND (CAST(:document AS uuid) IS NULL OR d.id = CAST(:document AS uuid)))"
    " SELECT count(*) AS ready_documents,"
    " count(*) FILTER (WHERE current_vectors = chunks AND other_vectors = 0) AS indexed,"
    " count(*) FILTER (WHERE other_vectors > 0) AS stale,"
    " coalesce(sum(current_vectors), 0) AS vectors FROM per_document"
)


@dataclass(frozen=True)
class IndexCounts:
    ready_documents: int
    indexed: int
    not_indexed: int
    stale: int
    vectors: int


async def index_counts(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    ref: ModelRef,
    document_id: uuid.UUID | None = None,
) -> IndexCounts | None:
    """How many ready documents of the Organization are indexed with ``ref``.

    ``indexed``: every chunk has a vector of ``ref``. ``stale``: the document has a vector of
    another model. ``not_indexed``: ready documents that are not ``indexed``. ``vectors``: the
    vectors of ``ref``. With ``document_id`` only that document counts; None when it does not
    exist in the Organization.
    """
    if document_id is not None:
        found = await conn.execute(
            text("SELECT 1 FROM documents WHERE org_id = :org AND id = :id"),
            {"org": org_id, "id": document_id},
        )
        if found.first() is None:
            return None
    row = (
        await conn.execute(
            text(_COUNTS_SQL),
            {
                "org": org_id,
                "document": str(document_id) if document_id is not None else None,
                "model_id": ref.model_id,
                "model_version": ref.version,
            },
        )
    ).one()
    return IndexCounts(
        ready_documents=row.ready_documents,
        indexed=row.indexed,
        not_indexed=row.ready_documents - row.indexed,
        stale=row.stale,
        vectors=int(row.vectors),
    )


async def chunk_ordinals(
    conn: TenantExecutor, org_id: uuid.UUID, chunk_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """The ordinal of each chunk of the Organization among ``chunk_ids``."""
    result = await conn.execute(
        text("SELECT id, ordinal FROM document_chunks WHERE org_id = :org AND id = ANY(:ids)"),
        {"org": org_id, "ids": chunk_ids},
    )
    return {row.id: row.ordinal for row in result}
