"""AC1: every rule of the schema guard, on synthetic catalog snapshots (no database)."""

from dataclasses import replace

import pytest

from ei_ai.db.catalog import (
    CatalogSnapshot,
    ColumnInfo,
    ColumnPrivilege,
    ForeignKeyInfo,
    FunctionInfo,
    PolicyInfo,
    Privilege,
    TableInfo,
)
from ei_ai.db.schema_guard import Violation, find_violations, guarded_table_names

SETTING = "NULLIF(current_setting('app.current_org'::text, true), ''::text)"
DML = tuple(Privilege("ei_ai_app", p) for p in ("DELETE", "INSERT", "SELECT", "UPDATE"))
SIGNIN = "ei_ai_signin"
# Revision 0004: the one reviewed policy with a TO clause and the sign-in role's column grants.
LOOKUP = PolicyInfo("sign_in_lookup", "SELECT", "true", None, roles=(SIGNIN,))
LOOKUP_COLUMNS = tuple(ColumnPrivilege(c, SIGNIN, "SELECT") for c in ("email", "id", "org_id"))


def _policy(key: str = "org_id", name: str = "tenant_isolation") -> PolicyInfo:
    expression = f"({key} = ({SETTING})::uuid)"
    return PolicyInfo(name, "ALL", expression, expression)


def _tenant_table(name: str, key: str = "org_id", **changes: object) -> TableInfo:
    table = TableInfo(
        name=name,
        kind="table",
        owner="ei_ai_migrator",
        rls_enabled=True,
        rls_forced=True,
        security_invoker=False,
        columns=(
            ColumnInfo("id", "uuid", True),
            *([ColumnInfo("org_id", "uuid", True)] if key == "org_id" else []),
        ),
        policies=(_policy(key),),
        privileges=DML,
    )
    return replace(table, **changes)  # type: ignore[arg-type]


def _good() -> CatalogSnapshot:
    """Mirrors the tenancy core of revision 0001 plus the sign-in lookup of revision 0004."""
    user_fk = ForeignKeyInfo("user_fk", ("org_id", "user_id"), "users", ("org_id", "id"))
    workspace_fk = ForeignKeyInfo(
        "ws_fk", ("org_id", "workspace_id"), "workspaces", ("org_id", "id")
    )
    return CatalogSnapshot(
        tables=(
            _tenant_table("organizations", key="id"),
            _tenant_table("workspaces"),
            _tenant_table("users", policies=(_policy(), LOOKUP), column_privileges=LOOKUP_COLUMNS),
            _tenant_table("memberships", foreign_keys=(user_fk,)),
            _tenant_table("workspace_memberships", foreign_keys=(workspace_fk,)),
            TableInfo("alembic_version", "table", "ei_ai_migrator", False, False, False),
        ),
        functions=(FunctionInfo("uuid_generate_v7", "ei_ai_migrator", False),),
    )


def _with_table(snapshot: CatalogSnapshot, name: str, **changes: object) -> CatalogSnapshot:
    tables = tuple(
        replace(t, **changes) if t.name == name else t  # type: ignore[arg-type]
        for t in snapshot.tables
    )
    return replace(snapshot, tables=tables)


def _codes(snapshot: CatalogSnapshot) -> list[tuple[str, str]]:
    return [(v.code, v.subject) for v in find_violations(snapshot)]


def test_the_reference_schema_has_no_violations() -> None:
    assert find_violations(_good()) == []


def test_every_table_except_alembic_version_is_a_tenant_table() -> None:
    assert guarded_table_names(_good()) == [
        "organizations",
        "workspaces",
        "users",
        "memberships",
        "workspace_memberships",
    ]


def test_g12_users_without_org_id_is_a_violation() -> None:
    columns = (ColumnInfo("id", "uuid", True), ColumnInfo("email", "text", True))

    assert ("G12", "users") in _codes(_with_table(_good(), "users", columns=columns))


def test_g12_table_without_org_id_is_a_violation() -> None:
    probe = _tenant_table("guard_probe", columns=(ColumnInfo("id", "uuid", True),))
    snapshot = replace(_good(), tables=(*_good().tables, probe))

    assert ("G12", "guard_probe") in _codes(snapshot)


def test_g12_unknown_platform_table_is_not_exempt() -> None:
    probe = _tenant_table("accounts", columns=(ColumnInfo("id", "uuid", True),))

    assert ("G12", "accounts") in _codes(replace(_good(), tables=(*_good().tables, probe)))


