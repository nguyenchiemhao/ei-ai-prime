"""One-time set-password links (FND-04 issues them, FND-05 redeems them).

The token is self-locating: ``<org_id>.<secret>``. The link carries it in the URL fragment
(``/set-password#token=...``): a fragment is never sent to a server, so the secret cannot reach an
access log, a proxy or a Referer header; the FND-05 page reads it from ``location.hash``.
The redeemer takes the Organization from the token, opens a tenant transaction for it and matches
``sha256(secret)`` inside that Organization only, so no lookup ever crosses tenants (D46) and no
table needs an isolation exemption. Only the hash is stored; the secret is shown once and never
logged (D52).
"""

import uuid
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.audit.events import USER_PASSWORD_SET, record_event, user_actor
from ei_ai.auth.credentials import upsert_credential
from ei_ai.auth.sessions import delete_user_sessions
from ei_ai.auth.tokens import format_token, hash_secret, new_secret, parse_token
from ei_ai.db.tenant import tenant_transaction

LINK_TTL = timedelta(hours=24)

__all__ = [
    "LINK_TTL",
    "format_token",
    "hash_secret",
    "issue_token",
    "new_secret",
    "parse_token",
    "redeem_in_transaction",
    "redeem_set_password_token",
    "set_password_link",
    "set_password_with_token",
]


def set_password_link(base_url: str, org_id: uuid.UUID, secret: str) -> str:
    """The admin URL of the set-password page with the token in the fragment, never the query."""
    return f"{base_url}/set-password#token={format_token(org_id, secret)}"


async def issue_token(conn: AsyncConnection, org_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Replace the user's unused tokens with a new one valid for ``LINK_TTL``; return its secret.

    Runs inside the caller's tenant transaction for ``org_id``.
    """
    secret = new_secret()
    params = {"org": org_id, "user": user_id}
    await conn.execute(
        text(
            "DELETE FROM set_password_tokens"
            " WHERE org_id = :org AND user_id = :user AND used_at IS NULL"
        ),
        params,
    )
    await conn.execute(
        text(
            "INSERT INTO set_password_tokens (org_id, user_id, token_hash, expires_at)"
            " VALUES (:org, :user, :hash, now() + :ttl)"
        ),
        {**params, "hash": hash_secret(secret), "ttl": LINK_TTL},
    )
    return secret


async def redeem_in_transaction(
    conn: AsyncConnection, org_id: uuid.UUID, secret: str
) -> uuid.UUID | None:
    """Mark an unused, unexpired token of this Organization used; its user id, else None.

    Runs inside the caller's tenant transaction, so the redeem commits with the caller's work.
    """
    result = await conn.execute(
        text(
            "UPDATE set_password_tokens SET used_at = now()"
            " WHERE org_id = :org AND token_hash = :hash"
            " AND used_at IS NULL AND expires_at > now()"
            " RETURNING user_id"
        ),
        {"org": org_id, "hash": hash_secret(secret)},
    )
    user_id: uuid.UUID | None = result.scalar_one_or_none()
    return user_id


async def redeem_set_password_token(engine: AsyncEngine, token: str) -> uuid.UUID | None:
    """Mark an unused, unexpired token used and return its user id; otherwise None.

    Unknown, used, expired, malformed and wrong-Organization tokens all give the same None; a
    malformed token never reaches the database.
    """
    parsed = parse_token(token)
    if parsed is None:
        return None
    org_id, secret = parsed
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        return await redeem_in_transaction(conn, org_id, secret)


async def set_password_with_token(
    engine: AsyncEngine, token: str, password_hash: str
) -> uuid.UUID | None:
    """Redeem the token, store the new hash (clearing lockout), end the user's sessions and audit,
    in one transaction. None (nothing changed) for any invalid token."""
    parsed = parse_token(token)
    if parsed is None:
        return None
    org_id, secret = parsed
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        user_id = await redeem_in_transaction(conn, org_id, secret)
        if user_id is None:
            return None
        await upsert_credential(conn, org_id, user_id, password_hash)
        await delete_user_sessions(conn, org_id, user_id)
        await record_event(conn, org_id, user_actor(user_id), USER_PASSWORD_SET, "user", user_id)
    return user_id
