"""Row reads and writes of indexing, run inside the caller's tenant transaction (EA-35).

Every statement carries the explicit Organization filter (layer 1) on top of row-level security
(layer 2, D46), and queries the parent ``chunk_embeddings``, never a partition. The vectors copy
the permission metadata of the collection (R4), so a query can filter inside the vector search.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.model_gateway.refs import ModelRef


@dataclass(frozen=True)
class IndexedDocument:
    """A locked ready document and the metadata its vectors carry."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    collection_id: uuid.UUID
    folder_id: uuid.UUID
    access_level: str
    groups: tuple[str, ...]


async def ready_chunks(
    conn: AsyncConnection, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]] | None:
    """The ``(chunk id, text)`` pairs of a ``ready`` document of the Organization, by ordinal.

    Plain reads that take no row lock, so the slow embedding that follows blocks no access
    change, collection edit or delete (Controller Ruling F1). Output: the pairs, or None when the
    document is unknown, of another Organization or not ready.
    """
    result = await conn.execute(
        text("SELECT 1 FROM documents WHERE org_id = :org AND id = :id AND status = 'ready'"),
        {"org": org_id, "id": document_id},
    )
    if result.first() is None:
        return None
    return await chunk_texts(conn, org_id, document_id)


async def lock_ready_document(
    conn: AsyncConnection, org_id: uuid.UUID, document_id: uuid.UUID
) -> IndexedDocument | None:
    """Locks a ``ready`` document of the Organization and shares its collection row until the
    transaction ends, and reads the collection's current access metadata under that lock.

    Taken only for the short vector write after embedding. An access change either commits
    first (then this waits and reads the new values) or waits for this write and then rewrites
    the vectors in its own transaction, so no vector keeps a stale access level (R10, R23).

    Input: the connection, its Organization and the document id.
    Output: the document with its collection metadata, or None when it is unknown, of another
    Organization or not ready.
    """
    result = await conn.execute(
        text(
            "SELECT d.id, c.workspace_id, d.collection_id, d.folder_id, c.access_level, c.groups"
            " FROM documents d JOIN collections c"
            " ON c.org_id = d.org_id AND c.id = d.collection_id"
            " WHERE d.org_id = :org AND c.org_id = :org AND d.id = :id AND d.status = 'ready'"
            " FOR NO KEY UPDATE OF d FOR SHARE OF c"
        ),
        {"org": org_id, "id": document_id},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return IndexedDocument(
        id=row.id,
        workspace_id=row.workspace_id,
        collection_id=row.collection_id,
        folder_id=row.folder_id,
        access_level=row.access_level,
        groups=tuple(row.groups),
    )


async def chunk_texts(
    conn: AsyncConnection, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    """The ``(chunk id, text)`` pairs of a document of the Organization, by ordinal."""
    result = await conn.execute(
        text(
            "SELECT id, text FROM document_chunks"
            " WHERE org_id = :org AND document_id = :document ORDER BY ordinal"
        ),
        {"org": org_id, "document": document_id},
    )
    return [(row.id, row.text) for row in result]


async def chunk_ids(
    conn: AsyncConnection, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[uuid.UUID]:
    """The chunk ids of a document of the Organization, by ordinal."""
    result = await conn.execute(
        text(
            "SELECT id FROM document_chunks"
            " WHERE org_id = :org AND document_id = :document ORDER BY ordinal"
        ),
        {"org": org_id, "document": document_id},
    )
    return [row.id for row in result]


def _literal(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


async def replace_vectors(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    document: IndexedDocument,
    vectors: Sequence[tuple[uuid.UUID, Sequence[float]]],
    ref: ModelRef,
) -> int:
    """Deletes the document's vectors, then inserts one per ``(chunk id, vector)`` pair.

    Input: the connection, its Organization, the locked document, the checked vectors and the
    embedding model that made them. Output: the number of vectors written.
    """
    await conn.execute(
        text("DELETE FROM chunk_embeddings WHERE org_id = :org AND document_id = :document"),
        {"org": org_id, "document": document.id},
    )
    if not vectors:
        return 0
    await conn.execute(
        text(
            "INSERT INTO chunk_embeddings (org_id, embedding, chunk_id, document_id, workspace_id,"
            " collection_id, folder_id, access_level, groups, model_id, model_version)"
            " VALUES (:org, CAST(:embedding AS vector), :chunk, :document, :workspace,"
            " :collection, :folder, :level, :groups, :model_id, :model_version)"
        ),
        [
            {
                "org": org_id,
                "embedding": _literal(vector),
                "chunk": chunk_id,
                "document": document.id,
                "workspace": document.workspace_id,
                "collection": document.collection_id,
                "folder": document.folder_id,
                "level": document.access_level,
                "groups": list(document.groups),
                "model_id": ref.model_id,
                "model_version": ref.version,
            }
            for chunk_id, vector in vectors
        ],
    )
    return len(vectors)


async def sync_collection_access(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    collection_id: uuid.UUID,
    access_level: str,
    groups: Sequence[str],
) -> int:
    """Copies a collection's new access level and groups onto all its vectors (R10, R23).

    Runs in the access-change transaction, so a query never sees the new collection with old
    vector permissions. Input: the connection, its Organization, the collection and its new
    metadata. Output: the number of vectors updated.
    """
    result = await conn.execute(
        text(
            "UPDATE chunk_embeddings SET access_level = :level, groups = :groups"
            " WHERE org_id = :org AND collection_id = :collection"
        ),
        {
            "org": org_id,
            "collection": collection_id,
            "level": access_level,
            "groups": list(groups),
        },
    )
    return result.rowcount


async def ready_document_ids(conn: AsyncConnection, org_id: uuid.UUID) -> list[uuid.UUID]:
    """The ids of the Organization's ready documents, oldest first."""
    result = await conn.execute(
        text(
            "SELECT id FROM documents WHERE org_id = :org AND status = 'ready'"
            " ORDER BY created_at, id"
        ),
        {"org": org_id},
    )
    return [row.id for row in result]
