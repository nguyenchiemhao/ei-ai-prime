from ei_ai.db.migrations import rls


def test_tenant_setting_reads_the_context_through_nullif() -> None:
    assert rls.TENANT_SETTING == "NULLIF(current_setting('app.current_org', true), '')::uuid"


def test_tenant_rls_enables_forces_and_adds_the_policy_on_org_id() -> None:
    statements = rls.tenant_rls_statements("workspaces")

    assert statements == [
        "ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE workspaces FORCE ROW LEVEL SECURITY",
        "CREATE POLICY tenant_isolation ON workspaces"
        " USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        " WITH CHECK (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)",
    ]


def test_tenant_rls_can_use_another_key_column() -> None:
    policy = rls.tenant_rls_statements("organizations", key="id")[2]

    assert "USING (id = NULLIF(" in policy
    assert "WITH CHECK (id = NULLIF(" in policy


def test_policy_never_names_a_role_so_it_binds_every_role() -> None:
    assert " TO " not in rls.tenant_rls_statements("workspaces")[2]


def test_grant_dml_gives_the_app_role_the_four_dml_privileges_only() -> None:
    assert rls.grant_dml_statement("workspaces") == (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON workspaces TO ei_ai_app"
    )
