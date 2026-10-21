"""The Workspaces a user can see: their memberships, and every Workspace for an Org Owner or Org
Admin (R21, FND-06).

Every query runs inside the caller's tenant transaction and filters by ``org_id`` explicitly on
each table it reads (D46).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# A Workspace is visible to its members and to anyone holding an Organization role.
_VISIBLE_WORKSPACES = (
    " FROM workspaces w"
    " JOIN memberships m ON m.org_id = w.org_id AND m.user_id = :user"
    " LEFT JOIN workspace_memberships wm ON wm.org_id = w.org_id"
    " AND wm.org_id = :org AND wm.workspace_id = w.id AND wm.user_id = :user"
    " WHERE w.org_id = :org AND m.org_id = :org"
    " AND (wm.role IS NOT NULL OR m.org_role IS NOT NULL)"
)


@dataclass(frozen=True)
class WorkspaceRef:
    id: uuid.UUID
    name: str
    role: str | None  # None: visible through an Organization role, no Workspace membership


async def list_workspaces(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[WorkspaceRef]:
    """The user's Workspaces with the user's role in each, ordered by name. Org Owner and Org
    Admin get every Workspace of the Organization (role ``None`` without a membership)."""
    result = await conn.execute(
        text(f"SELECT w.id, w.name, wm.role{_VISIBLE_WORKSPACES} ORDER BY w.name, w.id"),
        {"org": org_id, "user": user_id},
    )
    return [WorkspaceRef(id=row.id, name=row.name, role=row.role) for row in result]


async def default_workspace_id(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID | None:
    """The Workspace of the user's earliest membership (``created_at``, then ``id``; R20); for an
    Org Owner or Org Admin without any, the first Workspace by ``(created_at, id)``."""
    workspace_id: uuid.UUID | None = (
        await conn.execute(
            text(
                f"SELECT w.id{_VISIBLE_WORKSPACES}"
                " ORDER BY wm.created_at NULLS LAST, wm.id NULLS LAST, w.created_at, w.id LIMIT 1"
            ),
            {"org": org_id, "user": user_id},
        )
    ).scalar_one_or_none()
    return workspace_id
