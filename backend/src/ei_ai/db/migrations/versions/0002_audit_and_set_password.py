"""Provisioning (FND-04): audit events, set-password tokens, unique Organization names.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19

``organizations_name_lower_key`` is a constraint, not an RLS exemption: rows of other Organizations
stay invisible; a duplicate insert by the platform CLI fails with a unique violation. Only the CLI
inserts Organizations (no HTTP route does).

``audit_events`` is append-only by convention until FND-08 (EA-25) revokes UPDATE and DELETE; it
gets the standard grants so the cross-org fixtures and cleanup work like for every table.
``set_password_tokens`` stores only the sha256 of the secret, never the secret itself.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX organizations_name_lower_key ON organizations (lower(name))")

    op.execute(
        r"""
        CREATE TABLE audit_events (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            actor text NOT NULL CHECK (char_length(actor) BETWEEN 1 AND 100),
            action text NOT NULL CHECK (action ~ '^[a-z_]+(\.[a-z_]+)+$'),
            target_type text NOT NULL
                CHECK (target_type IN ('organization', 'workspace', 'user')),
            target_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id)
        )
        """
    )
    enable_tenant_rls("audit_events")
    grant_dml("audit_events")

    # Composite foreign key: a token can only belong to a user of its own Organization.
    op.execute(
        """
        CREATE TABLE set_password_tokens (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            user_id uuid NOT NULL,
            token_hash text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, token_hash),
            FOREIGN KEY (org_id, user_id) REFERENCES users (org_id, id)
        )
        """
    )
    enable_tenant_rls("set_password_tokens")
    grant_dml("set_password_tokens")


def downgrade() -> None:
    op.execute("DROP TABLE set_password_tokens")
    op.execute("DROP TABLE audit_events")
    op.execute("DROP INDEX organizations_name_lower_key")
