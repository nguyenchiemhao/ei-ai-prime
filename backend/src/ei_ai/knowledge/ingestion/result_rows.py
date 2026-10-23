"""Row reads and writes of the ingestion job, run inside the job's tenant transaction.

Every statement carries the explicit Organization filter (layer 1) on top of row-level security
(layer 2, D46). The job only knows the document id, which is unique, so the document id and the
Organization are the filters here.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.knowledge.ingestion.formats import DocumentFormat
from ei_ai.knowledge.ingestion.model import ExtractedDocument


@dataclass(frozen=True)
class QueuedDocument:
    id: uuid.UUID
    format: DocumentFormat
    size_bytes: int
    file_id: uuid.UUID


async def lock_queued_document(
    conn: AsyncConnection, org_id: uuid.UUID, document_id: uuid.UUID
) -> QueuedDocument | None:
    """Locks a ``queued`` document of the Organization until the transaction ends.

    Input: the job's connection, its Organization and the document id from the payload.
    Output: the document, or None when it is unknown, of another Organization, no longer
    queued or locked by another job (``SKIP LOCKED``).
    """
    result = await conn.execute(
        text(
            "SELECT id, format, size_bytes, file_id FROM documents"
            " WHERE org_id = :org AND id = :id AND status = 'queued'"
            " FOR UPDATE SKIP LOCKED"
        ),
        {"org": org_id, "id": document_id},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return QueuedDocument(
        id=row.id, format=row.format, size_bytes=row.size_bytes, file_id=row.file_id
    )


async def save_ready(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    extracted: ExtractedDocument,
) -> None:
    """Stores the chunks and marks the document ``ready`` with its text and page count.

    Input: the job's connection, its Organization, the document id and the extraction result.
    Output: None.
    """
    if extracted.chunks:
        await conn.execute(
            text(
                "INSERT INTO document_chunks (org_id, document_id, ordinal, text, page,"
                " heading_path, char_start, char_end, token_estimate)"
                " VALUES (:org, :document, :ordinal, :text, :page, :heading_path, :char_start,"
                " :char_end, :token_estimate)"
            ),
            [
                {
                    "org": org_id,
                    "document": document_id,
                    "ordinal": chunk.ordinal,
                    "text": chunk.text,
                    "page": chunk.page,
                    "heading_path": list(chunk.heading_path),
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "token_estimate": chunk.token_estimate,
                }
                for chunk in extracted.chunks
            ],
        )
    await conn.execute(
        text(
            "UPDATE documents SET status = 'ready', reason = NULL, page_count = :pages,"
            " chunk_count = :chunks, extracted_text = :text, updated_at = now(),"
            " processed_at = now()"
            " WHERE org_id = :org AND id = :id"
        ),
        {
            "pages": extracted.page_count,
            "chunks": len(extracted.chunks),
            "text": extracted.text,
            "org": org_id,
            "id": document_id,
        },
    )


async def save_outcome(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    status: str,
    reason: str,
) -> None:
    """Marks the document ``failed`` or ``not_supported`` with a reason code.

    Input: the job's connection, its Organization, the document id, the status and the reason.
    Output: None.
    """
    await conn.execute(
        text(
            "UPDATE documents SET status = :status, reason = :reason, updated_at = now(),"
            " processed_at = now()"
            " WHERE org_id = :org AND id = :id"
        ),
        {"status": status, "reason": reason, "org": org_id, "id": document_id},
    )
