"""What the caller may do: the roles read from the database for one request, and the check.

Roles are read per request inside the caller's tenant transaction (one indexed query), never
cached: a role change applies from the caller's next request. Every table is filtered by
``org_id`` (D46); the user and the Organization come from the verified identity (D32).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.rbac.permissions import Permission, permissions_for
from ei_ai.tenancy.context import TenantContext


class PermissionDenied(Exception):
    """The caller lacks a permission. The API answers 403 ``forbidden`` (no detail)."""


@dataclass(frozen=True)
class WorkspaceAccess:
    """The caller in one Workspace they can see: roles and the union of their permissions."""

    workspace_id: uuid.UUID
    name: str
    role: str | None
    org_role: str | None
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class OrgAccess:
    """The caller in their Organization."""

    org_role: str | None
    permissions: frozenset[Permission]


def ensure(granted: frozenset[Permission], permission: Permission) -> None:
    """Raise ``PermissionDenied`` unless ``permission`` is in ``granted``."""
    if permission not in granted:
        raise PermissionDenied


async def load_workspace_access(
    conn: AsyncConnection, tenant: TenantContext, workspace_id: uuid.UUID
) -> WorkspaceAccess | None:
    """The caller's access to the Workspace, or ``None`` when they cannot see it: it does not
    exist, belongs to another Organization, or the caller has neither a Workspace membership nor
    an Organization role (Org Owner and Org Admin see every Workspace of the Organization)."""
    row = (
        await conn.execute(
            text(
                "SELECT w.id, w.name, wm.role AS workspace_role, m.org_role"
                " FROM workspaces w"
                " JOIN memberships m ON m.org_id = w.org_id AND m.user_id = :user"
                " LEFT JOIN workspace_memberships wm ON wm.org_id = w.org_id"
                " AND wm.workspace_id = w.id AND wm.user_id = :user AND wm.org_id = :org"
                " WHERE w.org_id = :org AND m.org_id = :org AND w.id = :ws"
            ),
            {"org": tenant.org_id, "user": tenant.user_id, "ws": workspace_id},
        )
    ).one_or_none()
    if row is None or (row.workspace_role is None and row.org_role is None):
        return None
    return WorkspaceAccess(
        workspace_id=row.id,
        name=row.name,
        role=row.workspace_role,
        org_role=row.org_role,
        permissions=permissions_for(row.org_role, row.workspace_role),
    )


async def load_org_access(conn: AsyncConnection, tenant: TenantContext) -> OrgAccess:
    """The caller's Organization role and its permissions (none without a membership row)."""
    org_role: str | None = (
        await conn.execute(
            text("SELECT org_role FROM memberships WHERE org_id = :org AND user_id = :user"),
            {"org": tenant.org_id, "user": tenant.user_id},
        )
    ).scalar_one_or_none()
    return OrgAccess(org_role=org_role, permissions=permissions_for(org_role, None))
