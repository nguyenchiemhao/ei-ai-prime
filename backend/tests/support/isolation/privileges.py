"""The isolation suite's caller holds every permission, so a refusal is about the Organization.

The shared fixture user is a plain ``member`` (EA-22 tests rely on that). The isolation cases call
routes that need permissions (members, Organization roles); with a plain member a positive
control would answer 403 and the cross-Organization calls would be refused for the wrong reason,
hiding a leak. This grants the fixture user the Org Owner role (every Workspace Admin permission
and the Organization ones) plus the Reviewer role in the fixture Workspace (the only grant an
Org Owner lacks: reading conversations), so the user holds every tenant permission.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import OrgRows


async def grant_every_permission(engine: AsyncEngine, rows: OrgRows) -> None:
    """Org Owner and Workspace Reviewer for the fixture user of ``rows``."""
    params = {"org": rows.org_id, "user": rows.user_id, "ws": rows.workspace_id}
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "UPDATE memberships SET org_role = 'org_owner'"
                " WHERE org_id = :org AND user_id = :user"
            ),
            params,
        )
        await conn.execute(
            text(
                "UPDATE workspace_memberships SET role = 'reviewer'"
                " WHERE org_id = :org AND workspace_id = :ws AND user_id = :user"
            ),
            params,
        )