def test_g1_nullable_org_id() -> None:
    columns = (ColumnInfo("id", "uuid", True), ColumnInfo("org_id", "uuid", False))

    assert _codes(_with_table(_good(), "workspaces", columns=columns)) == [("G1", "workspaces")]


def test_g1_org_id_of_the_wrong_type() -> None:
    columns = (ColumnInfo("id", "uuid", True), ColumnInfo("org_id", "text", True))

    assert ("G1", "workspaces") in _codes(_with_table(_good(), "workspaces", columns=columns))


def test_g2_row_level_security_not_enabled() -> None:
    codes = _codes(_with_table(_good(), "workspaces", rls_enabled=False))

    assert codes == [("G2", "workspaces")]


def test_g2_row_level_security_not_forced() -> None:
    codes = _codes(_with_table(_good(), "workspaces", rls_forced=False))

    assert codes == [("G2", "workspaces")]


def test_g3_no_policy() -> None:
    codes = _codes(_with_table(_good(), "workspaces", policies=()))

    assert ("G3", "workspaces") in codes


def test_g4_policy_without_nullif() -> None:
    bare = "(org_id = (current_setting('app.current_org'::text, true))::uuid)"
    policy = PolicyInfo("tenant_isolation", "ALL", bare, bare)

    codes = _codes(_with_table(_good(), "workspaces", policies=(policy,)))

    assert ("G4", "workspaces") in codes


def test_g4_policy_whose_check_lacks_nullif() -> None:
    policy = PolicyInfo("tenant_isolation", "ALL", _policy().using, "true")

    assert ("G4", "workspaces") in _codes(_with_table(_good(), "workspaces", policies=(policy,)))


def test_g4_ignores_whitespace_and_case() -> None:
    spaced = f"(org_id =  (\n  {SETTING.lower()})::uuid)"
    policy = PolicyInfo("tenant_isolation", "ALL", spaced, spaced)

    assert _codes(_with_table(_good(), "workspaces", policies=(policy,))) == []


def _extra_policy(expression: str, permissive: bool = True) -> PolicyInfo:
    return PolicyInfo("extra", "SELECT", expression, None, permissive=permissive)


def test_g4_extra_permissive_policy_that_only_checks_the_context_is_set() -> None:
    # Mutation M-D12: permissive policies are OR-ed, so this one shows every row to any tenant.
    extra = _extra_policy(f"(({SETTING})::uuid IS NOT NULL)")
    policies = (_policy(), extra)

    assert ("G4", "workspaces") in _codes(_with_table(_good(), "workspaces", policies=policies))


def test_g4_key_comparison_or_ed_with_true() -> None:
    # Mutation M-D13.
    expression = f"((org_id = ({SETTING})::uuid) OR true)"
    policy = PolicyInfo("tenant_isolation", "ALL", expression, expression)

    assert ("G4", "workspaces") in _codes(_with_table(_good(), "workspaces", policies=(policy,)))


def test_g4_key_comparison_or_ed_with_its_negation() -> None:
    # Mutation M-D14.
    expression = f"((org_id = ({SETTING})::uuid) OR (org_id <> ({SETTING})::uuid))"
    policy = PolicyInfo("tenant_isolation", "ALL", expression, expression)

    assert ("G4", "workspaces") in _codes(_with_table(_good(), "workspaces", policies=(policy,)))


def test_g5_a_subquery_comparing_another_tables_org_id_is_not_the_tenant_key() -> None:
    expression = f"(EXISTS ( SELECT 1 FROM memberships m WHERE (m.org_id = ({SETTING})::uuid)))"
    policy = PolicyInfo("tenant_isolation", "ALL", expression, expression)

    codes = _codes(_with_table(_good(), "workspaces", policies=(policy,)))

    assert ("G4", "workspaces") in codes
    assert ("G5", "workspaces") in codes


def test_g4_a_restrictive_policy_can_only_narrow_and_is_allowed() -> None:
    restrictive = _extra_policy("(name <> 'hidden'::text)", permissive=False)

    assert _codes(_with_table(_good(), "workspaces", policies=(_policy(), restrictive))) == []


def test_g13_restrictive_policy_without_nullif() -> None:
    # A restrictive policy cannot widen access, but without NULLIF it errors on '' instead of
    # failing closed (EA-18 follow-up R2-2).
    restrictive = _extra_policy(
        "(org_id = (current_setting('app.current_org'::text, true))::uuid)", permissive=False
    )

    codes = _codes(_with_table(_good(), "workspaces", policies=(_policy(), restrictive)))

    assert codes == [("G13", "workspaces")]


