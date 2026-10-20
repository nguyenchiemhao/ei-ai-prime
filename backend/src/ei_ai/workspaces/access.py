"""Access to one Workspace: only a member sees it (R21).

A Workspace that does not exist, belongs to another Organization or has no membership of the
caller answers with the same 404 ``not_found`` (the Workspace id is never confirmed).
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import text

from ei_ai.api.deps import TenantSession
from ei_ai.tenancy.context import TenantContext, require_tenant
from ei_ai.workspaces.memberships import WorkspaceRef

NOT_FOUND = "not_found"


async def require_workspace_member(
    workspace_id: uuid.UUID,
    tenant: Annotated[TenantContext, Depends(require_tenant)],
    session: TenantSession,
) -> WorkspaceRef:
    """The caller's Workspace ``workspace_id`` with the caller's role, or 404 ``not_found``."""
    row = (
        await session.execute(
            text(
                "SELECT w.id, w.name, m.role FROM workspace_memberships m"
                " JOIN workspaces w ON w.org_id = m.org_id AND w.id = m.workspace_id"
                " WHERE m.org_id = :org AND w.org_id = :org AND m.user_id = :user"
                " AND m.workspace_id = :ws"
            ),
            {"org": tenant.org_id, "user": tenant.user_id, "ws": workspace_id},
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return WorkspaceRef(id=row.id, name=row.name, role=row.role)
