"""The document service called directly (no route), so a removed ``ensure`` cannot hide behind a
route dependency: permission, tenant scoping, check order, audit and quota."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.errors import KeyNotFound
from ei_ai.knowledge import documents, folders, service
from ei_ai.knowledge import documents as document_service
from ei_ai.knowledge.document_rows import DocumentRow
from ei_ai.knowledge.errors import (
    CollectionNotFound,
    DocumentNotFound,
    DocumentNotReady,
    EmptyFile,
    FolderNotFound,
    InvalidFileName,
    StorageQuotaExceeded,
    UnsupportedFormat,
)
from ei_ai.rbac.access import PermissionDenied
from ei_ai.storage.files import OrgFileStore
from support.rbac.orgs import RoleOrg
from support.sign_in import in_tenant

from .conftest import MakeOrg, add_document, document_file_id, file_store, run_as

pytestmark = pytest.mark.integration


async def _setup(engine: AsyncEngine, org: RoleOrg) -> tuple[uuid.UUID, uuid.UUID]:
    async def work(conn: Any, tenant: Any, access: Any) -> tuple[uuid.UUID, uuid.UUID]:
        collection = await service.create_collection(
            conn,
            tenant,
            access,
            name="Handbook",
            subtitle=None,
            access_level="authenticated",
            groups=[],
            local_only=False,
        )
        folder = await folders.create_folder(
            conn, tenant, access, collection.id, name="Policies", parent_id=None
        )
        return collection.id, folder.id

    return await run_as(engine, org, "ke", work)  # type: ignore[no-any-return]


async def _upload(
    engine: AsyncEngine,
    org: RoleOrg,
    storage: OrgFileStore,
    ids: tuple[uuid.UUID, uuid.UUID],
    name: str = "a.txt",
    data: bytes = b"text",
    actor: str = "ke",
) -> DocumentRow:
    async def work(conn: Any, tenant: Any, access: Any) -> DocumentRow:
        prepared = await documents.prepare_upload(conn, tenant, access, ids[0], ids[1], name)
        return await documents.store_document(
            conn, tenant, access, storage, ids[0], ids[1], prepared, data
        )

    return await run_as(engine, org, actor, work)  # type: ignore[no-any-return]


async def test_viewer_is_denied_by_every_service_function(
    app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path
) -> None:
    org = await make_org()
    ids = await _setup(app_engine, org)
    document_id = await add_document(app_engine, org, ids[0], ids[1], "ready")
    storage = file_store(tmp_path)

    async def prepare(conn: Any, tenant: Any, access: Any) -> object:
        return await documents.prepare_upload(conn, tenant, access, ids[0], ids[1], "a.txt")

    async def store(conn: Any, tenant: Any, access: Any) -> object:
        prepared = documents.PreparedUpload(name="a.txt", format="txt")
        return await documents.store_document(
            conn, tenant, access, storage, ids[0], ids[1], prepared, b"text"
        )

    async def listing(conn: Any, tenant: Any, access: Any) -> object:
        return await documents.list_documents(conn, tenant, access, ids[0], None)

    async def text(conn: Any, tenant: Any, access: Any) -> object:
        return await documents.get_document_text(conn, tenant, access, ids[0], document_id)

    async def chunks(conn: Any, tenant: Any, access: Any) -> object:
        return await documents.get_document_chunks(conn, tenant, access, ids[0], document_id)

    async def remove(conn: Any, tenant: Any, access: Any) -> None:
        await documents.remove_document(conn, tenant, access, ids[0], document_id)

    for work in (prepare, store, listing, text, chunks, remove):
        with pytest.raises(PermissionDenied):
            await run_as(app_engine, org, "viewer", work)
    rows = await in_tenant(
        app_engine, org.org_id, "SELECT count(*) FROM documents WHERE org_id = :org"
    )
    assert rows[0][0] == 1


async def test_prepare_checks_ids_then_name_then_format(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    collection_id, folder_id = await _setup(app_engine, org)

    async def prepare(collection: uuid.UUID, folder: uuid.UUID, name: str | None) -> object:
        async def work(conn: Any, tenant: Any, access: Any) -> object:
            return await documents.prepare_upload(conn, tenant, access, collection, folder, name)

        return await run_as(app_engine, org, "ke", work)

    with pytest.raises(CollectionNotFound):
        await prepare(uuid.uuid4(), folder_id, None)
    with pytest.raises(FolderNotFound):
        await prepare(collection_id, uuid.uuid4(), None)
    with pytest.raises(InvalidFileName):
        await prepare(collection_id, folder_id, None)
    with pytest.raises(UnsupportedFormat):
        await prepare(collection_id, folder_id, "setup.exe")
    assert await prepare(collection_id, folder_id, "../a/Report.PDF") == documents.PreparedUpload(
        name="Report.PDF", format="pdf"
    )


async def test_store_audits_codes_and_writes_the_original(
    app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path
) -> None:
    org = await make_org()
    ids = await _setup(app_engine, org)

    row = await _upload(app_engine, org, file_store(tmp_path), ids, "secret-name.txt")

    assert (row.status, row.format, row.size_bytes, row.uploaded_by) == (
        "queued",
        "txt",
        4,
        org.user("ke"),
    )
    file_id = await document_file_id(app_engine, org.org_id, row.id)
    stored = (tmp_path / str(org.org_id) / f"{file_id}.bin").read_bytes()
    assert stored.startswith(b"EIA")
    assert len(stored) == len(b"text") + 32
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [
        tmp_path / str(org.org_id) / f"{file_id}.bin"
    ]
    events = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT action, old_value, new_value, actor FROM audit_events"
        " WHERE org_id = :org AND target_id = :id",
        {"id": row.id},
    )
    assert [tuple(e) for e in events] == [
        ("document.uploaded", None, "txt", f"user:{org.user('ke')}")
    ]


async def test_store_refuses_empty_file_and_quota(
    app_engine: AsyncEngine,
    make_org: MakeOrg,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = await make_org()
    ids = await _setup(app_engine, org)
    storage = file_store(tmp_path)
    monkeypatch.setattr(document_service, "ORG_QUOTA_BYTES", 6)

    with pytest.raises(EmptyFile):
        await _upload(app_engine, org, storage, ids, data=b"")
    await _upload(app_engine, org, storage, ids, data=b"123456")
    with pytest.raises(StorageQuotaExceeded):
        await _upload(app_engine, org, storage, ids, data=b"1")

    rows = await in_tenant(
        app_engine, org.org_id, "SELECT count(*) FROM documents WHERE org_id = :org"
    )
    assert rows[0][0] == 1


async def test_text_and_chunks_need_a_ready_document_of_the_collection(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    ids = await _setup(app_engine, org)
    queued = await add_document(app_engine, org, ids[0], ids[1])

    async def text(document_id: uuid.UUID) -> object:
        async def work(conn: Any, tenant: Any, access: Any) -> object:
            return await documents.get_document_text(conn, tenant, access, ids[0], document_id)

        return await run_as(app_engine, org, "ke", work)

    with pytest.raises(DocumentNotReady):
        await text(queued)
    with pytest.raises(DocumentNotFound):
        await text(uuid.uuid4())


async def test_remove_writes_the_audit_event_and_returns_not_found_after(
    app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path
) -> None:
    org = await make_org()
    ids = await _setup(app_engine, org)
    row = await _upload(app_engine, org, file_store(tmp_path), ids)

    async def remove(conn: Any, tenant: Any, access: Any) -> None:
        await documents.remove_document(conn, tenant, access, ids[0], row.id)

    await run_as(app_engine, org, "ke", remove)
    with pytest.raises(DocumentNotFound):
        await run_as(app_engine, org, "ke", remove)

    events = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT action, old_value, new_value FROM audit_events"
        " WHERE org_id = :org AND target_id = :id ORDER BY created_at, id",
        {"id": row.id},
    )
    assert [tuple(e) for e in events] == [
        ("document.uploaded", None, "txt"),
        ("document.removed", "txt", None),
    ]


async def test_upload_without_org_key_stores_nothing(
    app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path
) -> None:
    org = await make_org()
    ids = await _setup(app_engine, org)
    await in_tenant(app_engine, org.org_id, "DELETE FROM organization_keys WHERE org_id = :org")

    with pytest.raises(KeyNotFound):
        await _upload(app_engine, org, file_store(tmp_path), ids)

    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
    rows = await in_tenant(
        app_engine, org.org_id, "SELECT count(*) FROM documents WHERE org_id = :org"
    )
    assert rows[0][0] == 0


async def test_failed_insert_removes_stored_file(
    app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await make_org()
    ids = await _setup(app_engine, org)

    async def fail(*args: object, **kwargs: object) -> DocumentRow:
        raise RuntimeError("insert failed")

    monkeypatch.setattr(document_service, "insert_document", fail)
    store = file_store(tmp_path)
    stored: list[uuid.UUID] = []
    real_put = store.put

    async def put_and_record(*args: Any) -> uuid.UUID:
        file_id = await real_put(*args)
        stored.append(file_id)
        return file_id

    monkeypatch.setattr(store, "put", put_and_record)

    with pytest.raises(RuntimeError, match="insert failed"):
        await _upload(app_engine, org, store, ids)

    assert len(stored) == 1
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
