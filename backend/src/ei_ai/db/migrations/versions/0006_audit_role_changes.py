"""Audit role changes (EA-23): the Workspace and the old and new value of a change.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21

``audit_events`` gets three nullable columns so a role change records where and from what to what
(AC6): ``workspace_id`` (NULL for an Organization role), ``old_value`` and ``new_value`` (a role
code, NULL meaning no role). The values are lower-case codes only, so no free text or personal
data can land in them (D52).

``workspace_id`` has no foreign key on purpose: audit rows are append-only and outlive the
Workspace, like ``target_id``; the caller resolves it inside its own tenant transaction. The row
policy is unchanged. A downgrade fails while a row uses the columns: audit events are never
deleted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE audit_events
            ADD COLUMN workspace_id uuid NULL,
            ADD COLUMN old_value text NULL CHECK (old_value ~ '^[a-z_]{1,40}$'),
            ADD COLUMN new_value text NULL CHECK (new_value ~ '^[a-z_]{1,40}$')
        """
    )


def downgrade() -> None:
    # Validating a constraint reads every row, whatever the row policy: it refuses the downgrade
    # while any event has the columns set. The columns' own drop then removes the constraint.
    op.execute(
        "ALTER TABLE audit_events ADD CONSTRAINT audit_events_role_columns_unused"
        " CHECK (workspace_id IS NULL AND old_value IS NULL AND new_value IS NULL)"
    )
    op.execute("ALTER TABLE audit_events DROP COLUMN workspace_id")
    op.execute("ALTER TABLE audit_events DROP COLUMN old_value")
    op.execute("ALTER TABLE audit_events DROP COLUMN new_value")
