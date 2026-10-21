"""Row reads and writes of members and their roles, run inside the caller's tenant transaction.

Every statement carries the explicit Organization filter (layer 1) on top of row-level security
(layer 2, D46). Shared by the members service, the provisioning commands and the demo seed.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.auth.set_password import issue_token


@dataclass(frozen=True)
class OrgRoleRow:
    user_id: uuid.UUID
    org_role: str | None


@dataclass(frozen=True)
class MemberRow:
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str
    org_role: str | None
    last_active_at: datetime | None


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


# The two member statements below are written out in full (no f-strings) so the static layer-1
# check in tests/provisioning can read them. Last activity: the latest session use or
# sign-in/sign-out event of the user, if any.


async def list_member_rows(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[MemberRow]:
    """The members of one Workspace in the order they joined."""
    result = await conn.execute(
        text(
            "SELECT u.id AS user_id, u.display_name, u.email, wm.role, m.org_role,"
            " GREATEST("
            "(SELECT max(s.last_seen_at) FROM admin_sessions s"
            " WHERE s.org_id = :org AND s.user_id = u.id),"
            "(SELECT max(e.created_at) FROM audit_events e"
            " WHERE e.org_id = :org AND e.actor = 'user:' || u.id::text"
            " AND e.action IN ('user.signed_in', 'user.signed_out'))"
            ") AS last_active_at"
            " FROM workspace_memberships wm"
            " JOIN users u ON u.org_id = wm.org_id AND u.id = wm.user_id"
            " JOIN memberships m ON m.org_id = wm.org_id AND m.user_id = wm.user_id"
            " WHERE wm.org_id = :org AND u.org_id = :org AND m.org_id = :org"
            " AND wm.workspace_id = :ws"
            " ORDER BY wm.created_at, wm.id"
        ),
        {"org": org_id, "ws": workspace_id},
    )
    return [MemberRow(**row._mapping) for row in result]


async def find_member_row(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> MemberRow | None:
    """One member of the Workspace, else None."""
    row = (
        await conn.execute(
            text(
                "SELECT u.id AS user_id, u.display_name, u.email, wm.role, m.org_role,"
                " GREATEST("
                "(SELECT max(s.last_seen_at) FROM admin_sessions s"
                " WHERE s.org_id = :org AND s.user_id = u.id),"
                "(SELECT max(e.created_at) FROM audit_events e"
                " WHERE e.org_id = :org AND e.actor = 'user:' || u.id::text"
                " AND e.action IN ('user.signed_in', 'user.signed_out'))"
                ") AS last_active_at"
                " FROM workspace_memberships wm"
                " JOIN users u ON u.org_id = wm.org_id AND u.id = wm.user_id"
                " JOIN memberships m ON m.org_id = wm.org_id AND m.user_id = wm.user_id"
                " WHERE wm.org_id = :org AND u.org_id = :org AND m.org_id = :org"
                " AND wm.workspace_id = :ws AND wm.user_id = :user"
            ),
            {"org": org_id, "ws": workspace_id, "user": user_id},
        )
    ).one_or_none()
    return None if row is None else MemberRow(**row._mapping)


async def find_user_id(conn: AsyncConnection, org_id: uuid.UUID, email: str) -> uuid.UUID | None:
    """Id of the user of this Organization with that (normalised) email, else None."""
    found: uuid.UUID | None = (
        await conn.execute(
            text("SELECT id FROM users WHERE org_id = :org AND email = :email"),
            {"org": org_id, "email": email},
        )
    ).scalar_one_or_none()
    return found


async def lock_workspace_role(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    """The user's Workspace role with the row locked until the transaction ends; None when the
    user is not a member of the Workspace."""
    role: str | None = (
        await conn.execute(
            text(
                "SELECT role FROM workspace_memberships"
                " WHERE org_id = :org AND workspace_id = :ws AND user_id = :user FOR UPDATE"
            ),
            {"org": org_id, "ws": workspace_id, "user": user_id},
        )
    ).scalar_one_or_none()
    return role


async def update_workspace_role(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> None:
    await conn.execute(
        text(
            "UPDATE workspace_memberships SET role = :role"
            " WHERE org_id = :org AND workspace_id = :ws AND user_id = :user"
        ),
        {"org": org_id, "ws": workspace_id, "user": user_id, "role": role},
    )


async def delete_workspace_member(
    conn: AsyncConnection, org_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await conn.execute(
        text(
            "DELETE FROM workspace_memberships"
            " WHERE org_id = :org AND workspace_id = :ws AND user_id = :user"
        ),
        {"org": org_id, "ws": workspace_id, "user": user_id},
    )


async def lock_owners_and_target(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[OrgRoleRow]:
    """Lock, in one statement and in a fixed order (by id), the membership of ``user_id`` and
    every Org Owner of the Organization, and return their current Organization roles.

    One statement in one order means two concurrent changes queue up instead of deadlocking.
    The roles returned are the latest committed ones: a row another transaction changed while
    this one waited is re-read under the lock (a demoted owner is no longer returned unless it
    is the target). No row for ``user_id`` means the user is not in this Organization.
    """
    result = await conn.execute(
        text(
            "SELECT user_id, org_role FROM memberships"
            " WHERE org_id = :org AND (org_role = 'org_owner' OR user_id = :user)"
            " ORDER BY id FOR UPDATE"
        ),
        {"org": org_id, "user": user_id},
    )
    return [OrgRoleRow(user_id=row.user_id, org_role=row.org_role) for row in result]


async def update_org_role(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID, org_role: str | None
) -> None:
    await conn.execute(
        text("UPDATE memberships SET org_role = :role WHERE org_id = :org AND user_id = :user"),
        {"org": org_id, "user": user_id, "role": org_role},
    )
