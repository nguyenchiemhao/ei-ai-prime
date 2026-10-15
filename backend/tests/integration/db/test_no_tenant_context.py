"""AC3: with no tenant context every table returns 0 rows, and errors leak no row values.

The table list comes from the catalog, so a table added later is covered without editing this file.
"""

import uuid

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.catalog import read_catalog
from ei_ai.db.schema_guard import guarded_table_names
from ei_ai.db.tenant import tenant_transaction
from support.tenants import TwoOrgs

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


class _Boom(Exception):
    pass


def _all_tables(conn: psycopg.Connection) -> list[str]:
    tables = guarded_table_names(read_catalog(conn))
    assert "organizations" in tables
    return tables


def test_every_table_returns_zero_rows_without_context(
    app_conn: psycopg.Connection, migrator_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    for table in _all_tables(migrator_conn):
        count = app_conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert count == (0,), table


async def test_every_table_returns_zero_rows_after_a_committed_tenant_transaction(
    app_engine: AsyncEngine, migrator_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    tables = _all_tables(migrator_conn)
    async with app_engine.connect() as conn:
        async with tenant_transaction(conn, two_orgs.a.org_id):
            assert (await conn.execute(text("SELECT count(*) FROM organizations"))).scalar() == 1

        # The setting now reads '' on this session; NULLIF turns it into NULL, not an error.
        for table in tables:
            result = await conn.execute(text(f"SELECT count(*) FROM {table}"))
            assert result.scalar() == 0, table


async def test_every_table_returns_zero_rows_after_a_rolled_back_tenant_transaction(
    app_engine: AsyncEngine, migrator_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    tables = _all_tables(migrator_conn)
    async with app_engine.connect() as conn:
        with pytest.raises(_Boom):
            async with tenant_transaction(conn, two_orgs.a.org_id):
                raise _Boom

        for table in tables:
            result = await conn.execute(text(f"SELECT count(*) FROM {table}"))
            assert result.scalar() == 0, table


def test_policy_without_nullif_would_raise_on_empty_setting(
    migrator_conn: psycopg.Connection,
) -> None:
    # Why the policies use NULLIF: after a transaction that used set_config(..., true) ends, the
    # setting reads '' in the same session, and ''::uuid raises instead of matching nothing.
    migrator_conn.execute("CREATE TEMP TABLE nullif_probe (org_id uuid NOT NULL)")
    migrator_conn.execute("ALTER TABLE nullif_probe ENABLE ROW LEVEL SECURITY")
    migrator_conn.execute("ALTER TABLE nullif_probe FORCE ROW LEVEL SECURITY")
    migrator_conn.execute(
        "CREATE POLICY no_nullif ON nullif_probe"
        " USING (org_id = current_setting('app.current_org', true)::uuid)"
    )
    with migrator_conn.transaction():
        migrator_conn.execute(
            "SELECT set_config('app.current_org', %s, true)", (str(uuid.uuid4()),)
        )

    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        migrator_conn.execute("SELECT * FROM nullif_probe")


def test_organizations_policy_returns_zero_rows_in_the_same_situation(
    app_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    with app_conn.transaction():
        app_conn.execute(
            "SELECT set_config('app.current_org', %s, true)", (str(two_orgs.a.org_id),)
        )

    assert app_conn.execute("SELECT count(*) FROM organizations").fetchone() == (0,)


def test_insert_without_context_is_rejected_without_row_values_in_error(
    app_tx_conn: psycopg.Connection,
) -> None:
    secret_name = f"secret-name-{uuid.uuid4()}"
    org_id = uuid.uuid4()

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as error:
        app_tx_conn.execute(
            "INSERT INTO organizations (id, name) VALUES (%s, %s)", (org_id, secret_name)
        )

    message = str(error.value)
    assert "organizations" in message
    assert secret_name not in message
    assert str(org_id) not in message


def test_user_insert_without_context_is_rejected(app_tx_conn: psycopg.Connection) -> None:
    email = f"{uuid.uuid4()}@example.invalid"

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as error:
        app_tx_conn.execute(
            "INSERT INTO users (id, org_id, email, display_name) VALUES (%s, %s, %s, 'No Context')",
            (uuid.uuid4(), uuid.uuid4(), email),
        )

    assert email not in str(error.value)
