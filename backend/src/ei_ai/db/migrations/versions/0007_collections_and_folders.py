"""Collections and folders (EA-32): the knowledge containers of a Workspace and their audit targets.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21

``collections`` belong to one Workspace; the name is unique there, ignoring case. The access level
(``public``, ``authenticated`` or ``restricted``) and the group list are stored together: a
restricted collection has at least one group, any other level has none, and there are at most 20.
Group names are stored normalised by the service, so a later query can match them with ``&&``.

``folders`` nest up to three levels inside one collection. The composite foreign keys keep a
parent in the same Organization and collection, and deleting a collection or a parent removes the
folders below it. Sibling names are unique ignoring case; a top-level folder has no parent, which
the unique index maps to the nil UUID because NULLs never collide.

``audit_events.target_type`` also accepts ``collection`` and ``folder``. A downgrade fails while
such an event exists: audit events are never deleted.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _target_type_check(values: Sequence[str]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return (
        "ALTER TABLE audit_events ADD CONSTRAINT audit_events_target_type_check"
        f" CHECK (target_type IN ({listed}))"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE collections (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            workspace_id uuid NOT NULL,
            name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
            subtitle text CHECK (char_length(subtitle) BETWEEN 1 AND 200),
            access_level text NOT NULL
                CHECK (access_level IN ('public', 'authenticated', 'restricted')),
            groups text[] NOT NULL DEFAULT '{}',
            local_only boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
            CHECK ((access_level = 'restricted') = (cardinality(groups) >= 1)),
            CHECK (cardinality(groups) <= 20)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX collections_workspace_name_key"
        " ON collections (org_id, workspace_id, lower(name))"
    )
    op.execute("CREATE INDEX collections_workspace_idx ON collections (org_id, workspace_id)")
    enable_tenant_rls("collections")
    grant_dml("collections")

    op.execute(
        """
        CREATE TABLE folders (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            collection_id uuid NOT NULL,
            parent_id uuid,
            name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
            depth smallint NOT NULL CHECK (depth BETWEEN 1 AND 3),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, collection_id, id),
            FOREIGN KEY (org_id, collection_id) REFERENCES collections (org_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (org_id, collection_id, parent_id)
                REFERENCES folders (org_id, collection_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX folders_sibling_name_key ON folders"
        " (org_id, collection_id,"
        " COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name))"
    )
    op.execute("CREATE INDEX folders_collection_idx ON folders (org_id, collection_id)")
    enable_tenant_rls("folders")
    grant_dml("folders")

    op.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_target_type_check")
    op.execute(
        _target_type_check(("organization", "workspace", "user", "model", "collection", "folder"))
    )


def downgrade() -> None:
    # Adding the old check validates every row, whatever the row policy, so the downgrade stops
    # while a collection or folder audit event exists.
    op.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_target_type_check")
    op.execute(_target_type_check(("organization", "workspace", "user", "model")))
    op.execute("DROP TABLE folders")
    op.execute("DROP TABLE collections")
