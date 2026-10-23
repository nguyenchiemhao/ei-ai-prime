"""Row reads and writes of documents on the request path, run inside the caller's tenant
transaction.

Every statement carries the explicit Organization and collection filters (layer 1) on top of
row-level security (layer 2, D46). The one statement without a collection filter is the quota,
which is the Organization's total by definition. The ingestion job has its own statements in
``ingestion/result_rows.py``.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

PREVIEW_CHARACTERS = 100_000

_COLUMNS = (
    "d.id, d.folder_id, d.name, d.format, d.size_bytes, d.status, d.reason, d.page_count,"
    " d.uploaded_by, u.display_name AS uploader_name, d.created_at, d.updated_at"
)
_FROM = " FROM documents d LEFT JOIN users u ON u.org_id = d.org_id AND u.id = d.uploaded_by"


@dataclass(frozen=True)
class DocumentRow:
    id: uuid.UUID
    folder_id: uuid.UUID
    name: str
    format: str
    size_bytes: int
    status: str
    reason: str | None
    page_count: int | None
    uploaded_by: uuid.UUID | None
    uploader_name: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentText:
    text: str
    total_characters: int


@dataclass(frozen=True)
class ChunkRow:
    ordinal: int
    text: str
    page: int | None
    heading_path: tuple[str, ...]
    char_start: int
    char_end: int
    token_estimate: int


def _to_row(row: Any) -> DocumentRow:
    return DocumentRow(**dict(row._mapping))


async def organization_size_bytes(conn: AsyncConnection, org_id: uuid.UUID) -> int:
    """The total size of the Organization's stored originals (the quota base).

    Named exception to the org + collection filter rule: the quota is the Organization's total.
    """
    result = await conn.execute(
        text("SELECT COALESCE(sum(size_bytes), 0) FROM documents WHERE org_id = :org"),
        {"org": org_id},
    )
    return int(result.scalar_one())


async def insert_document(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    name: str,
    file_format: str,
    size_bytes: int,
    uploaded_by: uuid.UUID,
    file_id: uuid.UUID,
) -> DocumentRow:
    """Insert a ``queued`` document with already validated values and the id of its stored
    original, and return it."""
    result = await conn.execute(
        text(
            "INSERT INTO documents (org_id, collection_id, folder_id, name, format, size_bytes,"
            " status, uploaded_by, file_id)"
            " VALUES (:org, :collection, :folder, :name, :format, :size, 'queued', :user, :file)"
            " RETURNING id"
        ),
        {
            "org": org_id,
            "collection": collection_id,
            "folder": folder_id,
            "name": name,
            "format": file_format,
            "size": size_bytes,
            "user": uploaded_by,
            "file": file_id,
        },
    )
    document_id = result.scalar_one()
    found = await find_document_row(conn, org_id, collection_id, document_id)
    assert found is not None
    return found


async def list_document_rows(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID | None,
) -> list[DocumentRow]:
    """The documents of a collection, or of one folder of it, newest first."""
    result = await conn.execute(
        text(
            f"SELECT {_COLUMNS}{_FROM} WHERE d.org_id = :org AND d.collection_id = :collection"
            " AND (CAST(:folder AS uuid) IS NULL OR d.folder_id = CAST(:folder AS uuid))"
            " ORDER BY d.created_at DESC, d.id DESC"
        ),
        {"org": org_id, "collection": collection_id, "folder": folder_id},
    )
    return [_to_row(row) for row in result]


async def find_document_row(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> DocumentRow | None:
    """One document of the collection, else None; ``for_update`` locks the row until the
    transaction ends."""
    result = await conn.execute(
        text(
            f"SELECT {_COLUMNS}{_FROM} WHERE d.org_id = :org AND d.collection_id = :collection"
            " AND d.id = :id" + (" FOR UPDATE OF d" if for_update else "")
        ),
        {"org": org_id, "collection": collection_id, "id": document_id},
    )
    row = result.one_or_none()
    return None if row is None else _to_row(row)


async def read_document_text(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentText:
    """The first ``PREVIEW_CHARACTERS`` characters of the extracted text and its full length
    (a missing text reads as empty)."""
    result = await conn.execute(
        text(
            "SELECT left(COALESCE(extracted_text, ''), :limit) AS preview,"
            " char_length(COALESCE(extracted_text, '')) AS total FROM documents"
            " WHERE org_id = :org AND collection_id = :collection AND id = :id"
        ),
        {
            "org": org_id,
            "collection": collection_id,
            "id": document_id,
            "limit": PREVIEW_CHARACTERS,
        },
    )
    row = result.one()
    return DocumentText(text=row.preview, total_characters=row.total)


async def list_chunk_rows(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID, document_id: uuid.UUID
) -> list[ChunkRow]:
    """The chunks of a document of the collection, by ordinal."""
    result = await conn.execute(
        text(
            "SELECT c.ordinal, c.text, c.page, c.heading_path, c.char_start, c.char_end,"
            " c.token_estimate FROM document_chunks c"
            " JOIN documents d ON d.org_id = c.org_id AND d.id = c.document_id"
            " WHERE c.org_id = :org AND d.org_id = :org AND d.collection_id = :collection"
            " AND c.document_id = :id ORDER BY c.ordinal"
        ),
        {"org": org_id, "collection": collection_id, "id": document_id},
    )
    return [
        ChunkRow(
            ordinal=row.ordinal,
            text=row.text,
            page=row.page,
            heading_path=tuple(row.heading_path),
            char_start=row.char_start,
            char_end=row.char_end,
            token_estimate=row.token_estimate,
        )
        for row in result
    ]


async def delete_document_row(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID, document_id: uuid.UUID
) -> uuid.UUID | None:
    """Delete a document; its chunks go with it (foreign key cascade). Returns the file id of
    its stored original, or None when no row was deleted."""
    result = await conn.execute(
        text(
            "DELETE FROM documents WHERE org_id = :org AND collection_id = :collection AND id = :id"
            " RETURNING file_id"
        ),
        {"org": org_id, "collection": collection_id, "id": document_id},
    )
    file_id: uuid.UUID | None = result.scalar_one_or_none()
    return file_id


async def list_document_file_ids(
    conn: AsyncConnection, org_id: uuid.UUID, collection_id: uuid.UUID
) -> list[uuid.UUID]:
    """The file ids of the stored originals of every document of the collection."""
    result = await conn.execute(
        text("SELECT file_id FROM documents WHERE org_id = :org AND collection_id = :collection"),
        {"org": org_id, "collection": collection_id},
    )
    return [row.file_id for row in result]
