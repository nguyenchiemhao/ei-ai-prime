"""Test-only helpers: Organizations with one row in every tenant table, and their removal.

Never imported by ``src``. Rows are created through the application role in a tenant transaction
(exactly like the product), so the fixtures exercise the real policies and grants.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction

# Every table of the schema, children first (the order in which fixture rows can be deleted).
DELETE_ORDER = ("workspace_memberships", "memberships", "workspaces", "users", "organizations")


@dataclass(frozen=True)
class OrgRows:
    """The ids of the fixture rows of one Organization (all random UUIDv4)."""

    org_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    workspace_membership_id: uuid.UUID
    label: str

    def row_id(self, table: str) -> uuid.UUID:
        return {
            "organizations": self.org_id,
            "workspaces": self.workspace_id,
            "users": self.user_id,
            "memberships": self.membership_id,
            "workspace_memberships": self.workspace_membership_id,
        }[table]


@dataclass(frozen=True)
class TwoOrgs:
    a: OrgRows
    b: OrgRows


# Per table the app role may update: the column and a harmless value for the cross-org UPDATE test.
UPDATE_SETS = {
    "organizations": ("name", "renamed-by-intruder"),
    "workspaces": ("name", "renamed-by-intruder"),
    "users": ("display_name", "renamed-by-intruder"),
    "memberships": ("org_role", "org_admin"),
    "workspace_memberships": ("role", "viewer"),
}


async def create_org_rows(engine: AsyncEngine, label: str) -> OrgRows:
    rows = OrgRows(
        org_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        workspace_membership_id=uuid.uuid4(),
        label=label,
    )
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": rows.org_id, "name": f"Org {label}"},
        )
        await conn.execute(
            text("INSERT INTO workspaces (id, org_id, name) VALUES (:id, :org, :name)"),
            {"id": rows.workspace_id, "org": rows.org_id, "name": f"Workspace {label}"},
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, org_id, email, display_name)"
                " VALUES (:id, :org, :email, :name)"
            ),
            {
                "id": rows.user_id,
                "org": rows.org_id,
                "email": f"{rows.user_id}@example.invalid",
                "name": f"User {label}",
            },
        )
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id) VALUES (:id, :org, :user)"),
            {"id": rows.membership_id, "org": rows.org_id, "user": rows.user_id},
        )
        await conn.execute(
            text(
                "INSERT INTO workspace_memberships (id, org_id, workspace_id, user_id, role)"
                " VALUES (:id, :org, :ws, :user, 'member')"
            ),
            {
                "id": rows.workspace_membership_id,
                "org": rows.org_id,
                "ws": rows.workspace_id,
                "user": rows.user_id,
            },
        )
    return rows


async def purge_org_rows(engine: AsyncEngine, *orgs: OrgRows) -> None:
    """Delete fixture rows through the application role, one tenant transaction per Organization.

    This is the product path: every table has a DELETE grant and the standard policy, so no owner
    privilege is used and row-level security is never altered.
    """
    for org in orgs:
        async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
            for table in DELETE_ORDER:
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE id = :id"), {"id": org.row_id(table)}
                )
