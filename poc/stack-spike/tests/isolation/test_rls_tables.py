"""AC3: with tenant context org A, regular tables return 0 rows of org B (database layer, D46)."""

import uuid

import psycopg
import pytest

from stack_spike.tenant import tenant_transaction
from stack_spike.vectors import to_vector_literal

pytestmark = pytest.mark.db


def test_reads_only_own_org_documents_with_tenant_context(app_conn, orgs):
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        own = conn.execute("SELECT id FROM documents WHERE org_id = %s", (orgs.org_a,))
        own_ids = {row[0] for row in own.fetchall()}
        other = conn.execute("SELECT count(*) FROM documents WHERE org_id = %s", (orgs.org_b,))
        other_count = other.fetchone()

    assert own_ids == {orgs.doc_a1, orgs.doc_a2}
    assert other_count == (0,)


def test_query_without_app_level_org_filter_still_returns_only_own_rows(app_conn, orgs):
    # Simulates a developer who forgot the WHERE org_id clause: the database layer still holds.
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        rows = conn.execute("SELECT id, org_id FROM documents").fetchall()

    assert {row[0] for row in rows} == {orgs.doc_a1, orgs.doc_a2}
    assert {row[1] for row in rows} == {orgs.org_a}


def test_returns_zero_rows_without_tenant_context(app_conn, orgs):
    for table in ("documents", "organizations", "chunk_embeddings"):
        assert app_conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def test_rejects_insert_of_row_for_other_org(app_conn, orgs):
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as excinfo:
        with tenant_transaction(app_conn, orgs.org_a) as conn:
            conn.execute(
                "INSERT INTO documents (id, org_id, title) VALUES (%s, %s, 'forged')",
                (uuid.uuid4(), orgs.org_b),
            )

    assert excinfo.value.sqlstate == "42501"


def test_update_of_other_org_row_affects_zero_rows(app_conn, admin_conn, orgs):
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        sql = "UPDATE documents SET title = 'hijacked' WHERE id = %s"
        cursor = conn.execute(sql, (orgs.doc_b1,))

    assert cursor.rowcount == 0
    title = admin_conn.execute("SELECT title FROM documents WHERE id = %s", (orgs.doc_b1,))
    assert title.fetchone() == ("B1",)


def test_delete_of_other_org_row_affects_zero_rows(app_conn, admin_conn, orgs):
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        cursor = conn.execute("DELETE FROM documents WHERE id = %s", (orgs.doc_b1,))

    assert cursor.rowcount == 0
    sql = "SELECT count(*) FROM documents WHERE id = %s"
    assert admin_conn.execute(sql, (orgs.doc_b1,)).fetchone() == (1,)


def test_rejects_cross_org_reference_via_composite_foreign_key(app_conn, orgs):
    # Referential-integrity checks bypass RLS, so only the composite FK (org_id, document_id)
    # stops a chunk of org A from pointing at a document of org B.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with tenant_transaction(app_conn, orgs.org_a) as conn:
            conn.execute(
                "INSERT INTO chunk_embeddings (org_id, id, document_id, content, embedding)"
                " VALUES (%s, %s, %s, 'cross-org', %s::vector)",
                (orgs.org_a, uuid.uuid4(), orgs.doc_b1, to_vector_literal(orgs.query)),
            )


def test_organizations_table_shows_only_current_org(app_conn, orgs):
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        rows = conn.execute("SELECT id FROM organizations").fetchall()

    assert rows == [(orgs.org_a,)]


def test_app_role_is_not_superuser_and_cannot_bypass_rls(app_conn):
    row = app_conn.execute(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()

    assert row == (False, False)
