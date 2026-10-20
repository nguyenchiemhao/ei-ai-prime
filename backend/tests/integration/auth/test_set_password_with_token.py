"""set_password_with_token: redeem, credential, sessions and audit, all or nothing."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.credentials import reserve_attempt
from ei_ai.auth.lockout import MAX_FAILURES
from ei_ai.auth.sessions import IDLE_TIMEOUT, create_session, verify_session
from ei_ai.auth.set_password import (
    format_token,
    hash_secret,
    issue_token,
    set_password_with_token,
)
from ei_ai.db.tenant import tenant_transaction
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

NEW_HASH = "$argon2id$v=19$m=19456,t=2,p=1$new"


async def _issue(engine: AsyncEngine, org: OrgRows) -> str:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        return format_token(org.org_id, await issue_token(conn, org.org_id, org.user_id))


async def _lock(engine: AsyncEngine, org: OrgRows) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        for _ in range(MAX_FAILURES):
            await reserve_attempt(conn, org.org_id, org.user_id)


async def _state(engine: AsyncEngine, org: OrgRows) -> dict[str, object]:
    """Everything the operation may touch, for before/after comparison."""
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        params = {"org": org.org_id}
        credential = (
            await conn.execute(
                text(
                    "SELECT password_hash, locked_until FROM user_credentials"
                    " WHERE org_id = :org AND user_id = :user"
                ),
                {**params, "user": org.user_id},
            )
        ).one_or_none()
        sessions = (
            await conn.execute(
                text("SELECT count(*) FROM admin_sessions WHERE org_id = :org"), params
            )
        ).scalar_one()
        password_set_events = (
            await conn.execute(
                text(
                    "SELECT actor FROM audit_events"
                    " WHERE org_id = :org AND action = 'user.password_set'"
                ),
                params,
            )
        ).all()
        tokens = (
            await conn.execute(
                text("SELECT count(*) FROM set_password_tokens WHERE org_id = :org"), params
            )
        ).scalar_one()
        used = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM set_password_tokens"
                    " WHERE org_id = :org AND used_at IS NOT NULL"
                ),
                params,
            )
        ).scalar_one()
    return {
        "credential": credential,
        "sessions": sessions,
        "events": [row.actor for row in password_set_events],
        "tokens": tokens,
        "used": used,
    }


async def test_set_password_with_token_is_atomic(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    token = await _issue(app_engine, a)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        cookie = await create_session(conn, a.org_id, a.user_id)
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        b_cookie = await create_session(conn, b.org_id, b.user_id)
    await _lock(app_engine, a)
    b_before = await _state(app_engine, b)

    assert await set_password_with_token(app_engine, token, NEW_HASH) == a.user_id

    after = await _state(app_engine, a)
    credential = after["credential"]
    assert credential is not None
    assert (credential.password_hash, credential.locked_until) == (NEW_HASH, None)  # type: ignore[attr-defined]
    assert after["sessions"] == 0
    assert after["events"] == [f"user:{a.user_id}"]
    assert after["used"] == 1
    assert await verify_session(app_engine, cookie, IDLE_TIMEOUT) is None
    assert await verify_session(app_engine, b_cookie, IDLE_TIMEOUT) is not None
    assert await _state(app_engine, b) == b_before


async def test_set_password_with_used_or_expired_token_changes_nothing(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    used = await _issue(app_engine, a)
    assert await set_password_with_token(app_engine, used, NEW_HASH) == a.user_id
    expired = await _issue(app_engine, a)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text(
                "UPDATE set_password_tokens SET expires_at = now() - interval '1 second'"
                " WHERE org_id = :org AND token_hash = :hash"
            ),
            {"org": a.org_id, "hash": hash_secret(expired.partition(".")[2])},
        )
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await create_session(conn, a.org_id, a.user_id)
    before = await _state(app_engine, a)
    b_secret = await _issue(app_engine, b)
    wrong_org = format_token(a.org_id, b_secret.partition(".")[2])

    for token in (used, expired, wrong_org, f"{a.org_id}.{'x' * 43}", "garbage"):
        assert await set_password_with_token(app_engine, token, "$argon2id$other") is None

    assert await _state(app_engine, a) == before


async def test_set_password_rolls_back_everything_when_a_later_step_fails(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    token = await _issue(app_engine, a)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        cookie = await create_session(conn, a.org_id, a.user_id)
    await _lock(app_engine, a)
    before = await _state(app_engine, a)

    # Violates the argon2id CHECK inside the credential upsert, after the redeem succeeded.
    with pytest.raises(DBAPIError):
        await set_password_with_token(app_engine, token, "not-argon")

    assert await _state(app_engine, a) == before
    assert before["used"] == 0 and before["events"] == []
    assert await verify_session(app_engine, cookie, IDLE_TIMEOUT) is not None

    assert await set_password_with_token(app_engine, token, NEW_HASH) == a.user_id
