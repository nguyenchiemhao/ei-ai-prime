"""Fixtures of the knowledge tests: Organizations with a Knowledge Editor and a Workspace Admin,
and queued documents for the ingestion tests."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.db.tenant import tenant_transaction
from ei_ai.rbac.access import WorkspaceAccess, load_workspace_access
from ei_ai.storage.files import OrgFileStore
from ei_ai.tenancy.context import TenantContext
from support.crypto import TEST_MASTER_KEY
from support.rbac.orgs import PersonSpec, RoleOrg, create_role_org
from support.tenants import OrgRows, purge_org_ids

MakeOrg = Callable[..., Awaitable[RoleOrg]]
Work = Callable[[Any, TenantContext, WorkspaceAccess], Awaitable[Any]]

PEOPLE: Mapping[str, PersonSpec] = {
    "ke": (None, {"x": "knowledge_editor"}),
    "ws_admin": (None, {"x": "workspace_admin", "y": "workspace_admin"}),
    "viewer": (None, {"x": "viewer"}),
}


def file_store(root: Path) -> OrgFileStore:
    """The encrypted store of originals at ``root``, with the test master key."""
    return OrgFileStore(root, OrgCipher(TEST_MASTER_KEY))


@pytest.fixture
async def make_org(app_engine: AsyncEngine) -> AsyncIterator[MakeOrg]:
    """``await make_org()``; each Organization is purged afterwards."""
    created: list[RoleOrg] = []

    async def make(
        people: Mapping[str, PersonSpec] = PEOPLE, workspaces: Sequence[str] = ("x", "y")
    ) -> RoleOrg:
        org = await create_role_org(app_engine, people, workspaces)
        created.append(org)
        return org

    try:
        yield make
    finally:
        await purge_org_ids(app_engine, *(org.org_id for org in created))


async def run_as(
    engine: AsyncEngine, org: RoleOrg, actor: str, work: Work, workspace: str = "x"
) -> Any:
    """Run ``work`` in the actor's tenant transaction with the actor's real access object."""
    tenant = TenantContext(org_id=org.org_id, user_id=org.user(actor))
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        access = await load_workspace_access(conn, tenant, org.workspace(workspace))
        assert access is not None, f"{actor} cannot see workspace {workspace}"
        return await work(conn, tenant, access)


async def queue_document(
    engine: AsyncEngine,
    files: OrgFileStore | None,
    org: OrgRows,
    fmt: str,
    data: bytes,
    name: str = "upload",
) -> uuid.UUID:
    """A ``queued`` document row of ``org`` and, when ``files`` is given, its original stored
    encrypted through it (otherwise the row names a file id that was never stored)."""
    document_id = uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        tenant = TenantContext(org_id=org.org_id, user_id=org.user_id)
        file_id = uuid.uuid4() if files is None else await files.put(conn, tenant, data)
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
                " size_bytes, status, uploaded_by, file_id)"
                " VALUES (:id, :org, :collection, :folder, :name, :format, :size, 'queued', :user,"
                " :file)"
            ),
            {
                "id": document_id,
                "org": org.org_id,
                "collection": org.collection_id,
                "folder": org.folder_id,
                "name": f"{name}.{fmt}",
                "format": fmt,
                "size": max(1, len(data)),
                "user": org.user_id,
                "file": file_id,
            },
        )
    return document_id


async def document_file_id(engine: AsyncEngine, org_id: uuid.UUID, document_id: uuid.UUID) -> Any:
    """The ``file_id`` of a document row (None when the row is gone)."""
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        return (
            await conn.execute(
                text("SELECT file_id FROM documents WHERE org_id = :org AND id = :id"),
                {"org": org_id, "id": document_id},
            )
        ).scalar_one_or_none()


async def document_row(engine: AsyncEngine, org: OrgRows, document_id: uuid.UUID) -> Any:
    """The stored state of one document and the number of its chunks."""
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        row = (
            await conn.execute(
                text(
                    "SELECT status, reason, page_count, chunk_count, extracted_text, updated_at,"
                    " processed_at,"
                    " (SELECT count(*) FROM document_chunks c"
                    "  WHERE c.org_id = :org AND c.document_id = d.id) AS chunks"
                    " FROM documents d WHERE d.org_id = :org AND d.id = :id"
                ),
                {"org": org.org_id, "id": document_id},
            )
        ).one()
    return row


_REASONS = {"failed": "corrupt_file", "not_supported": "scanned_pdf"}


async def add_document(
    engine: AsyncEngine,
    org: RoleOrg,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    status: str = "queued",
    file_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A document row of ``org`` in the given status (a reason is set for failed and
    not_supported). The row names ``file_id`` (a random id when none is given); no file is
    stored here."""
    document_id = uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
                " size_bytes, status, reason, uploaded_by, file_id)"
                " VALUES (:id, :org, :collection, :folder, 'a.txt', 'txt', 10, :status, :reason,"
                " :user, :file)"
            ),
            {
                "id": document_id,
                "org": org.org_id,
                "collection": collection_id,
                "folder": folder_id,
                "status": status,
                "reason": _REASONS.get(status),
                "user": org.user("ke"),
                "file": file_id or uuid.uuid4(),
            },
        )
    return document_id
