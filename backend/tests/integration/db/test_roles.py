"""AC5: the application role cannot bypass RLS; only the migration role has elevated rights."""

import psycopg
import pytest

from ei_ai.db.catalog import read_catalog
from support.tenants import DELETE_ORDER, TwoOrgs

pytestmark = pytest.mark.integration

APP = "ei_ai_app"
MIGRATOR = "ei_ai_migrator"


def test_app_role_has_no_elevated_attributes(app_conn: psycopg.Connection) -> None:
    row = app_conn.execute(
        "SELECT current_user, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()

    assert row == (APP, False, False, False, False)


def test_app_role_owns_no_object(app_conn: psycopg.Connection) -> None:
    # pg_shdepend 'o' rows are owner dependencies of every object in the cluster.
    owned = app_conn.execute(
        "SELECT count(*) FROM pg_shdepend"
        " WHERE deptype = 'o' AND refclassid = 'pg_authid'::regclass"
        " AND refobjid = (SELECT oid FROM pg_roles WHERE rolname = %s)",
        (APP,),
    ).fetchone()

    assert owned == (0,)


def test_app_role_cannot_create_tables(app_tx_conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_tx_conn.execute("CREATE TABLE app_probe (id int)")


@pytest.mark.parametrize("table", DELETE_ORDER)
@pytest.mark.parametrize("clause", ["DISABLE ROW LEVEL SECURITY", "NO FORCE ROW LEVEL SECURITY"])
def test_app_role_cannot_disable_rls(
    app_tx_conn: psycopg.Connection, table: str, clause: str
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as error:
        app_tx_conn.execute(f"ALTER TABLE {table} {clause}")

    assert "must be owner" in str(error.value)


def test_app_role_is_not_member_of_any_role(app_conn: psycopg.Connection) -> None:
    memberships = app_conn.execute(
        "SELECT count(*) FROM pg_auth_members WHERE member = "
        "(SELECT oid FROM pg_roles WHERE rolname = %s)",
        (APP,),
    ).fetchone()
    migrator = app_conn.execute("SELECT pg_has_role(%s, %s, 'MEMBER')", (APP, MIGRATOR)).fetchone()

    assert memberships == (0,)
    assert migrator == (False,)


def test_app_role_privileges_are_dml_only(app_conn: psycopg.Connection) -> None:
    granted = {
        (table, privilege)
        for table in DELETE_ORDER
        for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER")
        if app_conn.execute(
            "SELECT has_table_privilege(%s, %s, %s)", (APP, table, privilege)
        ).fetchone()
        == (True,)
    }

    assert granted == set()


def test_app_role_has_no_privilege_on_migration_bookkeeping(
    app_conn: psycopg.Connection,
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("SELECT * FROM alembic_version")


def test_migrator_owns_every_schema_object(migrator_conn: psycopg.Connection) -> None:
    snapshot = read_catalog(migrator_conn)
    other_owners = migrator_conn.execute(
        "SELECT c.relname, pg_get_userbyid(c.relowner) FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public'"
        " AND c.relowner <> (SELECT oid FROM pg_roles WHERE rolname = %s)"
        " AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass"
        "                 AND d.objid = c.oid AND d.deptype = 'e')",
        (MIGRATOR,),
    ).fetchall()

    assert other_owners == []
    assert {t.owner for t in snapshot.tables} == {MIGRATOR}
    assert {f.owner for f in snapshot.functions} == {MIGRATOR}


def test_migrator_is_not_superuser_and_cannot_bypass_rls(
    migrator_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    row = migrator_conn.execute(
        "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles"
        " WHERE rolname = current_user"
    ).fetchone()
    visible = migrator_conn.execute("SELECT count(*) FROM organizations").fetchone()

    assert row == (False, False, False, False)
    # Rows of two Organizations exist (fixture), yet the owner sees none without a tenant context:
    # the tables FORCE row-level security.
    assert visible == (0,)


def test_only_bootstrap_superuser_has_superuser_or_bypassrls(
    app_conn: psycopg.Connection,
) -> None:
    privileged = app_conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolsuper OR rolbypassrls ORDER BY rolname"
    ).fetchall()
    bootstrap = app_conn.execute("SELECT rolname FROM pg_roles WHERE oid = 10").fetchall()

    assert privileged == bootstrap
