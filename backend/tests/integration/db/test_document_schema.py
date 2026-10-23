"""Migration 0010 (EA-33): ``documents``, ``document_chunks`` and the ``document`` audit target.

Each case runs as the application role in a tenant transaction; a failing statement rolls back.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration


async def _insert_collection(engine: AsyncEngine, rows: OrgRows) -> uuid.UUID:
    """Insert a collection in the fixture Workspace of ``rows``; returns its id."""
    collection_id = uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "INSERT INTO collections (id, org_id, workspace_id, name, access_level)"
                " VALUES (:id, :org, :ws, :name, 'authenticated')"
            ),
            {
                "id": collection_id,
                "org": rows.org_id,
                "ws": rows.workspace_id,
                "name": f"Handbook {collection_id.hex[:8]}",
            },
        )
    return collection_id


async def _insert_folder(engine: AsyncEngine, rows: OrgRows, collection_id: uuid.UUID) -> uuid.UUID:
    """Insert a top-level folder under ``collection_id``; returns its id."""
    folder_id = uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "INSERT INTO folders (id, org_id, collection_id, name, depth)"
                " VALUES (:id, :org, :collection, 'Policies', 1)"
            ),
            {"id": folder_id, "org": rows.org_id, "collection": collection_id},
        )
    return folder_id


async def _insert_document(
    engine: AsyncEngine,
    rows: OrgRows,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    **overrides: Any,
) -> uuid.UUID:
    """Insert a document in ``folder_id``; returns its id. Defaults to a ready text file."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "org": rows.org_id,
        "collection": collection_id,
        "folder": folder_id,
        "name": "Overtime Policy 2026.txt",
        "format": "txt",
        "size": 1024,
        "status": "ready",
        "reason": None,
        "user": None,
        "file": uuid.uuid4(),
    }
    values.update(overrides)
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
                " size_bytes, status, reason, uploaded_by, file_id)"
                " VALUES (:id, :org, :collection, :folder, :name, :format, :size, :status,"
                " :reason, :user, :file)"
            ),
            values,
        )
    document_id: uuid.UUID = values["id"]
    return document_id