def test_g13_restrictive_policy_with_the_standard_form_is_fine() -> None:
    restrictive = _extra_policy(
        f"((org_id = ({SETTING})::uuid) AND (name <> 'hidden'::text))", False
    )

    assert _codes(_with_table(_good(), "workspaces", policies=(_policy(), restrictive))) == []


def test_g13_mixing_the_standard_form_with_a_bare_setting_is_reported() -> None:
    bare = "(current_setting('app.current_org'::text, true) <> 'x'::text)"
    restrictive = _extra_policy(f"((org_id = ({SETTING})::uuid) AND {bare})", permissive=False)

    codes = _codes(_with_table(_good(), "workspaces", policies=(_policy(), restrictive)))

    assert codes == [("G13", "workspaces")]


def test_g13_the_message_names_the_policy_and_the_rule_only() -> None:
    restrictive = _extra_policy(
        "(org_id = (current_setting('app.current_org'::text, true))::uuid)", permissive=False
    )

    violations = find_violations(
        _with_table(_good(), "workspaces", policies=(_policy(), restrictive))
    )

    assert [str(v) for v in violations] == [
        "G13 workspaces: restrictive policy extra reads app.current_org without the NULLIF form"
    ]


def _with_users_policies(*policies: PolicyInfo) -> CatalogSnapshot:
    return _with_table(_good(), "users", policies=(_policy(), *policies))


def test_g4_allows_exact_sign_in_lookup_policy() -> None:
    users = next(t for t in _good().tables if t.name == "users")

    assert LOOKUP in users.policies
    assert _codes(_good()) == []


@pytest.mark.parametrize("roles", [("ei_ai_app",), ("PUBLIC",), (SIGNIN, "ei_ai_app")])
def test_g4_rejects_lookup_policy_with_other_role(roles: tuple[str, ...]) -> None:
    snapshot = _with_users_policies(replace(LOOKUP, roles=roles))

    assert ("G4", "users") in _codes(snapshot)


@pytest.mark.parametrize("command", ["ALL", "INSERT", "UPDATE", "DELETE"])
def test_g4_rejects_lookup_policy_with_other_cmd(command: str) -> None:
    snapshot = _with_users_policies(replace(LOOKUP, command=command))

    assert ("G4", "users") in _codes(snapshot)


@pytest.mark.parametrize(
    ("using", "with_check"),
    [
        ("(org_id IS NOT NULL)", None),
        ("(true OR false)", None),
        ("false", None),
        (None, None),
        ("true", "true"),
        (_policy().using, None),  # the standard expression still needs no TO clause
    ],
)
def test_g4_rejects_lookup_policy_with_other_qual(
    using: str | None, with_check: str | None
) -> None:
    snapshot = _with_users_policies(replace(LOOKUP, using=using, with_check=with_check))

    assert ("G4", "users") in _codes(snapshot)


@pytest.mark.parametrize("table", ["workspaces", "memberships", "organizations"])
def test_g4_rejects_lookup_policy_with_other_table(table: str) -> None:
    key = "id" if table == "organizations" else "org_id"
    snapshot = _with_table(_good(), table, policies=(_policy(key), LOOKUP))

    assert ("G4", table) in _codes(snapshot)


def test_g4_rejects_lookup_policy_with_other_name() -> None:
    snapshot = _with_users_policies(replace(LOOKUP, name="lookup"))

    assert ("G4", "users") in _codes(snapshot)


def test_g4_rejects_a_standard_policy_with_a_to_clause() -> None:
    policy = replace(_policy(), roles=("ei_ai_app",))

    violations = find_violations(_with_table(_good(), "workspaces", policies=(policy,)))

    assert [str(v) for v in violations if v.code == "G4"] == [
        "G4 workspaces: policy tenant_isolation has a TO clause;"
        " only the reviewed sign-in lookup policy may"
    ]


def _with_signin_columns(*extra: ColumnPrivilege) -> CatalogSnapshot:
    return _with_table(_good(), "users", column_privileges=(*LOOKUP_COLUMNS, *extra))


def _g14(snapshot: CatalogSnapshot) -> list[str]:
    return [str(v) for v in find_violations(snapshot) if v.code == "G14"]


