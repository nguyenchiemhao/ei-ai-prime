"""Documents and chunks (EA-33): uploaded files of a folder and the text chunks made from them.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22

``documents`` belong to one folder of one collection. A collection delete removes its folders and
documents in one statement; the folder foreign key has no cascade, so a folder that still holds
documents cannot be deleted on its own. The stored status is ``queued``, ``ready``, ``failed`` or
``not_supported``; a reason is present exactly for the last two. ``extracted_text`` is the
normalised full text and the base of every chunk offset. Deleting the uploader clears
``uploaded_by`` and keeps the document. ``file_id`` names the encrypted original that EA-20's
``OrgFileStore`` made (``<FILE_STORAGE_ROOT>/<org_id>/<file_id>.bin``); it is unique per
Organization and never part of an API response.

``document_chunks`` hold the text pieces of a ready document, in order, with their page (PDF) or
heading path and their offsets into ``documents.extracted_text``. Deleting a document removes them.

``audit_events.target_type`` also accepts ``document``. A downgrade fails while such an event
exists: audit events are never deleted.
"""

from collections.abc import Sequence

from alembic import op

from ei_ai.db.migrations.rls import enable_tenant_rls, grant_dml

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _target_type_check(values: Sequence[str]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return (
        "ALTER TABLE audit_events ADD CONSTRAINT audit_events_target_type_check"
        f" CHECK (target_type IN ({listed}))"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE documents (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            collection_id uuid NOT NULL,
            folder_id uuid NOT NULL,
            name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 255),
            format text NOT NULL CHECK (format IN ('pdf', 'docx', 'md', 'txt')),
            size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 52428800),
            status text NOT NULL
                CHECK (status IN ('queued', 'ready', 'failed', 'not_supported')),
            reason text CHECK (reason IN (
                'scanned_pdf', 'corrupt_file', 'password_protected', 'no_text',
                'unreadable_encoding', 'file_too_complex', 'processing_error'
            )),
            page_count integer CHECK (page_count >= 0),
            chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
            extracted_text text,
            uploaded_by uuid,
            file_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            processed_at timestamptz,
            UNIQUE (org_id, id),
            UNIQUE (org_id, file_id),
            FOREIGN KEY (org_id, collection_id) REFERENCES collections (org_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (org_id, collection_id, folder_id)
                REFERENCES folders (org_id, collection_id, id),
            FOREIGN KEY (org_id, uploaded_by) REFERENCES users (org_id, id)
                ON DELETE SET NULL (uploaded_by),
            CHECK ((reason IS NOT NULL) = (status IN ('failed', 'not_supported')))
        )
        """
    )
    op.execute(
        "CREATE INDEX documents_folder_idx"
        " ON documents (org_id, collection_id, folder_id, created_at DESC)"
    )
    enable_tenant_rls("documents")
    grant_dml("documents")

    op.execute(
        """
        CREATE TABLE document_chunks (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            org_id uuid NOT NULL REFERENCES organizations (id),
            document_id uuid NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            text text NOT NULL,
            page integer,
            heading_path text[] NOT NULL DEFAULT '{}',
            char_start integer NOT NULL CHECK (char_start >= 0),
            char_end integer NOT NULL,
            token_estimate integer NOT NULL CHECK (token_estimate > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (org_id, id),
            UNIQUE (org_id, document_id, ordinal),
            FOREIGN KEY (org_id, document_id) REFERENCES documents (org_id, id)
                ON DELETE CASCADE,
            CHECK (char_end > char_start)
        )
        """
    )
    enable_tenant_rls("document_chunks")
    grant_dml("document_chunks")

    op.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_target_type_check")
    op.execute(
        _target_type_check(
            ("organization", "workspace", "user", "model", "collection", "folder", "document")
        )
    )


def downgrade() -> None:
    # Adding the old check validates every row, whatever the row policy, so the downgrade stops
    # while a document audit event exists.
    op.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_target_type_check")
    op.execute(
        _target_type_check(("organization", "workspace", "user", "model", "collection", "folder"))
    )
    op.execute("DROP TABLE document_chunks")
    op.execute("DROP TABLE documents")
