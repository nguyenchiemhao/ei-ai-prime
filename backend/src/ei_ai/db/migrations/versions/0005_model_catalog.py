"""Model catalog (EA-24): pinned model versions per Organization, the cloud switch, audit target.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20

``model_catalog`` is a standard tenant table: an Organization sees and calls only its own rows. The
pin columns (what the gateway calls: kind, model id, version, digest, source revision, deployment
and provider) can never be updated, for any role, by the trigger below: a new file is a new row
(D18). There is no endpoint column on purpose: a provider key maps to a configured base URL, so a
catalog row cannot point the gateway at an arbitrary host (SSRF, P35).

``organizations.allow_cloud_models`` is the Organization's "Allow cloud models" switch (D17, off
by default). ``audit_events.target_type`` also accepts ``model``. A downgrade fails while a
``model`` audit event exists: audit events are never deleted.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PIN_COLUMNS = ("kind", "model_id", "version", "digest", "source_revision", "deployment", "provider")


def _target_type_check(values: Sequence[str]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return (
        "ALTER TABLE audit_events ADD CONSTRAINT audit_events_target_type_check"
        f" CHECK (target_type IN ({listed}))"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_catalog (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            kind text NOT NULL CHECK (kind IN ('chat', 'embedding', 'rerank')),
            display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
            model_id text NOT NULL CHECK (model_id ~ '^[a-z0-9][a-z0-9._-]{0,99}$'),
            version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'),
            digest text CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
            source_revision text CHECK (char_length(source_revision) BETWEEN 1 AND 500),
            deployment text NOT NULL CHECK (deployment IN ('local', 'cloud')),
            provider text NOT NULL CHECK (provider ~ '^[a-z0-9][a-z0-9-]{0,49}$'),
            vietnamese_quality text CHECK (vietnamese_quality IN ('good', 'fair', 'poor')),
            vietnamese_quality_measured boolean NOT NULL DEFAULT false,
            tool_use boolean NOT NULL DEFAULT false,
            context_window integer CHECK (context_window > 0),
            speed text CHECK (speed IN ('faster', 'slower')),
            status text NOT NULL DEFAULT 'available'
                CHECK (status IN ('available', 'retiring', 'retired')),
            retirement_date date,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, model_id, version),
            CHECK (deployment = 'cloud' OR digest IS NOT NULL),
            CHECK (status <> 'retiring' OR retirement_date IS NOT NULL)
        )
        """
    )
    enable_tenant_rls("model_catalog")
    grant_dml("model_catalog")

    changed = " OR ".join(f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in PIN_COLUMNS)
    # Owned by the migration role and SECURITY INVOKER (schema guard G10).
    op.execute(
        f"""
        CREATE FUNCTION model_catalog_pin_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF {changed} THEN
                RAISE EXCEPTION 'model_catalog pin columns are immutable';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER model_catalog_pin_immutable BEFORE UPDATE ON model_catalog"
        " FOR EACH ROW EXECUTE FUNCTION model_catalog_pin_immutable()"
    )

    op.execute(
        "ALTER TABLE organizations ADD COLUMN allow_cloud_models boolean NOT NULL DEFAULT false"
    )

    op.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_target_type_check")
    op.execute(_target_type_check(("organization", "workspace", "user", "model")))


def downgrade() -> None:
    op.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_target_type_check")
    op.execute(_target_type_check(("organization", "workspace", "user")))
    op.execute("ALTER TABLE organizations DROP COLUMN allow_cloud_models")
    op.execute("DROP TABLE model_catalog")
    op.execute("DROP FUNCTION model_catalog_pin_immutable()")