@pytest.mark.parametrize("column", ["display_name", "created_at"])
def test_g14_rejects_extra_column(column: str) -> None:
    snapshot = _with_signin_columns(ColumnPrivilege(column, SIGNIN, "SELECT"))

    assert _g14(snapshot) == [
        f"G14 users: sign-in role has SELECT on column {column};"
        " only SELECT on email, id, org_id of users is allowed"
    ]


@pytest.mark.parametrize("table", ["users", "workspaces", "user_credentials", "alembic_version"])
def test_g14_rejects_table_privilege(table: str) -> None:
    extra = _tenant_table("user_credentials")
    snapshot = replace(_good(), tables=(*_good().tables, extra))
    snapshot = _with_table(snapshot, table, privileges=(Privilege(SIGNIN, "SELECT"),))

    assert f"G14 {table}: sign-in role has the table privilege SELECT" in _g14(snapshot)


@pytest.mark.parametrize("privilege", ["INSERT", "UPDATE", "REFERENCES"])
def test_g14_rejects_write(privilege: str) -> None:
    snapshot = _with_signin_columns(ColumnPrivilege("email", SIGNIN, privilege))

    assert _g14(snapshot) == [
        f"G14 users: sign-in role has {privilege} on column email;"
        " only SELECT on email, id, org_id of users is allowed"
    ]


@pytest.mark.parametrize("privilege", ["INSERT", "UPDATE", "DELETE", "TRUNCATE"])
def test_g14_rejects_write_on_the_table(privilege: str) -> None:
    snapshot = _with_table(_good(), "users", privileges=(*DML, Privilege(SIGNIN, privilege)))

    assert _g14(snapshot) == [f"G14 users: sign-in role has the table privilege {privilege}"]


def test_g14_rejects_lookup_columns_on_another_table() -> None:
    snapshot = _with_table(
        _good(), "workspaces", column_privileges=(ColumnPrivilege("id", SIGNIN, "SELECT"),)
    )

    assert _g14(snapshot) == [
        "G14 workspaces: sign-in role has SELECT on column id;"
        " only SELECT on email, id, org_id of users is allowed"
    ]


def test_g14_rejects_a_grant_option() -> None:
    columns = (
        ColumnPrivilege("email", SIGNIN, "SELECT", grantable=True),
        *LOOKUP_COLUMNS[1:],
    )

    assert _g14(_with_table(_good(), "users", column_privileges=columns)) == [
        "G14 users: sign-in role may grant SELECT on column email"
    ]


def test_g14_rejects_a_missing_lookup_column() -> None:
    snapshot = _with_table(_good(), "users", column_privileges=LOOKUP_COLUMNS[:2])

    assert _g14(snapshot) == ["G14 users: sign-in role lacks SELECT on column org_id"]


def test_g14_counts_public_privileges_as_sign_in_privileges() -> None:
    # Every role holds what PUBLIC holds, NOINHERIT or not.
    snapshot = _with_signin_columns(ColumnPrivilege("display_name", "PUBLIC", "SELECT"))
    snapshot = _with_table(snapshot, "workspaces", privileges=(*DML, Privilege("PUBLIC", "SELECT")))

    assert _g14(snapshot) == [
        "G14 workspaces: sign-in role has the table privilege SELECT",
        "G14 users: sign-in role has SELECT on column display_name;"
        " only SELECT on email, id, org_id of users is allowed",
    ]


def test_g14_ignores_column_privileges_of_other_roles() -> None:
    snapshot = _with_signin_columns(ColumnPrivilege("display_name", "ei_ai_app", "SELECT"))

    assert _g14(snapshot) == []


def test_g5_the_canonical_policy_may_omit_with_check() -> None:
    policy = PolicyInfo("tenant_isolation", "ALL", _policy().using, None)

    assert _codes(_with_table(_good(), "workspaces", policies=(policy,))) == []


def test_g5_a_canonical_policy_for_select_only_does_not_protect_writes() -> None:
    policy = PolicyInfo("select_only", "SELECT", _policy().using, None)

    assert ("G5", "workspaces") in _codes(_with_table(_good(), "workspaces", policies=(policy,)))


def test_g5_policy_not_on_the_tenant_key() -> None:
    policy = _policy(key="id")  # compares id, not org_id

    assert ("G5", "workspaces") in _codes(_with_table(_good(), "workspaces", policies=(policy,)))


def test_g5_organizations_must_be_keyed_by_id() -> None:
    policy = _policy(key="org_id")

    assert ("G5", "organizations") in _codes(
        _with_table(_good(), "organizations", policies=(policy,))
    )


