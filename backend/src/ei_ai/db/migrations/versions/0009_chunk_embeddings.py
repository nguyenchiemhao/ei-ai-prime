"""Per-Organization vector namespace (EA-20): the partitioned table of chunk embeddings.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22

``chunk_embeddings`` is partitioned by LIST (org_id): each Organization gets its own partition,
``chunk_embeddings_<org id hex>``, created by ``ei-ai db vector-partition --org ORG_ID`` (owner
role). The partitioned HNSW index on the parent gives every partition its own HNSW graph. There
is no DEFAULT partition: a vector of an Organization without a partition is rejected, and its
queries return nothing. Row-level security and the DML grants sit on the parent; the application
role gets nothing on any partition. KB-04 adds the chunk and document columns.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chunk_embeddings (
            org_id uuid NOT NULL REFERENCES organizations (id),
            id uuid NOT NULL DEFAULT uuid_generate_v7(),
            embedding vector(1024) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, id)
        ) PARTITION BY LIST (org_id)
        """
    )
    op.execute(
        "CREATE INDEX chunk_embeddings_embedding_hnsw ON chunk_embeddings"
        " USING hnsw (embedding vector_cosine_ops)"
    )
    enable_tenant_rls("chunk_embeddings")
    grant_dml("chunk_embeddings")


def downgrade() -> None:
    # Drops every Organization's partition with the parent.
    op.execute("DROP TABLE chunk_embeddings")