async def _insert_chunk(
    engine: AsyncEngine, rows: OrgRows, document_id: uuid.UUID, ordinal: int = 0, **overrides: Any
) -> uuid.UUID:
    """Insert one chunk of ``document_id``; returns its id."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "org": rows.org_id,
        "document": document_id,
        "ordinal": ordinal,
        "start": 0,
        "end": 10,
        "tokens": 3,
    }
    values.update(overrides)
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "INSERT INTO document_chunks (id, org_id, document_id, ordinal, text,"
                " char_start, char_end, token_estimate)"
                " VALUES (:id, :org, :document, :ordinal, 'chunk text', :start, :end, :tokens)"
            ),
            values,
        )
    chunk_id: uuid.UUID = values["id"]
    return chunk_id


async def _count(engine: AsyncEngine, org: uuid.UUID, table: str, row_id: uuid.UUID) -> int:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        sql = f"SELECT count(*) FROM {table} WHERE org_id = :org AND id = :id"
        total: int = (await conn.execute(text(sql), {"org": org, "id": row_id})).scalar_one()
        return total


async def _delete(engine: AsyncEngine, org: uuid.UUID, table: str, row_id: uuid.UUID) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        await conn.execute(
            text(f"DELETE FROM {table} WHERE org_id = :org AND id = :id"),
            {"org": org, "id": row_id},
        )


@pytest.mark.parametrize(
    ("status", "reason", "accepted"),
    [
        ("queued", None, True),
        ("ready", None, True),
        ("failed", "corrupt_file", True),
        ("not_supported", "scanned_pdf", True),
        ("queued", "corrupt_file", False),
        ("ready", "corrupt_file", False),
        ("failed", None, False),
        ("not_supported", None, False),
        ("failed", "unknown_reason", False),
        ("processing", None, False),
    ],
)
async def test_reason_required_iff_failed_or_not_supported(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    status: str,
    reason: str | None,
    accepted: bool,
) -> None:
    a = two_orgs.a

    insert = _insert_document(
        app_engine, a, a.collection_id, a.folder_id, status=status, reason=reason
    )

    if accepted:
        assert await _count(app_engine, a.org_id, "documents", await insert) == 1
    else:
        with pytest.raises(IntegrityError):
            await insert


@pytest.mark.parametrize(
    ("size", "accepted"),
    [(0, False), (1, True), (52_428_800, True), (52_428_801, False)],
)
async def test_size_above_limit_rejected(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, size: int, accepted: bool
) -> None:
    a = two_orgs.a

    insert = _insert_document(app_engine, a, a.collection_id, a.folder_id, size=size)

    if accepted:
        assert await _count(app_engine, a.org_id, "documents", await insert) == 1
    else:
        with pytest.raises(IntegrityError):
            await insert


@pytest.mark.parametrize("name", ["", "x" * 256])
async def test_document_name_length_is_checked(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, name: str
) -> None:
    a = two_orgs.a

    with pytest.raises(IntegrityError):
        await _insert_document(app_engine, a, a.collection_id, a.folder_id, name=name)


async def test_unknown_format_rejected(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a

    with pytest.raises(IntegrityError):
        await _insert_document(app_engine, a, a.collection_id, a.folder_id, format="exe")


async def test_file_id_required_and_unique_per_org(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    shared = uuid.uuid4()

    with pytest.raises(IntegrityError):
        await _insert_document(app_engine, a, a.collection_id, a.folder_id, file=None)
    first = await _insert_document(app_engine, a, a.collection_id, a.folder_id, file=shared)
    with pytest.raises(IntegrityError):
        await _insert_document(app_engine, a, a.collection_id, a.folder_id, file=shared)
    other = await _insert_document(app_engine, b, b.collection_id, b.folder_id, file=shared)

    assert await _count(app_engine, a.org_id, "documents", first) == 1
    assert await _count(app_engine, b.org_id, "documents", other) == 1


async def test_folder_must_belong_to_the_collection(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    other_collection = await _insert_collection(app_engine, a)

    with pytest.raises(IntegrityError):
        await _insert_document(app_engine, a, other_collection, a.folder_id)


async def test_folder_with_documents_cannot_be_deleted_by_fk(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    collection_id = await _insert_collection(app_engine, a)
    folder_id = await _insert_folder(app_engine, a, collection_id)
    document_id = await _insert_document(app_engine, a, collection_id, folder_id)

    with pytest.raises(IntegrityError):
        await _delete(app_engine, a.org_id, "folders", folder_id)

    assert await _count(app_engine, a.org_id, "folders", folder_id) == 1
    assert await _count(app_engine, a.org_id, "documents", document_id) == 1


async def test_collection_delete_cascades_documents_and_chunks(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    collection_id = await _insert_collection(app_engine, a)
    folder_id = await _insert_folder(app_engine, a, collection_id)
    document_id = await _insert_document(app_engine, a, collection_id, folder_id)
    chunk_id = await _insert_chunk(app_engine, a, document_id)

    await _delete(app_engine, a.org_id, "collections", collection_id)

    assert await _count(app_engine, a.org_id, "folders", folder_id) == 0
    assert await _count(app_engine, a.org_id, "documents", document_id) == 0
    assert await _count(app_engine, a.org_id, "document_chunks", chunk_id) == 0


async def test_document_delete_cascades_chunks(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    document_id = await _insert_document(app_engine, a, a.collection_id, a.folder_id)
    chunk_id = await _insert_chunk(app_engine, a, document_id)

    await _delete(app_engine, a.org_id, "documents", document_id)

    assert await _count(app_engine, a.org_id, "document_chunks", chunk_id) == 0


async def test_chunk_ordinal_unique_per_document(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    document_id = await _insert_document(app_engine, a, a.collection_id, a.folder_id)
    other_document = await _insert_document(app_engine, a, a.collection_id, a.folder_id)
    await _insert_chunk(app_engine, a, document_id, ordinal=0)

    with pytest.raises(IntegrityError):
        await _insert_chunk(app_engine, a, document_id, ordinal=0)

    await _insert_chunk(app_engine, a, document_id, ordinal=1)
    await _insert_chunk(app_engine, a, other_document, ordinal=0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"ordinal": -1},
        {"start": -1},
        {"start": 5, "end": 5},
        {"start": 5, "end": 4},
        {"tokens": 0},
    ],
)
async def test_chunk_bounds_are_checked(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, overrides: dict[str, int]
) -> None:
    a = two_orgs.a
    document_id = await _insert_document(app_engine, a, a.collection_id, a.folder_id)

    with pytest.raises(IntegrityError):
        await _insert_chunk(app_engine, a, document_id, **overrides)


async def test_chunk_cannot_point_at_a_document_of_another_organization(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    other_document = two_orgs.b.document_id

    with pytest.raises(IntegrityError):
        await _insert_chunk(app_engine, two_orgs.a, other_document)


async def test_uploader_delete_sets_null(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    uploader = uuid.uuid4()
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text(
                "INSERT INTO users (id, org_id, email, display_name)"
                " VALUES (:id, :org, :email, 'Uploader')"
            ),
            {"id": uploader, "org": a.org_id, "email": f"{uploader}@example.invalid"},
        )
    document_id = await _insert_document(app_engine, a, a.collection_id, a.folder_id, user=uploader)

    await _delete(app_engine, a.org_id, "users", uploader)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        row = (
            await conn.execute(
                text(
                    "SELECT uploaded_by, org_id, collection_id FROM documents"
                    " WHERE org_id = :org AND id = :id"
                ),
                {"org": a.org_id, "id": document_id},
            )
        ).one()
    assert row.uploaded_by is None
    assert row.org_id == a.org_id
    assert row.collection_id == a.collection_id


async def test_audit_accepts_document_target(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text(
                "INSERT INTO audit_events (org_id, actor, action, target_type, target_id,"
                " new_value) VALUES (:org, 'platform-operator', 'document.uploaded',"
                " 'document', :id, 'pdf')"
            ),
            {"org": a.org_id, "id": uuid.uuid4()},
        )
