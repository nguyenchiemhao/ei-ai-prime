"""Admin sessions: the cookie is ``<org_id>.<secret>``, only ``sha256(secret)`` is stored.

The Organization comes from the cookie and the secret is matched inside that Organization only
(tenant transaction plus explicit ``org_id``), so a secret presented with another Organization's id
finds nothing (D46). Nothing here logs a secret (D52).
"""

import uuid
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.auth.principal import Principal
from ei_ai.auth.tokens import format_token, hash_secret, new_secret, parse_token
from ei_ai.db.tenant import tenant_transaction

SESSION_COOKIE = "ei_session"  # the cookie name; its value is ``<org_id>.<secret>``
IDLE_TIMEOUT = timedelta(seconds=43200)  # module default; the setting is wired in by the caller
TOUCH_AFTER = timedelta(seconds=60)


async def create_session(conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Insert a session for the user and return the cookie value."""
    secret = new_secret()
    await conn.execute(
        text(
            "INSERT INTO admin_sessions (org_id, user_id, token_hash) VALUES (:org, :user, :hash)"
        ),
        {"org": org_id, "user": user_id, "hash": hash_secret(secret)},
    )
    return format_token(org_id, secret)


async def verify_session(engine: AsyncEngine, cookie: str, idle: timedelta) -> Principal | None:
    """The Principal of a live session, else None (malformed cookies never reach the database).

    Refreshes ``last_seen_at`` when it is older than ``TOUCH_AFTER``.
    """
    parsed = parse_token(cookie)
    if parsed is None:
        return None
    org_id, secret = parsed
    token_hash = hash_secret(secret)
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        row = (
            await conn.execute(
                text(
                    "SELECT user_id, last_seen_at < now() - :touch AS stale FROM admin_sessions"
                    " WHERE org_id = :org AND token_hash = :hash"
                    " AND last_seen_at > now() - :idle"
                ),
                {"org": org_id, "hash": token_hash, "idle": idle, "touch": TOUCH_AFTER},
            )
        ).one_or_none()
        if row is None:
            return None
        if row.stale:
            await conn.execute(
                text(
                    "UPDATE admin_sessions SET last_seen_at = now()"
                    " WHERE org_id = :org AND token_hash = :hash"
                ),
                {"org": org_id, "hash": token_hash},
            )
    return Principal(user_id=row.user_id, org_id=org_id)


async def delete_session(conn: AsyncConnection, org_id: uuid.UUID, secret: str) -> uuid.UUID | None:
    """Delete the session with this secret in this Organization; its user id, or None if absent."""
    user_id: uuid.UUID | None = (
        await conn.execute(
            text(
                "DELETE FROM admin_sessions WHERE org_id = :org AND token_hash = :hash"
                " RETURNING user_id"
            ),
            {"org": org_id, "hash": hash_secret(secret)},
        )
    ).scalar_one_or_none()
    return user_id


async def delete_user_sessions(
    conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Delete every session of the user (sign-out everywhere, e.g. after a password change)."""
    await conn.execute(
        text("DELETE FROM admin_sessions WHERE org_id = :org AND user_id = :user"),
        {"org": org_id, "user": user_id},
    )
