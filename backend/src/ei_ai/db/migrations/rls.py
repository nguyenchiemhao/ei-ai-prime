"""Row-level security helpers shared by every migration, so the pattern cannot drift (D46).

NULLIF is required: after a transaction that used ``set_config(..., true)`` ends, the setting reads
``''`` (not NULL) in the same session, and ``''::uuid`` would raise instead of matching nothing.
With no tenant context the key is NULL, the comparison is NULL and no row is visible.
"""

from alembic import op

from ei_ai.db.migrations.roles import APP_ROLE

TENANT_SETTING = "NULLIF(current_setting('app.current_org', true), '')::uuid"


def tenant_rls_statements(table: str, key: str = "org_id") -> list[str]:
    """ENABLE + FORCE row-level security and the ``tenant_isolation`` policy on ``key``.

    No ``TO`` clause: the policy binds every role. FORCE makes the owner subject to it as well.
    """
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {table}"
        f" USING ({key} = {TENANT_SETTING}) WITH CHECK ({key} = {TENANT_SETTING})",
    ]


def grant_dml_statement(table: str) -> str:
    """The only privileges the application role ever gets (TRUNCATE would bypass RLS)."""
    return f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}"


def enable_tenant_rls(table: str, key: str = "org_id") -> None:
    for statement in tenant_rls_statements(table, key):
        op.execute(statement)


def grant_dml(table: str) -> None:
    op.execute(grant_dml_statement(table))
