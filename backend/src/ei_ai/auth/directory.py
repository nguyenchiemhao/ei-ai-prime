"""The sign-in directory (EA-22, R42): which Organizations have a user with this email.

The only cross-tenant read in the codebase (owner decision 2026-10-20). Sign-in knows an email but
not the Organization, and row-level security hides every ``users`` row until the tenant is known,
so this module alone connects as the login role ``ei_ai_signin``. That role can read only
``users(id, org_id, email)`` (migration 0004, schema guard G4 allowance and G14). The engine stays
private, the directory runs exactly one query and never opens a tenant transaction; everything
after the lookup runs as ``ei_ai_app`` in the candidate Organization's tenant transaction.
Only the app factory, the auth router, sign-in and password reset may import it
(``tests/test_sign_in_directory_imports.py``).
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ei_ai.db.engine import to_sqlalchemy_url

# The directory's only query. At most 10 candidates per email (R44): sign-in tries each in turn,
# so the work per request is bounded.
_FIND_ACCOUNTS = text("SELECT org_id, id FROM users WHERE email = :email ORDER BY org_id LIMIT 10")


@dataclass(frozen=True)
class Account:
    """A user with the looked-up email, and the Organization it belongs to."""

    org_id: UUID
    user_id: UUID


class SignInDirectory:
    """Owns the private engine of the sign-in lookup role."""

    def __init__(self, url: str) -> None:
        # A small pool: one short indexed query per sign-in or reset request.
        self._engine = create_async_engine(
            to_sqlalchemy_url(url), pool_size=2, max_overflow=0, pool_pre_ping=True
        )

    async def find_accounts(self, email: str) -> list[Account]:
        """The accounts whose email equals ``email`` exactly (callers pass the stored, lower-case
        form), ordered by Organization id; empty when there is none."""
        async with self._engine.connect() as conn:
            result = await conn.execute(_FIND_ACCOUNTS, {"email": email})
            return [Account(org_id=row.org_id, user_id=row.id) for row in result]

    async def dispose(self) -> None:
        await self._engine.dispose()
