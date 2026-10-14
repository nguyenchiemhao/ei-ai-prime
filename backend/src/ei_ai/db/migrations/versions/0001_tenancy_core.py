"""Tenancy core: Organization, Workspace, user, memberships, with row-level security.

Revision ID: 0001
Revises:
Create Date: 2026-10-14

Each table is followed by its RLS policy and grants (D46). Hierarchy: Platform -> Organization ->
Workspace. A user belongs to exactly one Organization (owner decision 2026-10-14), so every table,
``users`` included, has ``org_id``, the standard tenant policy and composite foreign keys.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME_CHECK = "CHECK (char_length(name) BETWEEN 1 AND 200)"


def upgrade() -> None:
    # UUIDv7 (RFC 9562): a random v4 UUID with the first 48 bits replaced by the millisecond
    # timestamp and the version nibble set to 7 (the v4 variant bits are already right).
    op.execute(
        """
        CREATE FUNCTION uuid_generate_v7() RETURNS uuid LANGUAGE sql VOLATILE AS $$
            SELECT encode(
                set_bit(
                    set_bit(
                        overlay(
                            uuid_send(gen_random_uuid())
                            PLACING substring(
                                int8send(
                                    floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint
                                ) FROM 3
                            ) FROM 1 FOR 6
                        ),
                        52, 1
                    ),
                    53, 1
                ),
                'hex'
            )::uuid
        $$
        """
    )

    # RLS key of organizations is its own id.
    op.execute(
        f"""
        CREATE TABLE organizations (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            name text NOT NULL {NAME_CHECK},
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    enable_tenant_rls("organizations", key="id")
    grant_dml("organizations")

    op.execute(
        f"""
        CREATE TABLE workspaces (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            name text NOT NULL {NAME_CHECK},
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, name)
        )
        """
    )
    enable_tenant_rls("workspaces")
    grant_dml("workspaces")

    # A user belongs to one Organization. The same email may exist in several Organizations as
    # different users: nothing is unique across Organizations, so there is no cross-tenant oracle.
    op.execute(
        """
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            email text NOT NULL
                CHECK (email = lower(email) AND char_length(email) BETWEEN 3 AND 320),
            display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, email)
        )
        """
    )
    enable_tenant_rls("users")
    grant_dml("users")

    # Composite foreign keys: referential-integrity checks bypass RLS, so a plain id reference could
    # point at another Organization's row. (org_id, ...) on both sides blocks that.
    op.execute(
        """
        CREATE TABLE memberships (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            user_id uuid NOT NULL,
            org_role text CHECK (org_role IN ('org_owner', 'org_admin')),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, user_id),
            FOREIGN KEY (org_id, user_id) REFERENCES users (org_id, id)
        )
        """
    )
    enable_tenant_rls("memberships")
    grant_dml("memberships")

    # (org_id, user_id) -> memberships -> users: a Workspace member is an Organization member.
    op.execute(
        """
        CREATE TABLE workspace_memberships (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            user_id uuid NOT NULL,
            role text NOT NULL CHECK (role IN (
                'workspace_admin', 'developer', 'builder', 'knowledge_editor',
                'reviewer', 'viewer', 'member'
            )),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, workspace_id, user_id),
            FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
            FOREIGN KEY (org_id, user_id) REFERENCES memberships (org_id, user_id)
        )
        """
    )
    enable_tenant_rls("workspace_memberships")
    grant_dml("workspace_memberships")


def downgrade() -> None:
    op.execute("DROP TABLE workspace_memberships")
    op.execute("DROP TABLE memberships")
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE workspaces")
    op.execute("DROP TABLE organizations")
    op.execute("DROP FUNCTION uuid_generate_v7()")
