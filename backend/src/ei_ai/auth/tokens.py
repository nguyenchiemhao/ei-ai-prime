"""Self-locating secrets ``<org_id>.<secret>`` shared by set-password links and sessions.

Only the SHA-256 of a secret is stored; the secret is shown once and never logged (D52). The
Organization id in the token lets the redeemer open a tenant transaction before matching the
hash, so no lookup crosses tenants (D46).
"""

import hashlib
import re
import secrets
import uuid

_SECRET = re.compile(r"[A-Za-z0-9_-]{43}")


def new_secret() -> str:
    """32 random bytes from the OS CSPRNG, URL-safe base64 without padding (43 characters)."""
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    """Lower-case hex SHA-256 of the secret: the only form that is stored."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def format_token(org_id: uuid.UUID, secret: str) -> str:
    """The token ``<org_id>.<secret>``."""
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
