"""AC3: with tenant context org A, vector queries return 0 rows of org B, even when B is nearest."""

import uuid
from unittest.mock import Mock

import psycopg
import pytest

from stack_spike.search import MAX_K, search_chunks
from stack_spike.tenant import tenant_transaction
from stack_spike.vectors import to_vector_literal

pytestmark = pytest.mark.db

RAW_NEAREST_SQL = (
    "SELECT org_id, id FROM chunk_embeddings ORDER BY embedding <=> %s::vector LIMIT 10"
)


def _partition_name(org_id: uuid.UUID) -> str:
    return "chunk_embeddings_" + str(org_id).replace("-", "_")


def test_vector_search_with_context_a_never_returns_org_b_vectors_even_when_b_is_nearest(
    app_conn, orgs
):
    hits = search_chunks(app_conn, orgs.org_a, orgs.query, k=10)

    assert hits, "org A has chunks, so the result must not be empty"
    assert {hit.org_id for hit in hits} == {orgs.org_a}
    assert orgs.chunk_b1 not in {hit.id for hit in hits}


def test_raw_similarity_query_without_org_filter_returns_only_own_vectors(app_conn, orgs):
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        rows = conn.execute(RAW_NEAREST_SQL, (to_vector_literal(orgs.query),)).fetchall()

    assert {row[1] for row in rows} == {orgs.chunk_a1, orgs.chunk_a2}
    assert {row[0] for row in rows} == {orgs.org_a}


def test_vector_search_without_tenant_context_returns_nothing(app_conn, orgs):
    rows = app_conn.execute(RAW_NEAREST_SQL, (to_vector_literal(orgs.query),)).fetchall()

    assert rows == []


def test_rejects_vector_insert_for_other_org(app_conn, orgs):
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as excinfo:
        with tenant_transaction(app_conn, orgs.org_a) as conn:
            conn.execute(
                "INSERT INTO chunk_embeddings (org_id, id, document_id, content, embedding)"
                " VALUES (%s, %s, %s, 'forged', %s::vector)",
                (orgs.org_b, uuid.uuid4(), orgs.doc_b1, to_vector_literal(orgs.query)),
            )

    assert excinfo.value.sqlstate == "42501"


def test_app_role_cannot_read_org_partition_directly(app_conn, orgs):
    # A direct read of a partition would skip the parent's policy; it is denied by missing grants.
    for org_id in (orgs.org_a, orgs.org_b):
        partition = _partition_name(org_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with tenant_transaction(app_conn, org_id) as conn:
                conn.execute(f'SELECT count(*) FROM "{partition}"')


def test_each_org_has_its_own_vector_partition_with_hnsw_index(admin_conn, orgs):
    for org_id in (orgs.org_a, orgs.org_b):
        partition = _partition_name(org_id)
        is_partition = admin_conn.execute(
            "SELECT count(*) FROM pg_inherits"
            " WHERE inhparent = 'chunk_embeddings'::regclass AND inhrelid = %s::regclass",
            (f'"{partition}"',),
        ).fetchone()
        index_def = admin_conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", (partition,)
        ).fetchall()

        assert is_partition == (1,)
        assert any("USING hnsw" in row[0] for row in index_def)


@pytest.mark.parametrize("k", [0, -1, MAX_K + 1])
def test_rejects_k_outside_supported_range(k):
    # Beyond ef_search an HNSW scan silently returns fewer rows; fail loudly instead.
    with pytest.raises(ValueError):
        search_chunks(Mock(spec=[]), uuid.uuid4(), [1.0] + [0.0] * 7, k=k)
