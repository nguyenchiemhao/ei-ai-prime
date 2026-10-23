"""Test-only helpers: collections, folders and indexed documents for the retrieval tests (EA-36).

Everything runs inside the caller's ``tenant_transaction`` of ``org``. Never imported by ``src``.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.knowledge.indexing.indexer import index_document
from ei_ai.model_gateway.context import ModelCallContext
from support.fake_embedder import FakeEmbedder
from support.tenants import OrgRows


async def add_workspace(conn: AsyncConnection, org: OrgRows, name: str) -> uuid.UUID:
    """Another Workspace of the same Organization."""
    workspace_id = uuid.uuid4()
    await conn.execute(
        text("INSERT INTO workspaces (id, org_id, name) VALUES (:id, :org, :name)"),
        {"id": workspace_id, "org": org.org_id, "name": name},
    )
    return workspace_id


async def add_folder(
    conn: AsyncConnection,
    org: OrgRows,
    collection_id: uuid.UUID,
    *,
    parent_id: uuid.UUID | None = None,
    name: str,
) -> uuid.UUID:
    """A folder under ``parent_id`` (depth parent + 1) or at the top of the collection."""
    folder_id = uuid.uuid4()
    depth = 1
    if parent_id is not None:
        depth = (
            await conn.execute(
                text("SELECT depth + 1 FROM folders WHERE org_id = :org AND id = :id"),
                {"org": org.org_id, "id": parent_id},
            )
        ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO folders (id, org_id, collection_id, parent_id, name, depth)"
            " VALUES (:id, :org, :collection, :parent, :name, :depth)"
        ),
        {
            "id": folder_id,
            "org": org.org_id,
            "collection": collection_id,
            "parent": parent_id,
            "name": name,
            "depth": depth,
        },
    )
    return folder_id


async def add_collection(
    conn: AsyncConnection,
    org: OrgRows,
    *,
    name: str,
    access_level: str,
    groups: Sequence[str] = (),
    workspace_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A collection (default: the org's fixture Workspace) and a depth-1 folder for documents."""
    collection_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO collections (id, org_id, workspace_id, name, access_level, groups)"
            " VALUES (:id, :org, :ws, :name, :level, :groups)"
        ),
        {
            "id": collection_id,
            "org": org.org_id,
            "ws": workspace_id or org.workspace_id,
            "name": name,
            "level": access_level,
            "groups": list(groups),
        },
    )
    folder_id = await add_folder(conn, org, collection_id, name="Documents")
    return collection_id, folder_id


async def add_indexed_document(
    conn: AsyncConnection,
    org: OrgRows,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    chunk_texts: Sequence[str],
    *,
    embedder: FakeEmbedder,
) -> uuid.UUID:
    """A ``ready`` document with one chunk per text, indexed through the real indexer."""
    document_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
            " size_bytes, status, page_count, chunk_count, uploaded_by, file_id)"
            " VALUES (:id, :org, :collection, :folder, :name, 'txt', 100, 'ready', 1, :count,"
            " :user, gen_random_uuid())"
        ),
        {
            "id": document_id,
            "org": org.org_id,
            "collection": collection_id,
            "folder": folder_id,
            "name": f"doc-{document_id.hex[:8]}.txt",
            "count": len(chunk_texts),
            "user": org.user_id,
        },
    )
    for ordinal, chunk in enumerate(chunk_texts):
        await conn.execute(
            text(
                "INSERT INTO document_chunks (org_id, document_id, ordinal, text, page,"
                " heading_path, char_start, char_end, token_estimate)"
                " VALUES (:org, :document, :ordinal, :text, :page, :heading, 0, :end, 1)"
            ),
            {
                "org": org.org_id,
                "document": document_id,
                "ordinal": ordinal,
                "text": chunk,
                "page": ordinal + 1,
                "heading": ["Part", f"Section {ordinal}"],
                "end": len(chunk) + 1,
            },
        )
    ctx = ModelCallContext(org_id=org.org_id, actor="platform-operator")
    await index_document(conn, org.org_id, document_id, embedder, ctx)
    return document_id
