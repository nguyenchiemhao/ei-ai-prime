"""Set-password tokens against the real policies: one-time, 24 h, never across Organizations."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.set_password import (
    format_token,
    hash_secret,
    issue_token,
    redeem_set_password_token,
)
from ei_ai.db.tenant import tenant_transaction
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration


async def _issue(engine: AsyncEngine, org: OrgRows, user_id: uuid.UUID | None = None) -> str:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        return await issue_token(conn, org.org_id, user_id or org.user_id)


async def _unused_hashes(engine: AsyncEngine, org: OrgRows, user_id: uuid.UUID) -> list[str]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT token_hash FROM set_password_tokens"
                " WHERE org_id = :org AND user_id = :user AND used_at IS NULL"
            ),
            {"org": org.org_id, "user": user_id},
        )
        return list(result.scalars())


async def _used_hashes(engine: AsyncEngine, org: OrgRows, user_id: uuid.UUID) -> list[str]:
    """Hashes of the user's redeemed tokens (the redemption history a reissue must keep)."""
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT token_hash FROM set_password_tokens"
                " WHERE org_id = :org AND user_id = :user AND used_at IS NOT NULL"
            ),
            {"org": org.org_id, "user": user_id},
        )
        return list(result.scalars())


async def _add_user(engine: AsyncEngine, org: OrgRows) -> uuid.UUID:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "INSERT INTO users (org_id, email, display_name)"
                " VALUES (:org, :email, 'Second') RETURNING id"
            ),
            {"org": org.org_id, "email": f"second.{uuid.uuid4().hex[:8]}@example.invalid"},
        )
        user_id: uuid.UUID = result.scalar_one()
    return user_id


async def test_issue_stores_only_the_hash_valid_24_hours(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    secret = await _issue(app_engine, a)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        row = (
            await conn.execute(
                text(
                    "SELECT token_hash, expires_at - created_at = interval '24 hours'"
                    " FROM set_password_tokens"
                    " WHERE org_id = :org AND user_id = :user AND used_at IS NULL"
                ),
                {"org": a.org_id, "user": a.user_id},
            )
        ).one()

    assert row == (hash_secret(secret), True)


async def test_redeem_once_then_none(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    token = format_token(a.org_id, await _issue(app_engine, a))

    assert await redeem_set_password_token(app_engine, token) == a.user_id
    assert await redeem_set_password_token(app_engine, token) is None


async def test_expired_token_is_none(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    secret = await _issue(app_engine, a)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text(
                "UPDATE set_password_tokens SET expires_at = now() - interval '1 second'"
                " WHERE org_id = :org AND token_hash = :hash"
            ),
            {"org": a.org_id, "hash": hash_secret(secret)},
        )

    assert await redeem_set_password_token(app_engine, format_token(a.org_id, secret)) is None


async def test_unknown_secret_is_none(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    token = format_token(two_orgs.a.org_id, "x" * 43)

    assert await redeem_set_password_token(app_engine, token) is None


async def test_malformed_token_is_none_without_database_access(
    two_orgs: TwoOrgs,
) -> None:
    class _NoEngine:
        def connect(self) -> None:
            raise AssertionError("a malformed token must not reach the database")

    for token in ("", "abc", f"{two_orgs.a.org_id}.short", f"bad.{'x' * 43}"):
        assert await redeem_set_password_token(_NoEngine(), token) is None  # type: ignore[arg-type]


async def test_secret_with_other_org_id_is_none_and_untouched(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    b_secret = await _issue(app_engine, b)

    assert await redeem_set_password_token(app_engine, format_token(a.org_id, b_secret)) is None
    assert await _unused_hashes(app_engine, b, b.user_id) == [hash_secret(b_secret)]
    assert await redeem_set_password_token(app_engine, format_token(b.org_id, b_secret)) == (
        b.user_id
    )


async def test_reissue_deletes_only_that_users_unused_tokens(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    other_user = await _add_user(app_engine, a)
    used = await _issue(app_engine, a)
    assert await redeem_set_password_token(app_engine, format_token(a.org_id, used)) == a.user_id
    first = await _issue(app_engine, a)
    other = await _issue(app_engine, a, other_user)
    b_secret = await _issue(app_engine, b)

    second = await _issue(app_engine, a)

    assert await _unused_hashes(app_engine, a, a.user_id) == [hash_secret(second)]
    assert await _unused_hashes(app_engine, a, other_user) == [hash_secret(other)]
    assert await _unused_hashes(app_engine, b, b.user_id) == [hash_secret(b_secret)]
    assert await _used_hashes(app_engine, a, a.user_id) == [hash_secret(used)]
    assert await redeem_set_password_token(app_engine, format_token(a.org_id, first)) is None
    assert await redeem_set_password_token(app_engine, format_token(a.org_id, second)) == (
        a.user_id
    )
