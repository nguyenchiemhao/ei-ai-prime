"""One-time set-password links (FND-04 issues them, FND-05 redeems them).

The token is self-locating: ``<org_id>.<secret>``. The link carries it in the URL fragment
(``/set-password#token=...``): a fragment is never sent to a server, so the secret cannot reach an
access log, a proxy or a Referer header; the FND-05 page reads it from ``location.hash``.
The redeemer takes the Organization from the token, opens a tenant transaction for it and matches
``sha256(secret)`` inside that Organization only, so no lookup ever crosses tenants (D46) and no
table needs an isolation exemption. Only the hash is stored; the secret is shown once and never
logged (D52).
"""

import hashlib
import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.db.tenant import tenant_transaction

LINK_TTL = timedelta(hours=24)
_SECRET = re.compile(r"[A-Za-z0-9_-]{43}")


def new_secret() -> str:
    """32 random bytes from the OS CSPRNG, URL-safe base64 without padding (43 characters)."""
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    """Lower-case hex SHA-256 of the secret: the only form that is stored."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def format_token(org_id: uuid.UUID, secret: str) -> str:
    """The token ``<org_id>.<secret>`` that the link carries."""
    return f"{org_id}.{secret}"


def parse_token(token: str) -> tuple[uuid.UUID, str] | None:
    """(Organization id, secret), or None when the token is malformed."""
    raw_org, dot, secret = token.partition(".")
    if not dot or not _SECRET.fullmatch(secret):
        return None
    try:
        return uuid.UUID(raw_org), secret
    except ValueError:
        return None


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
