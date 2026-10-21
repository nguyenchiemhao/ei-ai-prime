"""AC1 on the live database: the guard accepts head and rejects each kind of unsafe new table.

Negative cases create the table inside a transaction on the owner connection and roll it back.
"""

from collections.abc import Iterator

import psycopg
import pytest

from ei_ai.db.catalog import read_catalog
from ei_ai.db.migrations.rls import tenant_rls_statements
from ei_ai.db.schema_guard import find_violations

pytestmark = pytest.mark.integration


@pytest.fixture
def tx_conn(migrator_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrator_url) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


def _found(conn: psycopg.Connection) -> list[tuple[str, str]]:
    return [
        (v.code, v.subject) for v in find_violations(read_catalog(conn)) if "probe" in v.subject
    ]


def test_head_schema_has_no_tenant_violations(migrator_conn: psycopg.Connection) -> None:
    snapshot = read_catalog(migrator_conn)

    assert find_violations(snapshot) == []
    assert {t.name for t in snapshot.tables} >= {
        "organizations",
        "workspaces",
        "users",
        "memberships",
        "workspace_memberships",
        "alembic_version",
    }


def test_guard_ignores_objects_that_belong_to_extensions(
    migrator_conn: psycopg.Connection,
) -> None:
    snapshot = read_catalog(migrator_conn)
    names = {t.name for t in snapshot.tables}
    functions = {f.name for f in snapshot.functions}

    assert not any(name.startswith("vector") for name in names | functions)
    # Our own functions only: the UUIDv7 default and the model_catalog pin trigger (0005).
    assert functions == {"uuid_generate_v7", "model_catalog_pin_immutable"}


