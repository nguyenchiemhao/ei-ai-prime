"""Admin sessions on the real database: cookie to Principal, idle expiry, touch, org scoping."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.principal import Principal
from ei_ai.auth.sessions import (
    IDLE_TIMEOUT,
    create_session,
    delete_session,
    delete_user_sessions,
    verify_session,
)
from ei_ai.auth.tokens import format_token, hash_secret, parse_token
from ei_ai.db.tenant import tenant_transaction
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

IDLE = IDLE_TIMEOUT


async def _create(engine: AsyncEngine, org: OrgRows) -> str:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        return await create_session(conn, org.org_id, org.user_id)


async def _last_seen(engine: AsyncEngine, org: OrgRows, cookie: str) -> datetime:
    parsed = parse_token(cookie)
    assert parsed is not None
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        value: datetime = (
            await conn.execute(
                text(
                    "SELECT last_seen_at FROM admin_sessions"
                    " WHERE org_id = :org AND token_hash = :hash"
                ),
                {"org": org.org_id, "hash": hash_secret(parsed[1])},
            )
        ).scalar_one()
    return value


async def _age(engine: AsyncEngine, org: OrgRows, cookie: str, age: timedelta) -> None:
    parsed = parse_token(cookie)
    assert parsed is not None
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        await conn.execute(
            text(
                "UPDATE admin_sessions SET last_seen_at = now() - :age"
                " WHERE org_id = :org AND token_hash = :hash"
            ),
            {"age": age, "org": org.org_id, "hash": hash_secret(parsed[1])},
        )


async def test_session_cookie_verifies_to_principal(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    cookie = await _create(app_engine, a)

    assert await verify_session(app_engine, cookie, IDLE) == Principal(a.user_id, a.org_id)


async def test_session_stores_only_the_hash(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    cookie = await _create(app_engine, a)
    parsed = parse_token(cookie)
    assert parsed is not None

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        hashes = list(
            (
                await conn.execute(
                    text("SELECT token_hash FROM admin_sessions WHERE org_id = :org"),
                    {"org": a.org_id},
                )
            ).scalars()
        )

    assert hash_secret(parsed[1]) in hashes
    assert parsed[1] not in hashes


async def test_idle_session_expires_after_12_hours(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    live = await _create(app_engine, a)
    idle = await _create(app_engine, a)
    await _age(app_engine, a, live, timedelta(hours=11, minutes=59))
    await _age(app_engine, a, idle, timedelta(hours=12, seconds=1))

    assert await verify_session(app_engine, live, IDLE) == Principal(a.user_id, a.org_id)
    assert await verify_session(app_engine, idle, IDLE) is None


async def test_idle_parameter_is_honoured(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    cookie = await _create(app_engine, a)
    await _age(app_engine, a, cookie, timedelta(minutes=10))

    assert await verify_session(app_engine, cookie, timedelta(minutes=5)) is None
    assert await verify_session(app_engine, cookie, timedelta(minutes=15)) is not None


async def test_touch_updates_last_seen(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    stale = await _create(app_engine, a)
    fresh = await _create(app_engine, a)
    await _age(app_engine, a, stale, timedelta(seconds=61))
    await _age(app_engine, a, fresh, timedelta(seconds=30))
    stale_before = await _last_seen(app_engine, a, stale)
    fresh_before = await _last_seen(app_engine, a, fresh)

    assert await verify_session(app_engine, stale, IDLE) is not None
    assert await verify_session(app_engine, fresh, IDLE) is not None

    assert await _last_seen(app_engine, a, stale) > stale_before + timedelta(seconds=60)
    assert await _last_seen(app_engine, a, fresh) == fresh_before


async def test_secret_with_other_org_id_does_not_verify(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    b_cookie = await _create(app_engine, b)
    parsed = parse_token(b_cookie)
    assert parsed is not None

    assert await verify_session(app_engine, format_token(a.org_id, parsed[1]), IDLE) is None
    assert await verify_session(app_engine, b_cookie, IDLE) == Principal(b.user_id, b.org_id)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await delete_session(conn, a.org_id, parsed[1]) is None
    assert await verify_session(app_engine, b_cookie, IDLE) is not None


async def test_malformed_cookie_is_none_without_database_access() -> None:
    class _NoEngine:
        def connect(self) -> None:
            raise AssertionError("a malformed cookie must not reach the database")

    for cookie in ("", "abc", "not-a-uuid." + "x" * 43, "00000000-0000-0000-0000-000000000000.s"):
        assert await verify_session(_NoEngine(), cookie, IDLE) is None  # type: ignore[arg-type]


async def test_delete_session_then_verify_is_none(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    cookie = await _create(app_engine, a)
    parsed = parse_token(cookie)
    assert parsed is not None

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await delete_session(conn, a.org_id, parsed[1]) == a.user_id
        assert await delete_session(conn, a.org_id, parsed[1]) is None

    assert await verify_session(app_engine, cookie, IDLE) is None


async def test_delete_user_sessions_removes_only_that_user_in_that_org(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    a_cookie = await _create(app_engine, a)
    b_cookie = await _create(app_engine, b)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await delete_user_sessions(conn, a.org_id, a.user_id)

    assert await verify_session(app_engine, a_cookie, IDLE) is None
    assert await verify_session(app_engine, b_cookie, IDLE) is not None
