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


async def delete_collection_row(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID, collection_id: uuid.UUID
) -> None:
    """Delete a collection; its folders go with it (foreign key cascade)."""
    await conn.execute(
        text("DELETE FROM collections WHERE org_id = :org AND workspace_id = :ws AND id = :id"),
        {"org": org_id, "ws": workspace_id, "id": collection_id},
    )
