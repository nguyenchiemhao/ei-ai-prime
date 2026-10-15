"""AC2: with tenant context A, rows of Organization B cannot be read, changed, deleted or created.

Each case runs as the application role through ``tenant_transaction`` against the real policies.
The statements carry no ``org_id`` filter on purpose: the database layer must hold on its own.
"""

import uuid

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.catalog import read_catalog
from ei_ai.db.schema_guard import guarded_table_names
from ei_ai.db.tenant import tenant_transaction
from support.tenants import DELETE_ORDER, UPDATE_SETS, TwoOrgs

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

TABLES = list(UPDATE_SETS)

# An INSERT of a row that belongs to Organization B, attempted in context A.
FORGED_INSERTS = {
    "organizations": "INSERT INTO organizations (id, name) VALUES (:other_org, 'forged')",
    "workspaces": "INSERT INTO workspaces (org_id, name) VALUES (:other_org, 'forged')",
    "users": (
        "INSERT INTO users (org_id, email, display_name)"
        " VALUES (:other_org, 'forged@example.invalid', 'forged')"
    ),
    "memberships": "INSERT INTO memberships (org_id, user_id) VALUES (:other_org, :own_user)",
    "workspace_memberships": (
        "INSERT INTO workspace_memberships (org_id, workspace_id, user_id, role)"
        " VALUES (:other_org, :other_ws, :own_user, 'member')"
    ),
}


async def _scalar(engine: AsyncEngine, org: uuid.UUID, sql: str, **params: object) -> object:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        return (await conn.execute(text(sql), params)).scalar()


@pytest.mark.parametrize("table", TABLES)
async def test_select_of_other_org_rows_returns_nothing(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, table: str
) -> None:
    a, b = two_orgs.a, two_orgs.b

    other = await _scalar(
        app_engine, a.org_id, f"SELECT count(*) FROM {table} WHERE id = :id", id=b.row_id(table)
    )
    own = await _scalar(
        app_engine, a.org_id, f"SELECT count(*) FROM {table} WHERE id = :id", id=a.row_id(table)
    )

    assert other == 0
    assert own == 1


@pytest.mark.parametrize("table", TABLES)
async def test_query_without_app_filter_returns_only_own_rows(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, table: str
) -> None:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        ids = (await conn.execute(text(f"SELECT id FROM {table}"))).scalars().all()

    assert ids == [two_orgs.a.row_id(table)]


@pytest.mark.parametrize("table", TABLES)
async def test_update_of_other_org_rows_affects_zero_rows(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, table: str
) -> None:
    column, value = UPDATE_SETS[table]
    select_sql = f"SELECT {column} FROM {table} WHERE id = :id"
    before = await _scalar(app_engine, two_orgs.b.org_id, select_sql, id=two_orgs.b.row_id(table))

    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        result = await conn.execute(
            text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
            {"value": value, "id": two_orgs.b.row_id(table)},
        )

    assert result.rowcount == 0
    after = await _scalar(app_engine, two_orgs.b.org_id, select_sql, id=two_orgs.b.row_id(table))
    assert after == before
    assert after != value


@pytest.mark.parametrize("table", TABLES)
async def test_delete_of_other_org_rows_affects_zero_rows(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, table: str
) -> None:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        result = await conn.execute(
            text(f"DELETE FROM {table} WHERE id = :id"), {"id": two_orgs.b.row_id(table)}
        )

    assert result.rowcount == 0
    still_there = await _scalar(
        app_engine,
        two_orgs.b.org_id,
        f"SELECT count(*) FROM {table} WHERE id = :id",
        id=two_orgs.b.row_id(table),
    )
    assert still_there == 1


@pytest.mark.parametrize("table", TABLES)
async def test_insert_for_other_org_is_rejected_42501(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, table: str
) -> None:
    sql = FORGED_INSERTS[table]
    params = {
        "other_org": two_orgs.b.org_id,
        "other_ws": two_orgs.b.workspace_id,
        "own_user": two_orgs.a.user_id,
    }
    params = {k: v for k, v in params.items() if f":{k}" in sql}

    with pytest.raises(DBAPIError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(text(sql), params)

    assert error.value.orig is not None
    assert getattr(error.value.orig, "sqlstate", None) == "42501"


async def test_cross_org_reference_is_rejected_by_composite_fk(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    # Referential-integrity checks bypass RLS, so only the composite FK (org_id, workspace_id)
    # stops a row of Organization A from pointing at the Workspace of Organization B.
    with pytest.raises(IntegrityError):
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO workspace_memberships (org_id, workspace_id, user_id, role)"
                    " VALUES (:org, :ws, :user, 'member')"
                ),
                {
                    "org": two_orgs.a.org_id,
                    "ws": two_orgs.b.workspace_id,
                    "user": two_orgs.a.user_id,
                },
            )


def test_fixture_tables_cover_every_tenant_table(migrator_conn: psycopg.Connection) -> None:
    live = set(guarded_table_names(read_catalog(migrator_conn)))

    assert live == set(TABLES), (
        "add the new table to the FND-01 cross-org fixtures (FND-02 extends this suite)"
    )


def test_isolation_suite_snapshots_and_cleanup_cover_every_tenant_table(
    migrator_conn: psycopg.Connection,
) -> None:
    live = set(guarded_table_names(read_catalog(migrator_conn)))

    assert live == set(DELETE_ORDER), (
        "add the new table to DELETE_ORDER in tests/support/tenants.py: the snapshots and the"
        " cleanup of the isolation suite use it"
    )
