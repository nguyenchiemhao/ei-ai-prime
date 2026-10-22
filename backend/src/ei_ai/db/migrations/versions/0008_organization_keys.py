"""Per-Organization data keys (EA-20): the wrapped key of each Organization.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22

One row per Organization holds its data key wrapped (AES-256-GCM) by the platform master key:
60 bytes while the key is live, NULL once it is destroyed (``destroyed_at`` is set exactly then).
``kek_id`` is the non-secret fingerprint of the master key that wrapped it. The migration creates
no key: the migration role holds no master key and cannot see Organizations. The demo seed adds
the keys of the demo Organizations; ``org create`` adds one for each new Organization.

The downgrade drops every wrapped key, which crypto-shreds every Organization: never downgrade
0008 on a database that holds encrypted data.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE organization_keys (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            wrapped_key bytea CHECK (octet_length(wrapped_key) = 60),
            kek_id text NOT NULL CHECK (kek_id ~ '^[0-9a-f]{16}$'),
            created_at timestamptz NOT NULL DEFAULT now(),
            destroyed_at timestamptz,
            UNIQUE (org_id),
            UNIQUE (org_id, id),
            CHECK ((wrapped_key IS NULL) = (destroyed_at IS NOT NULL))
        )
        """
    )
    enable_tenant_rls("organization_keys")
    grant_dml("organization_keys")


def downgrade() -> None:
    op.execute("DROP TABLE organization_keys")
