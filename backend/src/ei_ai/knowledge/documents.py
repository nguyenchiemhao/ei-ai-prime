"""Documents: the service layer behind the document routes of a collection (EA-33).

Same rules as the folder service: permission first, every statement filtered by the caller's
Organization and by a collection of the caller's Workspace (D46), the audit event written in the
same transaction, never a file name or text in an event or a log (D52). Check order for an
upload: permission, ids, file name, format, size, empty, quota.

Originals are stored encrypted with the Organization's key through EA-20's ``OrgFileStore``
(``<root>/<org_id>/<file_id>.bin``). A file id is read only from the caller's own document row.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.audit.events import DOCUMENT_REMOVED, DOCUMENT_UPLOADED, record_event, user_actor
from ei_ai.db.constraints import violated_constraint
from ei_ai.knowledge.document_rows import (
    ChunkRow,
    DocumentRow,
    DocumentText,
    delete_document_row,
    find_document_row,
    insert_document,
    list_chunk_rows,
    list_document_rows,
    organization_size_bytes,
    read_document_text,
)
from ei_ai.knowledge.errors import (
    DocumentNotFound,
    DocumentNotReady,
    EmptyFile,
    FileTooLarge,
    FolderNotFound,
    StorageQuotaExceeded,
    UnsupportedFormat,
)
from ei_ai.knowledge.folder_rows import find_folder_row
from ei_ai.knowledge.folders import guard_collection
from ei_ai.knowledge.ingestion.formats import (
    MAX_FILE_BYTES,
    ORG_QUOTA_BYTES,
    clean_file_name,
    format_for,
)
from ei_ai.rbac.access import WorkspaceAccess, ensure
from ei_ai.rbac.permissions import Permission
from ei_ai.storage.files import OrgFileStore
from ei_ai.tenancy.context import TenantContext

logger = logging.getLogger("ei_ai.knowledge")

_FOLDER_KEY = "documents_org_id_collection_id_folder_id_fkey"
_READY = "ready"


@dataclass(frozen=True)
class PreparedUpload:
    """A file name and format that passed the checks that run before the body is read."""

    name: str
    format: str


async def _find(
    conn: AsyncConnection,
    tenant: TenantContext,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> DocumentRow:
    """The document of the collection; ``DocumentNotFound`` when there is none."""
    row = await find_document_row(
        conn, tenant.org_id, collection_id, document_id, for_update=for_update
    )
    if row is None:
        raise DocumentNotFound
    return row


async def prepare_upload(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    raw_name: str | None,
) -> PreparedUpload:
    """Check the permission, the ids, then the file name and format of an upload.

    Input: the decoded ``X-File-Name`` (None when the header is missing).
    Output: the cleaned base name and its format; raises ``InvalidFileName`` or
    ``UnsupportedFormat``.
    """
    await guard_collection(conn, tenant, access, collection_id)
    if await find_folder_row(conn, tenant.org_id, collection_id, folder_id) is None:
        raise FolderNotFound
    name = clean_file_name("" if raw_name is None else raw_name)
    file_format = format_for(name)
    if file_format is None:
        raise UnsupportedFormat
    return PreparedUpload(name=name, format=file_format)


async def store_document(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    files: OrgFileStore,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    prepared: PreparedUpload,
    data: bytes | bytearray,
) -> DocumentRow:
    """Check size and quota, store the original encrypted, then insert the ``queued`` row with
    its file id and audit event. If the row cannot be written, the stored file is deleted and
    the error re-raised. A key error of the store (no, destroyed or mismatched key) propagates
    before anything is written. The caller dispatches the ingestion job after the commit."""
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    if len(data) > MAX_FILE_BYTES:
        raise FileTooLarge
    if not data:
        raise EmptyFile
    if await organization_size_bytes(conn, tenant.org_id) + len(data) > ORG_QUOTA_BYTES:
        raise StorageQuotaExceeded
    file_id = await files.put(conn, tenant, data)
    try:
        return await _insert_queued(
            conn, tenant, access, collection_id, folder_id, prepared, len(data), file_id
        )
    except Exception:
        await delete_originals(files, tenant, [file_id])
        raise


async def _insert_queued(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    prepared: PreparedUpload,
    size_bytes: int,
    file_id: uuid.UUID,
) -> DocumentRow:
    """Insert the ``queued`` row of a stored original and write ``DOCUMENT_UPLOADED``; a folder
    deleted meanwhile raises ``FolderNotFound``."""
    try:
        async with conn.begin_nested():
            row = await insert_document(
                conn,
                tenant.org_id,
                collection_id,
                folder_id,
                name=prepared.name,
                file_format=prepared.format,
                size_bytes=size_bytes,
                uploaded_by=tenant.user_id,
                file_id=file_id,
            )
    except IntegrityError as error:
        if violated_constraint(error) == _FOLDER_KEY:
            raise FolderNotFound from None
        raise
    await record_event(
        conn,
        tenant.org_id,
        user_actor(tenant.user_id),
        DOCUMENT_UPLOADED,
        "document",
        row.id,
        workspace_id=access.workspace_id,
        new_value=prepared.format,
    )
    return row


async def list_documents(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID | None,
) -> list[DocumentRow]:
    """The documents of a collection of the caller's Workspace, or of one of its folders,
    newest first."""
    await guard_collection(conn, tenant, access, collection_id)
    if folder_id is not None:
        if await find_folder_row(conn, tenant.org_id, collection_id, folder_id) is None:
            raise FolderNotFound
    return await list_document_rows(conn, tenant.org_id, collection_id, folder_id)


async def get_document_text(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
) -> DocumentText:
    """The preview text of a ready document; ``DocumentNotReady`` for any other status."""
    await guard_collection(conn, tenant, access, collection_id)
    row = await _find(conn, tenant, collection_id, document_id)
    if row.status != _READY:
        raise DocumentNotReady
    return await read_document_text(conn, tenant.org_id, collection_id, document_id)


async def get_document_chunks(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
) -> list[ChunkRow]:
    """The chunks of a ready document, by ordinal; ``DocumentNotReady`` for any other status."""
    await guard_collection(conn, tenant, access, collection_id)
    row = await _find(conn, tenant, collection_id, document_id)
    if row.status != _READY:
        raise DocumentNotReady
    return await list_chunk_rows(conn, tenant.org_id, collection_id, document_id)


async def remove_document(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
) -> uuid.UUID:
    """Delete a document in any status with its chunks and write the audit event. Returns the
    file id of its stored original, which the caller deletes after the transaction has
    committed."""
    await guard_collection(conn, tenant, access, collection_id)
    row = await _find(conn, tenant, collection_id, document_id, for_update=True)
    file_id = await delete_document_row(conn, tenant.org_id, collection_id, document_id)
    if file_id is None:  # not reachable while the row is locked
        raise DocumentNotFound
    await record_event(
        conn,
        tenant.org_id,
        user_actor(tenant.user_id),
        DOCUMENT_REMOVED,
        "document",
        document_id,
        workspace_id=access.workspace_id,
        old_value=row.format,
    )
    return file_id


async def delete_originals(
    files: OrgFileStore, tenant: TenantContext, file_ids: Sequence[uuid.UUID]
) -> None:
    """Delete stored originals by file id, in the caller's Organization only (run after the
    removal has committed). No key is needed, so this works after the key was destroyed; a file
    that is already gone is not an error.

    A failure is logged with the file id, the Organization and the error class only; the
    remaining files are still deleted.
    """
    for file_id in file_ids:
        try:
            await files.delete(tenant, file_id)
        except Exception as error:
            logger.error(
                "document_original_delete_failed file_id=%s org_id=%s error=%s",
                file_id,
                tenant.org_id,
                type(error).__name__,
            )
