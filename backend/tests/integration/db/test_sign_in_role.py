"""R42 proof: the sign-in lookup role reads ``users(id, org_id, email)`` and nothing else.

``ei_ai_signin`` is the only cross-tenant read in the codebase (owner decision 2026-10-20). These
tests connect as that role and prove each limit of the spec ("Sign-in lookup role", point 6); the
schema guard (G4 allowance, G14) keeps the grants from drifting.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.directory import Account, SignInDirectory
from ei_ai.db.tenant import tenant_transaction
from support.tenants import DELETE_ORDER, TwoOrgs

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

SIGNIN = "ei_ai_signin"
OTHER_TABLES = tuple(t for t in DELETE_ORDER if t != "users") + ("alembic_version",)


@pytest.fixture
def signin_url() -> str:
    return os.environ["SIGNIN_DATABASE_URL"]


@pytest.fixture
def signin_conn(signin_url: str) -> Iterator[psycopg.Connection]:
    """Connection as ``ei_ai_signin`` (autocommit)."""
    with psycopg.connect(signin_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def signin_tx_conn(signin_url: str) -> Iterator[psycopg.Connection]:
    """``ei_ai_signin`` connection whose transaction is ALWAYS rolled back (negative tests)."""
    with psycopg.connect(signin_url) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture
async def directory(signin_url: str) -> AsyncIterator[SignInDirectory]:
    directory = SignInDirectory(signin_url)
    try:
        yield directory
    finally:
        await directory.dispose()


def _assert_permission_denied(conn: psycopg.Connection, statement: str) -> None:
    """The statement fails for a missing privilege. An RLS rejection (`new row violates row-level
    security policy`) has the same SQLSTATE 42501, so only the message tells the two apart: a role
    that held the privilege would fail on the policy instead and must not pass this proof."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as error:
        conn.execute(statement)

    message = error.value.diag.message_primary or ""
    assert message.startswith("permission denied"), message


def test_signin_role_reads_only_id_org_id_email_across_orgs(
    signin_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    orgs = (two_orgs.a, two_orgs.b)
    rows = signin_conn.execute(
        "SELECT id, org_id, email FROM users WHERE org_id = ANY (%s)",
        ([org.org_id for org in orgs],),
    ).fetchall()

    assert set(rows) == {(org.user_id, org.org_id, org.email) for org in orgs}


@pytest.mark.parametrize(
    "query",
    [
        "SELECT display_name FROM users",
        "SELECT * FROM users",
        "SELECT created_at FROM users",
        "SELECT u FROM users u",
    ],
)
def test_signin_role_cannot_read_display_name_or_star(
    signin_conn: psycopg.Connection, query: str
) -> None:
    _assert_permission_denied(signin_conn, query)


@pytest.mark.parametrize("table", OTHER_TABLES)
def test_signin_role_cannot_read_other_tables(signin_conn: psycopg.Connection, table: str) -> None:
    _assert_permission_denied(signin_conn, f"SELECT 1 FROM {table} LIMIT 1")


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO users (id, org_id, email, display_name)"
        " VALUES (gen_random_uuid(), gen_random_uuid(), 'probe@example.invalid', 'Probe')",
        "UPDATE users SET email = email",
        "DELETE FROM users",
        "TRUNCATE users",
    ],
)
def test_signin_role_cannot_write_or_truncate_users(
    signin_tx_conn: psycopg.Connection, two_orgs: TwoOrgs, statement: str
) -> None:
    _assert_permission_denied(signin_tx_conn, statement)


@pytest.mark.parametrize(
    "statement", ["CREATE TABLE signin_probe (id int)", "CREATE TABLE public.signin_probe (id int)"]
)
def test_signin_role_cannot_create_table(
    signin_tx_conn: psycopg.Connection, statement: str
) -> None:
    _assert_permission_denied(signin_tx_conn, statement)


def test_signin_role_attributes(signin_conn: psycopg.Connection) -> None:
    row = signin_conn.execute(
        "SELECT current_user, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole,"
        " rolinherit FROM pg_roles WHERE rolname = current_user"
    ).fetchone()

    assert row == (SIGNIN, True, False, False, False, False, False)


def test_app_role_still_sees_no_users_without_context(
    app_conn: psycopg.Connection, migrator_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    # The lookup policy binds only ei_ai_signin: the application and owner roles still see nothing.
    assert app_conn.execute("SELECT count(*) FROM users").fetchone() == (0,)
    assert migrator_conn.execute("SELECT count(*) FROM users").fetchone() == (0,)


async def _add_user(engine: AsyncEngine, org_id: uuid.UUID, email: str) -> uuid.UUID:
    """A second user with ``email`` in the Organization (removed with the fixture's rows)."""
    user_id = uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        await conn.execute(
            text(
                "INSERT INTO users (id, org_id, email, display_name)"
                " VALUES (:id, :org, :email, 'Same email')"
            ),
            {"id": user_id, "org": org_id, "email": email},
        )
    return user_id


async def test_find_accounts_returns_both_orgs_ordered(
    directory: SignInDirectory, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    email = f"{uuid.uuid4()}@example.invalid"
    expected = sorted(
        [
            Account(org_id=org.org_id, user_id=await _add_user(app_engine, org.org_id, email))
            for org in (two_orgs.b, two_orgs.a)
        ],
        key=lambda account: account.org_id,
    )

    assert await directory.find_accounts(email) == expected


async def test_find_accounts_unknown_email_is_empty(
    directory: SignInDirectory, two_orgs: TwoOrgs
) -> None:
    assert await directory.find_accounts(f"{uuid.uuid4()}@example.invalid") == []
    assert await directory.find_accounts(two_orgs.a.email) == [
        Account(org_id=two_orgs.a.org_id, user_id=two_orgs.a.user_id)
    ]
