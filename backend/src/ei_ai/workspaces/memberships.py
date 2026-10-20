"""The Workspaces a user belongs to (``workspace_memberships`` only, R21).

Every query runs inside the caller's tenant transaction and filters by ``org_id`` explicitly on
each table it reads (D46).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class WorkspaceRef:
    id: uuid.UUID
    name: str
    role: str


async def list_workspaces(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[WorkspaceRef]:
    """The user's Workspaces with the user's role in each, ordered by name."""
    result = await conn.execute(
        text(
            "SELECT w.id, w.name, m.role FROM workspace_memberships m"
            " JOIN workspaces w ON w.org_id = m.org_id AND w.id = m.workspace_id"
            " WHERE m.org_id = :org AND w.org_id = :org AND m.user_id = :user"
            " ORDER BY w.name, w.id"
        ),
        {"org": org_id, "user": user_id},
    )
    return [WorkspaceRef(id=row.id, name=row.name, role=row.role) for row in result]


async def default_workspace_id(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID | None:
    """The Workspace of the user's earliest membership (``created_at``, then ``id``; R20)."""
    workspace_id: uuid.UUID | None = (
        await conn.execute(
            text(
                "SELECT workspace_id FROM workspace_memberships"
                " WHERE org_id = :org AND user_id = :user"
                " ORDER BY created_at, id LIMIT 1"
            ),
            {"org": org_id, "user": user_id},
        )
    ).scalar_one_or_none()
    return workspace_id
