"""Sign-in lookup (EA-22, R42, owner decision 2026-10-20): the only cross-tenant read.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20

Sign-in by email and password must find the user's Organizations before any tenant is known, which
the standard policy forbids. The login role ``ei_ai_signin`` (created by
``infra/db/init/030-signin-role.sh``) gets exactly SELECT on ``users(id, org_id, email)`` and one
permissive SELECT policy bound to it alone. No table-level privilege, no other table, no write, no
grant option; ``ei_ai_app`` and ``ei_ai_migrator`` still see no ``users`` row without
``app.current_org``. The schema guard matches the policy exactly (``SIGN_IN_LOOKUP_ALLOWANCE``,
G4) and the grants exactly (G14).
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.roles import SIGNIN_ROLE

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(f"GRANT SELECT (id, org_id, email) ON users TO {SIGNIN_ROLE}")
    op.execute(
        f"CREATE POLICY sign_in_lookup ON users AS PERMISSIVE FOR SELECT TO {SIGNIN_ROLE}"
        " USING (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY sign_in_lookup ON users")
    op.execute(f"REVOKE SELECT (id, org_id, email) ON users FROM {SIGNIN_ROLE}")
