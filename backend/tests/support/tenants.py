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


def tenant_key_column(table: str) -> str:
    """The column that holds the Organization of a row (the Organization is its own tenant)."""
    return "id" if table == "organizations" else "org_id"


@dataclass(frozen=True)
class FixtureNames:
    """The visible names of the fixture rows of one Organization. They carry a random suffix, so
    no ordinary text ("user agent", "org admin") can contain one by accident."""

    organization: str
    workspace: str
    user: str


def fixture_names(label: str, suffix: str) -> FixtureNames:
    tag = f"{label} {suffix}"
    return FixtureNames(organization=f"Org {tag}", workspace=f"Workspace {tag}", user=f"User {tag}")


@dataclass(frozen=True)
class OrgRows:
    """The ids of the fixture rows of one Organization (all random UUIDv4)."""

    org_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    workspace_membership_id: uuid.UUID
    label: str
    suffix: str

    @property
    def names(self) -> FixtureNames:
        return fixture_names(self.label, self.suffix)

    def row_id(self, table: str) -> uuid.UUID:
        return {
            "organizations": self.org_id,
            "workspaces": self.workspace_id,
            "users": self.user_id,
            "memberships": self.membership_id,
            "workspace_memberships": self.workspace_membership_id,
        }[table]

    @property
    def email(self) -> str:
        return f"{self.user_id}@example.invalid"

    def markers(self) -> frozenset[str]:
        """Strings that identify this Organization's fixture data: every row id, the user's email
        and the names. Any of them in a response for another Organization is a leak."""
        names = self.names
        ids = {str(self.row_id(table)) for table in DELETE_ORDER}
        return frozenset({*ids, self.email, names.organization, names.workspace, names.user})


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
        suffix=uuid.uuid4().hex[:8],
    )
    names = rows.names
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": rows.org_id, "name": names.organization},
        )
        await conn.execute(
            text("INSERT INTO workspaces (id, org_id, name) VALUES (:id, :org, :name)"),
            {"id": rows.workspace_id, "org": rows.org_id, "name": names.workspace},
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, org_id, email, display_name)"
                " VALUES (:id, :org, :email, :name)"
            ),
            {
                "id": rows.user_id,
                "org": rows.org_id,
                "email": rows.email,
                "name": names.user,
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
    """Delete everything an Organization owns through the application role, one tenant
    transaction per Organization: the fixture rows and any row a test created for it (e.g. by a
    positive-control POST).

    This is the product path: every table has a DELETE grant and the standard policy, so no owner
    privilege is used and row-level security is never altered. The explicit ``org_id`` filter
    and the policy both apply.
    """
    for org in orgs:
        async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
            for table in DELETE_ORDER:
                key = tenant_key_column(table)
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE {key} = :org"), {"org": org.org_id}
                )
