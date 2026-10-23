"""The background job that turns a queued document into chunks (EA-33).

It runs only through ``run_tenant_job``, so every statement is inside the tenant transaction of
the Organization that queued it (D46). The payload names a document id; a document of another
Organization, or one that is not ``queued``, is not found and the job does nothing. Logs carry
ids, format, size, status, reason and error class only, never the file name or any text (D52).

``ei_ai.jobs`` imports this module when the package loads, so nothing imported at the top here may
import ``ei_ai.jobs`` back through a module that is still loading (see ``runtime.py``).
"""

import logging
import uuid
from collections.abc import Mapping

import anyio.to_thread
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.jobs.envelope import JobContext
from ei_ai.jobs.registry import JOBS
from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.model import (
    PROCESSING_ERROR,
    ExtractedDocument,
    ExtractionOutcome,
)
from ei_ai.knowledge.ingestion.result_rows import (
    QueuedDocument,
    lock_queued_document,
    save_outcome,
    save_ready,
)
from ei_ai.knowledge.ingestion.runtime import IngestionRuntime, current_runtime

INGEST_DOCUMENT = "knowledge.document.ingest"

logger = logging.getLogger("ei_ai.knowledge.ingestion")


def document_id_of(payload: Mapping[str, object]) -> uuid.UUID:
    """The document id of an ingestion payload ``{"document_id": "<uuid>"}``.

    Input: the payload. Output: the id; ``ValueError`` when it is missing or not a UUID.
    """
    return uuid.UUID(str(payload.get("document_id")))


def _log_failure(ctx: JobContext, document: QueuedDocument, error: Exception) -> None:
    """Logs an unexpected failure with ids, format, size and the error class only."""
    logger.error(
        "document_ingest_failed document_id=%s org_id=%s format=%s size_bytes=%s error=%s",
        document.id,
        ctx.org_id,
        document.format,
        document.size_bytes,
        type(error).__name__,
    )


async def _extract(
    ctx: JobContext, conn: AsyncConnection, runtime: IngestionRuntime, document: QueuedDocument
) -> ExtractedDocument:
    """Decrypts the original and extracts it in a worker thread, reporting progress.

    Input: the job context, its connection, the runtime and the locked document, whose file id
    comes from the Organization's own row; the store looks only under that Organization.
    Output: the extraction; raises ``ExtractionOutcome`` for an expected failure and the store's
    error (missing file, missing or destroyed key, foreign blob) otherwise.
    """
    data = await runtime.files.get(conn, ctx, document.file_id)

    def report(percent: int) -> None:
        runtime.progress.report(ctx, document.id, percent)

    return await anyio.to_thread.run_sync(extract_document, document.format, data, report)


async def _save(
    ctx: JobContext, conn: AsyncConnection, document: QueuedDocument, extracted: ExtractedDocument
) -> tuple[str, str | None]:
    """Saves a ready document inside a savepoint; a failure rolls it back.

    Input: the job context, its connection, the document and the extraction.
    Output: the final ``(status, reason)``: ready, or failed with ``processing_error``.
    """
    try:
        async with conn.begin_nested():
            await save_ready(conn, ctx.org_id, document.id, extracted)
    except Exception as error:
        _log_failure(ctx, document, error)
        await save_outcome(conn, ctx.org_id, document.id, "failed", PROCESSING_ERROR)
        return "failed", PROCESSING_ERROR
    return "ready", None


async def _process(
    ctx: JobContext, conn: AsyncConnection, runtime: IngestionRuntime, document: QueuedDocument
) -> tuple[str, str | None]:
    """Extracts and stores one locked document; every failure becomes a final status.

    Input: the job context, its connection, the runtime and the locked document.
    Output: the final ``(status, reason)``.
    """
    try:
        extracted = await _extract(ctx, conn, runtime, document)
    except ExtractionOutcome as outcome:
        await save_outcome(conn, ctx.org_id, document.id, outcome.status, outcome.reason)
        return outcome.status, outcome.reason
    except Exception as error:  # FileNotFound, KeyNotFound, KeyDestroyed, DecryptionFailed, ...
        _log_failure(ctx, document, error)
        await save_outcome(conn, ctx.org_id, document.id, "failed", PROCESSING_ERROR)
        return "failed", PROCESSING_ERROR
    return await _save(ctx, conn, document, extracted)


@JOBS.register(INGEST_DOCUMENT)
async def ingest_document(ctx: JobContext, payload: Mapping[str, object]) -> None:
    """Processes the queued document named by ``payload`` for the job's Organization.

    Input: the job context and ``{"document_id": "<uuid>"}``.
    Output: None; the document ends ``ready``, ``failed`` or ``not_supported``.
    """
    document_id = document_id_of(payload)
    conn = await ctx.session.connection()
    document = await lock_queued_document(conn, ctx.org_id, document_id)
    if document is None:
        return
    runtime = current_runtime()
    runtime.progress.start(ctx, document.id)
    status, reason = await _process(ctx, conn, runtime, document)
    runtime.progress.report(ctx, document.id, 100)
    logger.info(
        "document_ingested document_id=%s org_id=%s format=%s size_bytes=%s status=%s reason=%s",
        document.id,
        ctx.org_id,
        document.format,
        document.size_bytes,
        status,
        reason,
    )