def test_g6_app_role_must_not_own_a_table() -> None:
    assert ("G6", "workspaces") in _codes(_with_table(_good(), "workspaces", owner="ei_ai_app"))


def test_g6_superuser_owner_is_not_the_migration_role() -> None:
    assert ("G6", "workspaces") in _codes(_with_table(_good(), "workspaces", owner="postgres"))


def test_g7_truncate_grant() -> None:
    privileges = (*DML, Privilege("ei_ai_app", "TRUNCATE"))

    assert _codes(_with_table(_good(), "workspaces", privileges=privileges)) == [
        ("G7", "workspaces")
    ]


@pytest.mark.parametrize("privilege", ["REFERENCES", "TRIGGER"])
def test_g7_other_non_dml_grants(privilege: str) -> None:
    privileges = (*DML, Privilege("ei_ai_app", privilege))

    assert ("G7", "workspaces") in _codes(_with_table(_good(), "workspaces", privileges=privileges))


def test_g7_public_grant_counts_as_an_application_grant() -> None:
    privileges = (*DML, Privilege("PUBLIC", "TRUNCATE"))

    assert ("G7", "workspaces") in _codes(_with_table(_good(), "workspaces", privileges=privileges))


def test_g8_grant_on_a_partition() -> None:
    partition = _tenant_table("chunks_p1", kind="partition")

    assert ("G8", "chunks_p1") in _codes(replace(_good(), tables=(*_good().tables, partition)))


def test_g8_a_partition_without_grants_is_fine() -> None:
    partition = _tenant_table("chunks_p1", kind="partition", privileges=())

    assert _codes(replace(_good(), tables=(*_good().tables, partition))) == []


def test_g8_privilege_on_alembic_version() -> None:
    codes = _codes(
        _with_table(_good(), "alembic_version", privileges=(Privilege("ei_ai_app", "SELECT"),))
    )

    assert codes == [("G8", "alembic_version")]


def test_g9_view_without_security_invoker() -> None:
    view = _tenant_table("v_workspaces", kind="view", security_invoker=False)

    assert ("G9", "v_workspaces") in _codes(replace(_good(), tables=(*_good().tables, view)))


def test_g9_security_invoker_view_is_fine() -> None:
    view = _tenant_table("v_workspaces", kind="view", security_invoker=True)

    assert _codes(replace(_good(), tables=(*_good().tables, view))) == []


def test_g9_materialised_view_with_app_privilege() -> None:
    view = _tenant_table("mv_stats", kind="matview")

    assert ("G9", "mv_stats") in _codes(replace(_good(), tables=(*_good().tables, view)))


def test_g10_security_definer_function() -> None:
    function = FunctionInfo("provision_org", "ei_ai_migrator", True)

    codes = _codes(replace(_good(), functions=(function,)))

    assert codes == [("G10", "provision_org")]


def test_g10_function_owned_by_another_role() -> None:
    function = FunctionInfo("helper", "postgres", False)

    assert _codes(replace(_good(), functions=(function,))) == [("G10", "helper")]


def test_g11_foreign_key_between_tenant_tables_without_org_id() -> None:
    fk = ForeignKeyInfo("plain_fk", ("workspace_id",), "workspaces", ("id",))

    codes = _codes(_with_table(_good(), "workspace_memberships", foreign_keys=(fk,)))

    assert codes == [("G11", "workspace_memberships")]


def test_g11_columns_are_paired_position_by_position() -> None:
    # org_id and id are both present on both sides, but crossed: org_id -> id and id -> org_id.
    fk = ForeignKeyInfo("crossed_fk", ("org_id", "workspace_id"), "workspaces", ("id", "org_id"))

    assert ("G11", "workspace_memberships") in _codes(
        _with_table(_good(), "workspace_memberships", foreign_keys=(fk,))
    )


def test_g11_users_are_referenced_with_the_organization_too() -> None:
    plain = ForeignKeyInfo("user_fk", ("user_id",), "users", ("id",))

    assert ("G11", "memberships") in _codes(
        _with_table(_good(), "memberships", foreign_keys=(plain,))
    )


def test_g11_reference_to_organizations_is_fine() -> None:
    fk = ForeignKeyInfo("org_fk", ("org_id",), "organizations", ("id",))

    assert _codes(_with_table(_good(), "memberships", foreign_keys=(fk,))) == []


def test_violations_name_the_rule_and_the_object_only() -> None:
    violation = Violation("G2", "workspaces", "row-level security is not forced")

    assert str(violation) == "G2 workspaces: row-level security is not forced"
