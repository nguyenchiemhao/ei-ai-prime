"""The background job that embeds a ready document into its Organization's vectors (EA-35, R8).

It runs only through ``run_tenant_job``, so every statement is inside the tenant transaction of
the Organization that queued it (D46). The payload names a document id; a document of another
Organization, or one that is not ``ready``, is not found and the job does nothing (the embedder is
not even looked up). The embedding runs without row locks; the vectors are written under a short
lock, and a document that stopped being ready (or whose chunks changed) meanwhile gets none
(``document_index_skipped``). A failure (gateway error, wrong vector shape, missing partition) is
logged and re-raised, so the transaction rolls back and the old vectors stay; there is no
automatic retry (R11). Logs carry ids, counts, the model ref and error codes only, never text
(D52).
"""

import logging
import uuid
from collections.abc import Mapping

from ei_ai.audit.events import SYSTEM_ACTOR
from ei_ai.jobs.envelope import JobContext
from ei_ai.jobs.registry import JOBS
from ei_ai.knowledge.indexing.index_rows import ready_chunks
from ei_ai.knowledge.indexing.indexer import index_chunks
from ei_ai.knowledge.ingestion.runtime import current_runtime
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError

INDEX_DOCUMENT = "knowledge.document.index"

logger = logging.getLogger("ei_ai.knowledge.indexing")


def _document_id(payload: Mapping[str, object]) -> uuid.UUID:
    """The id in ``{"document_id": "<uuid>"}``; ``ValueError`` when missing or not a UUID.

    Not imported from the ingestion job: ``ei_ai.jobs`` loads both job modules, and one importing
    the other would close an import cycle.
    """
    return uuid.UUID(str(payload.get("document_id")))


def _error_name(error: Exception) -> str:
    """The gateway's error code, else the exception class (never the message)."""
    return error.code.value if isinstance(error, ModelError) else type(error).__name__


@JOBS.register(INDEX_DOCUMENT)
async def index_document_job(ctx: JobContext, payload: Mapping[str, object]) -> None:
    """Replaces the vectors of the ready document named by ``payload``.

    Input: the job context and ``{"document_id": "<uuid>"}``.
    Output: None; ``RuntimeError`` when the runtime has no embedder, and the indexing error
    otherwise. A document that stops being ready while it is embedded gets no vectors and is
    logged as skipped.
    """
    document_id = _document_id(payload)
    conn = await ctx.session.connection()
    chunks = await ready_chunks(conn, ctx.org_id, document_id)
    if chunks is None:
        return
    embedder = current_runtime().embedder
    if embedder is None:
        raise RuntimeError("no embedder configured")
    model_ctx = ModelCallContext(org_id=ctx.org_id, actor=SYSTEM_ACTOR)
    try:
        result = await index_chunks(conn, ctx.org_id, document_id, chunks, embedder, model_ctx)
    except Exception as error:
        logger.error(
            "document_index_failed document_id=%s org_id=%s error=%s",
            document_id,
            ctx.org_id,
            _error_name(error),
        )
        raise
    if result is None:
        logger.info("document_index_skipped document_id=%s org_id=%s", document_id, ctx.org_id)
        return
    logger.info(
        "document_indexed document_id=%s org_id=%s vectors=%s model=%s",
        result.document_id,
        ctx.org_id,
        result.vectors,
        result.model,
    )
