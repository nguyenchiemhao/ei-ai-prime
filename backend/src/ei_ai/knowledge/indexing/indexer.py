"""Indexing of one document: read the chunks, embed them, then write the vectors (EA-35).

Three phases in the caller's tenant transaction (Controller Ruling F1, keeps the R23 invariant):
1. read the ready document's chunks without row locks;
2. embed them, still without row locks, so a slow model never blocks an access change, a
   collection edit or a delete;
3. lock the document and share its collection row, re-read the collection's current access
   metadata under that lock and replace the vectors. When the document is no longer ready or its
   chunks changed during embedding, nothing is written and the result is None.

A failure leaves the old vectors in place. Idempotent: running it twice leaves exactly one vector
per chunk. A document with no chunks ends with no vectors.

``ei_ai.jobs`` loads this module through the index job, so the embedder protocol is imported for
type checking only: ``embedder`` imports ``ei_ai.vectors.search``, which imports ``ei_ai.jobs``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.knowledge.indexing.index_rows import (
    chunk_ids,
    lock_ready_document,
    ready_chunks,
    replace_vectors,
)
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.refs import ModelRef

if TYPE_CHECKING:
    from ei_ai.knowledge.indexing.embedder import ChunkEmbedder


@dataclass(frozen=True)
class IndexResult:
    document_id: uuid.UUID
    vectors: int
    model: ModelRef


async def index_chunks(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    chunks: Sequence[tuple[uuid.UUID, str]],
    embedder: ChunkEmbedder,
    ctx: ModelCallContext,
) -> IndexResult | None:
    """Embeds ``chunks`` (read by ``ready_chunks``), then writes them under the document lock.

    Input: the connection, its Organization, the document id, its ``(chunk id, text)`` pairs, the
    embedder and the model call context. Output: the number of vectors written and the model, or
    None when the document stopped being ready or its chunks changed while it was embedded
    (nothing written); embedder errors pass through.
    """
    vectors = await embedder.embed(ctx, [chunk_text for _, chunk_text in chunks])
    pairs = [(chunk_id, vector) for (chunk_id, _), vector in zip(chunks, vectors, strict=True)]
    document = await lock_ready_document(conn, org_id, document_id)
    if document is None:
        return None
    if await chunk_ids(conn, org_id, document_id) != [chunk_id for chunk_id, _ in chunks]:
        return None
    count = await replace_vectors(conn, org_id, document, pairs, embedder.ref)
    return IndexResult(document_id=document.id, vectors=count, model=embedder.ref)


async def index_document(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    embedder: ChunkEmbedder,
    ctx: ModelCallContext,
) -> IndexResult | None:
    """Reads the ready document's chunks, then indexes them (``index_chunks``).

    Output: the result, or None when the document is unknown, of another Organization or not
    ready (the embedder is not called), or stopped being ready while it was embedded.
    """
    chunks = await ready_chunks(conn, org_id, document_id)
    if chunks is None:
        return None
    return await index_chunks(conn, org_id, document_id, chunks, embedder, ctx)
