"""Row reads and writes of collections, run inside the caller's tenant transaction.

Every statement carries the explicit Organization and Workspace filters (layer 1) on top of
row-level security (layer 2, D46). Shared by the knowledge service and the demo seed.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class CollectionRow:
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    subtitle: str | None
    access_level: str
    groups: tuple[str, ...]
    local_only: bool
    created_at: datetime
    updated_at: datetime


def _to_row(row: Any) -> CollectionRow:
    values = dict(row._mapping)
    values["groups"] = tuple(values["groups"])
    return CollectionRow(**values)


async def list_collection_rows(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[CollectionRow]:
    """The collections of one Workspace, by name ignoring case."""
    result = await conn.execute(
        text(
            "SELECT id, workspace_id, name, subtitle, access_level, groups, local_only,"
            " created_at, updated_at FROM collections"
            " WHERE org_id = :org AND workspace_id = :ws ORDER BY lower(name), id"
        ),
        {"org": org_id, "ws": workspace_id},
    )
    return [_to_row(row) for row in result]


async def find_collection_row(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    collection_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> CollectionRow | None:
    """One collection of the Workspace, else None; ``for_update`` locks the row until the
    transaction ends."""
    if for_update:
        result = await conn.execute(
            text(
                "SELECT id, workspace_id, name, subtitle, access_level, groups, local_only,"
                " created_at, updated_at FROM collections"
                " WHERE org_id = :org AND workspace_id = :ws AND id = :id FOR UPDATE"
            ),
            {"org": org_id, "ws": workspace_id, "id": collection_id},
        )
    else:
        result = await conn.execute(
            text(
                "SELECT id, workspace_id, name, subtitle, access_level, groups, local_only,"
                " created_at, updated_at FROM collections"
                " WHERE org_id = :org AND workspace_id = :ws AND id = :id"
            ),
            {"org": org_id, "ws": workspace_id, "id": collection_id},
        )
    row = result.one_or_none()
    return None if row is None else _to_row(row)


async def insert_collection(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    name: str,
    subtitle: str | None,
    access_level: str,
    groups: Sequence[str],
    local_only: bool,
) -> CollectionRow:
    """Insert a collection with already validated values and return it."""
    result = await conn.execute(
        text(
            "INSERT INTO collections"
            " (org_id, workspace_id, name, subtitle, access_level, groups, local_only)"
            " VALUES (:org, :ws, :name, :subtitle, :level, CAST(:groups AS text[]), :local_only)"
            " RETURNING id, workspace_id, name, subtitle, access_level, groups, local_only,"
            " created_at, updated_at"
        ),
        {
            "org": org_id,
            "ws": workspace_id,
            "name": name,
            "subtitle": subtitle,
            "level": access_level,
            "groups": list(groups),
            "local_only": local_only,
        },
    )
    return _to_row(result.one())


async def update_collection_settings_row(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    collection_id: uuid.UUID,
    *,
    name: str,
    subtitle: str | None,
    local_only: bool,
) -> CollectionRow:
    """Set the name, subtitle and local-only flag of a collection and return it."""
    result = await conn.execute(
        text(
            "UPDATE collections SET name = :name, subtitle = :subtitle, local_only = :local_only,"
            " updated_at = now() WHERE org_id = :org AND workspace_id = :ws AND id = :id"
            " RETURNING id, workspace_id, name, subtitle, access_level, groups, local_only,"
            " created_at, updated_at"
        ),
        {
            "org": org_id,
            "ws": workspace_id,
            "id": collection_id,
            "name": name,
            "subtitle": subtitle,
            "local_only": local_only,
        },
    )
    return _to_row(result.one())


async def update_collection_access_row(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    collection_id: uuid.UUID,
    *,
    access_level: str,
    groups: Sequence[str],
) -> CollectionRow:
    """Set the access level and groups of a collection and return it."""
    result = await conn.execute(
        text(
            "UPDATE collections SET access_level = :level, groups = CAST(:groups AS text[]),"
            " updated_at = now() WHERE org_id = :org AND workspace_id = :ws AND id = :id"
            " RETURNING id, workspace_id, name, subtitle, access_level, groups, local_only,"
            " created_at, updated_at"
        ),
        {
            "org": org_id,
            "ws": workspace_id,
            "id": collection_id,
            "level": access_level,
            "groups": list(groups),
        },
    )
    return _to_row(result.one())


@dataclass(frozen=True)
class DocumentCounts:
    """The document counts of one collection by shown group (stored statuses)."""

    total: int = 0
    ready: int = 0
    processing: int = 0
    needs_attention: int = 0


async def document_counts(
    conn: AsyncConnection, org_id: uuid.UUID, collection_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, DocumentCounts]:
    """The counts of the given collections from one aggregate; a collection without documents
    is absent from the result. Queued counts as processing; failed and not supported as needing
    attention."""
    result = await conn.execute(
        text(
            "SELECT collection_id, count(*) AS total,"
            " count(*) FILTER (WHERE status = 'ready') AS ready,"
            " count(*) FILTER (WHERE status = 'queued') AS processing,"
            " count(*) FILTER (WHERE status IN ('failed', 'not_supported')) AS needs_attention"
            " FROM documents WHERE org_id = :org AND collection_id = ANY(CAST(:ids AS uuid[]))"
            " GROUP BY collection_id"
        ),
        {"org": org_id, "ids": list(collection_ids)},
    )
    return {
        row.collection_id: DocumentCounts(
            total=row.total,
            ready=row.ready,
            processing=row.processing,
            needs_attention=row.needs_attention,
        )
        for row in result
    }


@dataclass(frozen=True)
class QueuedDocument:
    id: uuid.UUID
    collection_id: uuid.UUID
    updated_at: datetime


async def list_queued_documents(
    conn: AsyncConnection, org_id: uuid.UUID, collection_ids: Sequence[uuid.UUID]
) -> list[QueuedDocument]:
    """The stored-``queued`` documents of the given collections, so a caller can tell the ones
    a job still holds from the interrupted ones."""
    result = await conn.execute(
        text(
            "SELECT id, collection_id, updated_at FROM documents WHERE org_id = :org"
            " AND collection_id = ANY(CAST(:ids AS uuid[])) AND status = 'queued'"
        ),
        {"org": org_id, "ids": list(collection_ids)},
    )
    return [
        QueuedDocument(id=row.id, collection_id=row.collection_id, updated_at=row.updated_at)
        for row in result
    ]


async def delete_collection_row(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID, collection_id: uuid.UUID
) -> None:
    """Delete a collection; its folders go with it (foreign key cascade)."""
    await conn.execute(
        text("DELETE FROM collections WHERE org_id = :org AND workspace_id = :ws AND id = :id"),
        {"org": org_id, "ws": workspace_id, "id": collection_id},
    )
