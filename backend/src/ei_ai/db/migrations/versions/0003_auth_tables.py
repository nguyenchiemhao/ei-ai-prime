"""Admin sign-in (EA-22): password credentials and server-side sessions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20

``user_credentials`` holds the Argon2id hash and the lockout counters of one user; a user without
a row has never set a password and cannot sign in. ``admin_sessions`` stores only the SHA-256 of
the session secret, never the cookie value. Both tables follow the standard tenant pattern: the
composite foreign key keeps a row inside the Organization of its user.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_credentials (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            user_id uuid NOT NULL,
            password_hash text NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
            password_set_at timestamptz NOT NULL DEFAULT now(),
            failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
            failure_window_started_at timestamptz,
            locked_until timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, user_id),
            FOREIGN KEY (org_id, user_id) REFERENCES users (org_id, id)
        )
        """
    )
    enable_tenant_rls("user_credentials")
    grant_dml("user_credentials")

    op.execute(
        """
        CREATE TABLE admin_sessions (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            user_id uuid NOT NULL,
            token_hash text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            created_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, token_hash),
            FOREIGN KEY (org_id, user_id) REFERENCES users (org_id, id)
        )
        """
    )
    op.execute("CREATE INDEX admin_sessions_org_user_idx ON admin_sessions (org_id, user_id)")
    enable_tenant_rls("admin_sessions")
    grant_dml("admin_sessions")


def downgrade() -> None:
    op.execute("DROP TABLE admin_sessions")
    op.execute("DROP TABLE user_credentials")
