import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest

from stack_spike.vectors import to_vector_literal

# The query vector and the chunks. B's chunk is identical to the query, so organization B owns the
# global nearest neighbour: any leak across organizations would show up at rank 1.
QUERY = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
FAR_1 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
FAR_2 = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]


@dataclass(frozen=True)
class SeededOrgs:
    org_a: uuid.UUID
    org_b: uuid.UUID
    doc_a1: uuid.UUID
    doc_a2: uuid.UUID
    doc_b1: uuid.UUID
    chunk_a1: uuid.UUID
    chunk_a2: uuid.UUID
    chunk_b1: uuid.UUID
    query: list[float]


@pytest.fixture(scope="session")
def admin_conn() -> Iterator[psycopg.Connection]:
    """Superuser connection: plays the migration/provisioning role and bypasses RLS."""
    with psycopg.connect(os.environ["POC_ADMIN_DSN"], autocommit=True) as conn:
        yield conn


@pytest.fixture
def app_conn() -> Iterator[psycopg.Connection]:
    """Connection as the application role `poc_app` (not owner, no BYPASSRLS).

    Autocommit, so no implicit transaction can carry a tenant context between statements.
    """
    with psycopg.connect(os.environ["POC_APP_DSN"], autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="session")
def orgs(admin_conn: psycopg.Connection) -> SeededOrgs:
    """Provision two fresh organizations (random ids) so re-runs on a live DB never collide."""
    seeded = SeededOrgs(
        org_a=uuid.uuid4(),
        org_b=uuid.uuid4(),
        doc_a1=uuid.uuid4(),
        doc_a2=uuid.uuid4(),
        doc_b1=uuid.uuid4(),
        chunk_a1=uuid.uuid4(),
        chunk_a2=uuid.uuid4(),
        chunk_b1=uuid.uuid4(),
        query=QUERY,
    )
    admin_conn.execute("SELECT provision_org(%s, 'Org A')", (seeded.org_a,))
    admin_conn.execute("SELECT provision_org(%s, 'Org B')", (seeded.org_b,))
    for doc_id, org_id, title in [
        (seeded.doc_a1, seeded.org_a, "A1"),
        (seeded.doc_a2, seeded.org_a, "A2"),
        (seeded.doc_b1, seeded.org_b, "B1"),
    ]:
        admin_conn.execute(
            "INSERT INTO documents (id, org_id, title) VALUES (%s, %s, %s)",
            (doc_id, org_id, title),
        )
    for chunk_id, org_id, doc_id, content, vector in [
        (seeded.chunk_a1, seeded.org_a, seeded.doc_a1, "A-chunk-1", FAR_1),
        (seeded.chunk_a2, seeded.org_a, seeded.doc_a2, "A-chunk-2", FAR_2),
        (seeded.chunk_b1, seeded.org_b, seeded.doc_b1, "B-chunk-1", QUERY),
    ]:
        admin_conn.execute(
            "INSERT INTO chunk_embeddings (org_id, id, document_id, content, embedding)"
            " VALUES (%s, %s, %s, %s, %s::vector)",
            (org_id, chunk_id, doc_id, content, to_vector_literal(vector)),
        )
    return seeded
