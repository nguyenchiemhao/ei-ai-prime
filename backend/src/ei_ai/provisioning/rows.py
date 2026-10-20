"""Row reads and writes of provisioning, run inside the caller's tenant transaction.

Every statement carries the explicit Organization filter (layer 1) on top of row-level security
(layer 2, D46). Shared by the provisioning service and the demo seed.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.auth.set_password import issue_token


async def organization_exists(conn: AsyncConnection, org_id: uuid.UUID) -> bool:
    """True when the Organization row exists (visible in this tenant transaction)."""
    result = await conn.execute(
        text("SELECT 1 FROM organizations WHERE id = :org"), {"org": org_id}
    )
    return result.first() is not None


async def insert_organization(conn: AsyncConnection, org_id: uuid.UUID, name: str) -> None:
    """Insert the Organization row with its given id and trimmed name."""
    await conn.execute(
        text("INSERT INTO organizations (id, name) VALUES (:org, :name)"),
        {"org": org_id, "name": name},
    )


async def workspace_exists(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID
) -> bool:
    """True when the Workspace exists in this Organization."""
    result = await conn.execute(
        text("SELECT 1 FROM workspaces WHERE org_id = :org AND id = :ws"),
        {"org": org_id, "ws": workspace_id},
    )
    return result.first() is not None


async def find_workspace_id(
    conn: AsyncConnection, org_id: uuid.UUID, name: str
) -> uuid.UUID | None:
    """Id of the Workspace of this Organization with that name, else None."""
    result = await conn.execute(
        text("SELECT id FROM workspaces WHERE org_id = :org AND name = :name"),
        {"org": org_id, "name": name},
    )
    found: uuid.UUID | None = result.scalar_one_or_none()
    return found


async def insert_workspace(conn: AsyncConnection, org_id: uuid.UUID, name: str) -> uuid.UUID:
    """Insert a Workspace and return its id."""
    result = await conn.execute(
        text("INSERT INTO workspaces (org_id, name) VALUES (:org, :name) RETURNING id"),
        {"org": org_id, "name": name},
    )
    workspace_id: uuid.UUID = result.scalar_one()
    return workspace_id


async def find_user_id(conn: AsyncConnection, org_id: uuid.UUID, email: str) -> uuid.UUID | None:
    """Id of the user of this Organization with that (normalised) email, else None."""
    result = await conn.execute(
        text("SELECT id FROM users WHERE org_id = :org AND email = :email"),
        {"org": org_id, "email": email},
    )
    found: uuid.UUID | None = result.scalar_one_or_none()
    return found


async def workspace_member_exists(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """True when the user is already a member of the Workspace."""
    result = await conn.execute(
        text(
            "SELECT 1 FROM workspace_memberships"
            " WHERE org_id = :org AND workspace_id = :ws AND user_id = :user"
        ),
        {"org": org_id, "ws": workspace_id, "user": user_id},
    )
    return result.first() is not None


async def insert_workspace_member(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> None:
    """Insert a Workspace membership of an existing user."""
    await conn.execute(
        text(
            "INSERT INTO workspace_memberships (org_id, workspace_id, user_id, role)"
            " VALUES (:org, :ws, :user, :role)"
        ),
        {"org": org_id, "ws": workspace_id, "user": user_id, "role": role},
    )


async def insert_member(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    email: str,
    display_name: str,
    org_role: str | None,
    workspace: tuple[uuid.UUID, str] | None,
) -> tuple[uuid.UUID, str]:
    """Insert a user, its membership, its Workspace membership (``(workspace_id, role)``, if
    any) and a set-password token. Returns ``(user_id, secret)``."""
    result = await conn.execute(
        text(
            "INSERT INTO users (org_id, email, display_name)"
            " VALUES (:org, :email, :name) RETURNING id"
        ),
        {"org": org_id, "email": email, "name": display_name},
    )
    user_id: uuid.UUID = result.scalar_one()
    await conn.execute(
        text("INSERT INTO memberships (org_id, user_id, org_role) VALUES (:org, :user, :role)"),
        {"org": org_id, "user": user_id, "role": org_role},
    )
    if workspace is not None:
        await insert_workspace_member(conn, org_id, workspace[0], user_id, workspace[1])
    return user_id, await issue_token(conn, org_id, user_id)
