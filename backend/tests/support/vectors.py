"""Test-only helper: a complete ``chunk_embeddings`` row for a fixture Organization."""

import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.model_gateway.refs import ModelRef
from support.tenants import OrgRows

DEFAULT_MODEL = ModelRef("bge-m3", "2026.10")


def _literal(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


async def insert_vector(
    conn: AsyncConnection,
    org: OrgRows,
    embedding: Sequence[float],
    *,
    model: ModelRef = DEFAULT_MODEL,
    access_level: str = "authenticated",
    groups: Sequence[str] = (),
    chunk_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Inserts one vector in the org's fixture document and returns its id.

    ``conn`` must be inside ``tenant_transaction`` of ``org``. Without ``chunk_id`` a fresh chunk
    is created first (a chunk has at most one vector). ``collection_id`` and ``folder_id`` default
    to
    the org's fixture collection and folder.
    """
    params = {"org": org.org_id, "document": org.document_id}
    if chunk_id is None:
        chunk_id = (
            await conn.execute(
                text(
                    "INSERT INTO document_chunks (org_id, document_id, ordinal, text, char_start,"
                    " char_end, token_estimate) VALUES (:org, :document,"
                    " (SELECT coalesce(max(ordinal) + 1, 0) FROM document_chunks"
                    "  WHERE org_id = :org AND document_id = :document), 'qa', 0, 2, 1)"
                    " RETURNING id"
                ),
                params,
            )
        ).scalar_one()
    result = await conn.execute(
        text(
            "INSERT INTO chunk_embeddings (org_id, embedding, chunk_id, document_id, workspace_id,"
            " collection_id, folder_id, access_level, groups, model_id, model_version)"
            " VALUES (:org, CAST(:v AS vector), :chunk, :document, :ws, :collection, :folder,"
            " :level, :groups, :model_id, :model_version) RETURNING id"
        ),
        {
            **params,
            "v": _literal(embedding),
            "chunk": chunk_id,
            "ws": org.workspace_id,
            "collection": collection_id or org.collection_id,
            "folder": folder_id or org.folder_id,
            "level": access_level,
            "groups": list(groups),
            "model_id": model.model_id,
            "model_version": model.version,
        },
    )
    vector_id: uuid.UUID = result.scalar_one()
    return vector_id
