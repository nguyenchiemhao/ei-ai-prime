"""Migration 0003 (EA-22): the credential and session tables and the constraints auth relies on.

Each case runs as the application role in a tenant transaction and is rolled back by the failure.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration

ARGON_HASH = "$argon2id$v=19$m=19456,t=2,p=1$test"
AUTH_TABLES = ("user_credentials", "admin_sessions")


async def test_auth_tables_have_rls_and_tenant_policy(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        flags = (
            await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity"
                    " FROM pg_class c WHERE c.relname = ANY(:names)"
                ),
                {"names": list(AUTH_TABLES)},
            )
        ).all()
        policies = (
            await conn.execute(
                text(
                    "SELECT tablename, cmd, qual, with_check FROM pg_policies"
                    " WHERE tablename = ANY(:names)"
                ),
                {"names": list(AUTH_TABLES)},
            )
        ).all()

    assert sorted(tuple(row) for row in flags) == [
        ("admin_sessions", True, True),
        ("user_credentials", True, True),
    ]
    assert sorted(row[0] for row in policies) == sorted(AUTH_TABLES)
    for _table, command, qual, with_check in policies:
        assert command == "ALL"
        for expression in (qual, with_check):
            assert "NULLIF(current_setting('app.current_org'" in expression
            assert "org_id" in expression


async def test_credential_hash_must_be_argon2id(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO user_credentials (org_id, user_id, password_hash)"
                    " VALUES (:org, :user, '$2b$12$bcrypt-is-not-allowed')"
                ),
                {"org": two_orgs.a.org_id, "user": two_orgs.a.user_id},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23514"


@pytest.mark.parametrize("bad", ["Z" * 64, "a" * 63, "A" * 64])
async def test_session_token_hash_must_be_hex64(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, bad: str
) -> None:
    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO admin_sessions (org_id, user_id, token_hash)"
                    " VALUES (:org, :user, :hash)"
                ),
                {"org": two_orgs.a.org_id, "user": two_orgs.a.user_id, "hash": bad},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23514"


@pytest.mark.parametrize("table", AUTH_TABLES)
async def test_composite_fk_rejects_other_org_user(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, table: str
) -> None:
    sql = {
        "user_credentials": (
            "INSERT INTO user_credentials (org_id, user_id, password_hash)"
            f" VALUES (:org, :user, '{ARGON_HASH}')"
        ),
        "admin_sessions": (
            "INSERT INTO admin_sessions (org_id, user_id, token_hash)"
            f" VALUES (:org, :user, '{'c' * 64}')"
        ),
    }[table]

    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(text(sql), {"org": two_orgs.a.org_id, "user": two_orgs.b.user_id})

    assert getattr(error.value.orig, "sqlstate", None) == "23503"


async def test_one_credential_per_user_and_defaults(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        row = (
            await conn.execute(
                text(
                    "SELECT failed_attempts, failure_window_started_at, locked_until,"
                    " password_set_at IS NOT NULL FROM user_credentials WHERE id = :id"
                ),
                {"id": two_orgs.a.user_credential_id},
            )
        ).one()
    assert tuple(row) == (0, None, None, True)

    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO user_credentials (org_id, user_id, password_hash)"
                    f" VALUES (:org, :user, '{ARGON_HASH}')"
                ),
                {"org": two_orgs.a.org_id, "user": two_orgs.a.user_id},
            )
    assert getattr(error.value.orig, "sqlstate", None) == "23505"


async def test_failed_attempts_cannot_be_negative(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text("UPDATE user_credentials SET failed_attempts = -1 WHERE id = :id"),
                {"id": two_orgs.a.user_credential_id},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23514"
