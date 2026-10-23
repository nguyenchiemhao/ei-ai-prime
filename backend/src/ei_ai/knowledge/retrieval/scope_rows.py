"""Row reads of the knowledge scope, run inside the caller's tenant transaction (EA-36).

Every statement carries the explicit Organization and Workspace filters (layer 1) on top of
row-level security (layer 2, D46). An id of another Workspace or Organization simply matches no
row, so callers cannot tell it from an unknown id.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_MAX_FOLDER_DEPTH = 3

_FOLDER_TREES = f"""
WITH RECURSIVE tree (root_id, id, collection_id, level) AS (
    SELECT f.id, f.id, f.collection_id, 1
    FROM folders f
    JOIN collections c ON c.org_id = f.org_id AND c.id = f.collection_id
    WHERE f.org_id = :org AND c.org_id = :org AND c.workspace_id = :ws
      AND f.id = ANY(CAST(:ids AS uuid[]))
  UNION ALL
    SELECT t.root_id, f.id, f.collection_id, t.level + 1
    FROM folders f
    JOIN tree t ON f.org_id = :org AND f.collection_id = t.collection_id AND f.parent_id = t.id
    WHERE t.level < {_MAX_FOLDER_DEPTH}
)
SELECT root_id, collection_id, id FROM tree ORDER BY root_id, level, id
"""


async def collections_by_id(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    ids: Sequence[uuid.UUID],
) -> list[tuple[uuid.UUID, str, tuple[str, ...]]]:
    """``(id, access level, groups)`` of the collections of the Workspace among ``ids``."""
    result = await conn.execute(
        text(
            "SELECT id, access_level, groups FROM collections"
            " WHERE org_id = :org AND workspace_id = :ws AND id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"org": org_id, "ws": workspace_id, "ids": list(ids)},
    )
    return [(row.id, row.access_level, tuple(row.groups)) for row in result]


async def folder_trees(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    folder_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, tuple[uuid.UUID, tuple[uuid.UUID, ...]]]:
    """Each listed folder of the Workspace -> ``(its collection id, itself + all descendants)``.

    Folders that are unknown or outside the Workspace are absent. Depth is at most 3.
    """
    result = await conn.execute(
        text(_FOLDER_TREES), {"org": org_id, "ws": workspace_id, "ids": list(folder_ids)}
    )
    collections: dict[uuid.UUID, uuid.UUID] = {}
    members: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in result:
        collections[row.root_id] = row.collection_id
        members.setdefault(row.root_id, []).append(row.id)
    return {root: (collections[root], tuple(ids)) for root, ids in members.items()}


async def workspace_exists(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID
) -> bool:
    """Whether the Workspace belongs to the Organization."""
    result = await conn.execute(
        text("SELECT 1 FROM workspaces WHERE org_id = :org AND id = :ws"),
        {"org": org_id, "ws": workspace_id},
    )
    return result.first() is not None


async def workspace_collection_ids(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[uuid.UUID, ...]:
    """Every collection id of the Workspace, by name ignoring case, then id."""
    result = await conn.execute(
        text(
            "SELECT id FROM collections WHERE org_id = :org AND workspace_id = :ws"
            " ORDER BY lower(name), id"
        ),
        {"org": org_id, "ws": workspace_id},
    )
    return tuple(row.id for row in result)