def test_guard_reports_table_without_org_id(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("CREATE TABLE guard_probe (id uuid PRIMARY KEY)")

    assert ("G12", "guard_probe") in _found(tx_conn)


def test_guard_reports_table_with_nullable_org_id(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("CREATE TABLE guard_probe (id uuid PRIMARY KEY, org_id uuid)")
    for statement in tenant_rls_statements("guard_probe"):
        tx_conn.execute(statement)

    assert _found(tx_conn) == [("G1", "guard_probe")]


def test_guard_reports_table_without_policy(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("CREATE TABLE guard_probe (id uuid PRIMARY KEY, org_id uuid NOT NULL)")

    codes = [code for code, _ in _found(tx_conn)]

    assert "G3" in codes
    assert "G2" in codes


def test_guard_reports_table_without_force(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("CREATE TABLE guard_probe (id uuid PRIMARY KEY, org_id uuid NOT NULL)")
    for statement in tenant_rls_statements("guard_probe"):
        if "FORCE" not in statement:
            tx_conn.execute(statement)

    assert _found(tx_conn) == [("G2", "guard_probe")]


def test_guard_reports_policy_without_nullif(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("CREATE TABLE guard_probe (id uuid PRIMARY KEY, org_id uuid NOT NULL)")
    tx_conn.execute("ALTER TABLE guard_probe ENABLE ROW LEVEL SECURITY")
    tx_conn.execute("ALTER TABLE guard_probe FORCE ROW LEVEL SECURITY")
    tx_conn.execute(
        "CREATE POLICY tenant_isolation ON guard_probe"
        " USING (org_id = current_setting('app.current_org', true)::uuid)"
    )

    assert ("G4", "guard_probe") in _found(tx_conn)


def test_guard_reports_a_truncate_grant_to_the_app_role(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("CREATE TABLE guard_probe (id uuid PRIMARY KEY, org_id uuid NOT NULL)")
    for statement in tenant_rls_statements("guard_probe"):
        tx_conn.execute(statement)
    tx_conn.execute("GRANT SELECT, TRUNCATE ON guard_probe TO ei_ai_app")

    assert _found(tx_conn) == [("G7", "guard_probe")]


def _probe_table_with_standard_policy(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE guard_probe (id uuid PRIMARY KEY, org_id uuid NOT NULL)")
    for statement in tenant_rls_statements("guard_probe"):
        conn.execute(statement)
    assert _found(conn) == []  # the standard form is accepted before the mutation


_SETTING = "NULLIF(current_setting('app.current_org', true), '')::uuid"


def test_guard_reports_an_extra_permissive_policy_that_leaks_rows(
    tx_conn: psycopg.Connection,
) -> None:
    # Mutation M-D12: permissive policies are OR-ed, so any tenant would read every row.
    _probe_table_with_standard_policy(tx_conn)
    tx_conn.execute(f"CREATE POLICY leak ON guard_probe FOR SELECT USING ({_SETTING} IS NOT NULL)")

    assert ("G4", "guard_probe") in _found(tx_conn)


def test_guard_reports_a_key_comparison_or_ed_with_true(tx_conn: psycopg.Connection) -> None:
    # Mutation M-D13.
    _probe_table_with_standard_policy(tx_conn)
    tx_conn.execute("DROP POLICY tenant_isolation ON guard_probe")
    tx_conn.execute(
        f"CREATE POLICY tenant_isolation ON guard_probe USING (org_id = {_SETTING} OR true)"
    )

    assert ("G4", "guard_probe") in _found(tx_conn)


def test_guard_reports_a_key_comparison_or_ed_with_its_negation(
    tx_conn: psycopg.Connection,
) -> None:
    # Mutation M-D14.
    _probe_table_with_standard_policy(tx_conn)
    tx_conn.execute("DROP POLICY tenant_isolation ON guard_probe")
    tx_conn.execute(
        "CREATE POLICY tenant_isolation ON guard_probe"
        f" USING (org_id = {_SETTING} OR org_id <> {_SETTING})"
    )

    assert ("G4", "guard_probe") in _found(tx_conn)


def test_guard_reports_restrictive_policy_without_nullif(tx_conn: psycopg.Connection) -> None:
    _probe_table_with_standard_policy(tx_conn)
    tx_conn.execute(
        "CREATE POLICY probe_narrow ON guard_probe AS RESTRICTIVE"
        " USING (org_id = current_setting('app.current_org', true)::uuid)"
    )

    assert _found(tx_conn) == [("G13", "guard_probe")]


def test_guard_accepts_a_restrictive_policy_with_the_nullif_form(
    tx_conn: psycopg.Connection,
) -> None:
    _probe_table_with_standard_policy(tx_conn)
    tx_conn.execute(
        f"CREATE POLICY probe_narrow ON guard_probe AS RESTRICTIVE USING (org_id = {_SETTING})"
    )

    assert _found(tx_conn) == []


def _sign_in_findings(conn: psycopg.Connection) -> list[str]:
    return [str(v) for v in find_violations(read_catalog(conn)) if v.code in ("G4", "G14")]


def test_guard_reports_a_wider_grant_to_the_sign_in_role(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("GRANT UPDATE (display_name) ON users TO ei_ai_signin")
    tx_conn.execute("GRANT SELECT ON workspaces TO PUBLIC")

    assert _sign_in_findings(tx_conn) == [
        "G14 users: sign-in role has UPDATE on column display_name;"
        " only SELECT on email, id, org_id of users is allowed",
        "G14 workspaces: sign-in role has the table privilege SELECT",
    ]


def test_guard_reports_a_changed_sign_in_lookup_policy(tx_conn: psycopg.Connection) -> None:
    tx_conn.execute("ALTER POLICY sign_in_lookup ON users TO ei_ai_signin, ei_ai_app")

    assert _sign_in_findings(tx_conn) == [
        "G4 users: policy sign_in_lookup is not the standard tenant expression"
    ]


def test_guard_reports_a_tenant_foreign_key_that_crosses_the_columns(
    tx_conn: psycopg.Connection,
) -> None:
    _probe_table_with_standard_policy(tx_conn)
    tx_conn.execute("ALTER TABLE guard_probe ADD COLUMN ws uuid")
    tx_conn.execute(
        "ALTER TABLE guard_probe ADD FOREIGN KEY (org_id, ws) REFERENCES workspaces (id, org_id)"
    )

    assert ("G11", "guard_probe") in _found(tx_conn)
