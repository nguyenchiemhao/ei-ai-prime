"""Vector metadata (EA-35): the chunk, its scope, its permissions and the embedding model.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23

Every vector now names its chunk and carries the document, workspace, collection and folder it came
from, the collection's access level and groups (so a query filters inside the vector search, not
afterwards) and the embedding model id and version. All columns are ``NOT NULL`` without a default
(``groups`` defaults to empty): the upgrade fails loudly if a vector row exists, and nothing deletes
data. Vectors can be rebuilt, and none exist outside tests. Deleting a chunk (so a document or a
collection) removes its vector through the foreign key. Downgrade drops the columns again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chunk_embeddings
            ADD COLUMN chunk_id uuid NOT NULL,
            ADD COLUMN document_id uuid NOT NULL,
            ADD COLUMN workspace_id uuid NOT NULL,
            ADD COLUMN collection_id uuid NOT NULL,
            ADD COLUMN folder_id uuid NOT NULL,
            ADD COLUMN access_level text NOT NULL,
            ADD COLUMN groups text[] NOT NULL DEFAULT '{}',
            ADD COLUMN model_id text NOT NULL,
            ADD COLUMN model_version text NOT NULL,
            ADD CONSTRAINT chunk_embeddings_access_level_check
                CHECK (access_level IN ('public', 'authenticated', 'restricted')),
            ADD CONSTRAINT chunk_embeddings_groups_check
                CHECK ((access_level = 'restricted') = (cardinality(groups) >= 1)),
            ADD CONSTRAINT chunk_embeddings_model_id_check
                CHECK (model_id ~ '^[a-z0-9][a-z0-9._-]{0,99}$'),
            ADD CONSTRAINT chunk_embeddings_model_version_check
                CHECK (model_version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'),
            ADD CONSTRAINT chunk_embeddings_chunk_fk
                FOREIGN KEY (org_id, chunk_id) REFERENCES document_chunks (org_id, id)
                ON DELETE CASCADE,
            ADD CONSTRAINT chunk_embeddings_chunk_key UNIQUE (org_id, chunk_id)
        """
    )
    op.execute(
        "CREATE INDEX chunk_embeddings_document_idx ON chunk_embeddings (org_id, document_id)"
    )
    op.execute(
        "CREATE INDEX chunk_embeddings_collection_idx ON chunk_embeddings (org_id, collection_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX chunk_embeddings_collection_idx")
    op.execute("DROP INDEX chunk_embeddings_document_idx")
    op.execute(
        """
        ALTER TABLE chunk_embeddings
            DROP CONSTRAINT chunk_embeddings_chunk_key,
            DROP CONSTRAINT chunk_embeddings_chunk_fk,
            DROP CONSTRAINT chunk_embeddings_model_version_check,
            DROP CONSTRAINT chunk_embeddings_model_id_check,
            DROP CONSTRAINT chunk_embeddings_groups_check,
            DROP CONSTRAINT chunk_embeddings_access_level_check,
            DROP COLUMN model_version,
            DROP COLUMN model_id,
            DROP COLUMN groups,
            DROP COLUMN access_level,
            DROP COLUMN folder_id,
            DROP COLUMN collection_id,
            DROP COLUMN workspace_id,
            DROP COLUMN document_id,
            DROP COLUMN chunk_id
        """
    )
