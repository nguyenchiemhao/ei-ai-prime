"""``tenant_transaction``: the tenant context is transaction-local and cannot nest (AC3)."""

import uuid
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration


class _Boom(Exception):
    pass


async def _count(conn: AsyncConnection, table: str = "workspaces") -> int:
    return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def _setting(conn: AsyncConnection) -> str | None:
    result = await conn.execute(text("SELECT current_setting('app.current_org', true)"))
    return result.scalar()


@pytest.mark.parametrize(
    "bad_org_id", ["not-a-uuid", "0b9c1c3e-5f0a-4a52-9a53-2c0f1f6f7a11", 42, None]
)
async def test_rejects_non_uuid_org_id_before_any_database_call(bad_org_id: object) -> None:
    conn = Mock(spec=[])  # any database call would raise AttributeError

    with pytest.raises(TypeError):
        async with tenant_transaction(conn, bad_org_id):  # type: ignore[arg-type]
            pass


async def test_context_is_cleared_after_commit(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    async with app_engine.connect() as conn:
        async with tenant_transaction(conn, two_orgs.a.org_id):
            assert await _count(conn) == 1

        # Same connection, no context: sees nothing and must not raise on the leftover '' setting.
        assert await _count(conn) == 0
        assert await _setting(conn) in (None, "")


async def test_context_is_transaction_local_after_rollback(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn:
        with pytest.raises(_Boom):
            async with tenant_transaction(conn, two_orgs.a.org_id):
                raise _Boom

        assert await _count(conn) == 0
        assert await _setting(conn) in (None, "")


async def test_rejects_nested_tenant_transaction(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    # A nested call would become a SAVEPOINT, and set_config(..., true) survives RELEASE SAVEPOINT,
    # so the inner tenant would leak into the rest of the outer block.
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        with pytest.raises(RuntimeError):
            async with tenant_transaction(conn, two_orgs.b.org_id):
                pass

        # The outer context is untouched: still Organization A only.
        names = (await conn.execute(text("SELECT name FROM organizations"))).scalars().all()
        assert names == ["Org A"]


async def test_rejects_an_already_open_sqlalchemy_transaction(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))  # autobegin

        with pytest.raises(RuntimeError):
            async with tenant_transaction(conn, two_orgs.a.org_id):
                pass


async def test_rejects_a_transaction_opened_on_the_driver_connection(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute("SELECT 1")  # type: ignore[union-attr]

        with pytest.raises(RuntimeError):
            async with tenant_transaction(conn, two_orgs.a.org_id):
                pass


async def test_pooled_connection_reuse_after_a_tenant_transaction_sees_nothing(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        assert await _count(conn, "organizations") == 1

    # pool_size=1: this is the same physical connection.
    async with app_engine.connect() as conn:
        assert await _count(conn, "organizations") == 0


async def test_an_unknown_organization_sees_nothing(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn, tenant_transaction(conn, uuid.uuid4()):
        for table in (
            "organizations",
            "workspaces",
            "memberships",
            "workspace_memberships",
            "users",
        ):
            assert await _count(conn, table) == 0
