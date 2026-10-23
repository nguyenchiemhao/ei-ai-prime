"""Loading the passages (chunk text and location) of chosen chunks (EA-36).

Org-scoped, ready documents only, and only collections the caller has already resolved as readable
(defence in depth on top of the vector filter, D46).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_PASSAGES = """
SELECT c.id AS chunk_id, c.document_id, d.collection_id, d.folder_id, d.name AS document_name,
       c.page, c.heading_path, c.ordinal, c.text
FROM document_chunks c
JOIN documents d ON d.org_id = c.org_id AND d.id = c.document_id
WHERE c.org_id = :org AND d.org_id = :org
  AND c.id = ANY(CAST(:ids AS uuid[]))
  AND d.status = 'ready'
  AND d.collection_id = ANY(CAST(:readable AS uuid[]))
"""


@dataclass(frozen=True)
class PassageRow:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    collection_id: uuid.UUID
    folder_id: uuid.UUID
    document_name: str
    page: int | None
    heading_path: tuple[str, ...]
    ordinal: int
    text: str


async def load_passages(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    chunk_ids: Sequence[uuid.UUID],
    readable_collection_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, PassageRow]:
    """The passages of ``chunk_ids`` that are in a ready document of a readable collection.

    Other ids (unknown, of another Organization, unready, unreadable) are simply absent. Folder
    narrowing is not done here: the vector filter's folder clause selected ``chunk_ids``.
    """
    result = await conn.execute(
        text(_PASSAGES),
        {"org": org_id, "ids": list(chunk_ids), "readable": list(readable_collection_ids)},
    )
    return {
        row.chunk_id: PassageRow(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            collection_id=row.collection_id,
            folder_id=row.folder_id,
            document_name=row.document_name,
            page=row.page,
            heading_path=tuple(row.heading_path),
            ordinal=row.ordinal,
            text=row.text,
        )
        for row in result
    }
