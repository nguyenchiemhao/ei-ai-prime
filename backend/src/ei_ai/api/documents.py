"""Documents API (EA-33, contract "API").

The Organization, Workspace and caller come from the verified session and the path only (D32,
D46). The upload takes the raw file as its body and the name from the ``X-File-Name`` header,
reduced to a base name; the name is data, never part of a path. Errors are codes only. Nothing
here logs a file name or text (D52): the upload logs ids, format and size.
"""

import logging
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.api.deps import TenantSession
from ei_ai.api.errors import ErrorCode, raise_mapped
from ei_ai.jobs.envelope import JobEnvelope, envelope_for
from ei_ai.knowledge import documents
from ei_ai.knowledge.document_rows import DocumentRow
from ei_ai.knowledge.errors import (
    CollectionNotFound,
    DocumentNotFound,
    DocumentNotReady,
    EmptyFile,
    FileTooLarge,
    FolderNotFound,
    InvalidFileName,
    StorageQuotaExceeded,
    UnsupportedFormat,
)
from ei_ai.knowledge.ingestion.formats import MAX_FILE_BYTES
from ei_ai.knowledge.ingestion.job import INGEST_DOCUMENT
from ei_ai.knowledge.ingestion.status import shown_status
from ei_ai.rbac.access import WorkspaceAccess
from ei_ai.rbac.declarations import requires
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import TenantContext, require_tenant

router = APIRouter()
logger = logging.getLogger("ei_ai.knowledge")

DocumentStatus = Literal["queued", "processing", "ready", "failed", "not_supported"]

_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (CollectionNotFound, 404, "not_found"),
    (FolderNotFound, 404, "not_found"),
    (DocumentNotFound, 404, "not_found"),
    (InvalidFileName, 422, "invalid_file_name"),
    (UnsupportedFormat, 415, "unsupported_format"),
    (FileTooLarge, 413, "file_too_large"),
    (EmptyFile, 422, "empty_file"),
    (StorageQuotaExceeded, 413, "storage_quota_exceeded"),
    (DocumentNotReady, 409, "document_not_ready"),
)
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


class UploadedBy(BaseModel):
    id: uuid.UUID
    display_name: str


class DocumentItem(BaseModel):
    id: uuid.UUID
    folder_id: uuid.UUID
    name: str
    format: Literal["pdf", "docx", "md", "txt"]
    size_bytes: int
    status: DocumentStatus
    progress: int | None
    reason: str | None
    page_count: int | None
    uploaded_by: UploadedBy | None
    created_at: datetime
    updated_at: datetime


class DocumentList(BaseModel):
    documents: list[DocumentItem]


class TextPreview(BaseModel):
    text: str
    truncated: bool
    total_characters: int


class ChunkItem(BaseModel):
    ordinal: int
    text: str
    page: int | None
    heading_path: list[str]
    char_start: int
    char_end: int
    token_estimate: int


class ChunkList(BaseModel):
    chunks: list[ChunkItem]


_UNAUTHENTICATED = {"model": ErrorCode, "description": "No live session (unauthenticated)"}
_FORBIDDEN = {"model": ErrorCode, "description": "The role lacks the permission (forbidden)"}
_NOT_FOUND = {
    "model": ErrorCode,
    "description": "Unknown or invisible Workspace, collection, folder or document (not_found)",
}
_COMMON: dict[int | str, dict[str, Any]] = {401: _UNAUTHENTICATED, 403: _FORBIDDEN, 404: _NOT_FOUND}
_UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    **_COMMON,
    413: {
        "model": ErrorCode,
        "description": "Over the size limit or the storage quota (file_too_large,"
        " storage_quota_exceeded)",
    },
    415: {"model": ErrorCode, "description": "Unsupported file format (unsupported_format)"},
    422: {
        "model": ErrorCode,
        "description": "Bad file name or an empty file (invalid_file_name, empty_file)",
    },
}
_NOT_READY: dict[int | str, dict[str, Any]] = {
    **_COMMON,
    409: {"model": ErrorCode, "description": "The document is not ready (document_not_ready)"},
}
_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}

ManageAccess = Annotated[WorkspaceAccess, Depends(requires(Permission.KNOWLEDGE_MANAGE))]
Tenant = Annotated[TenantContext, Depends(require_tenant)]

_COLLECTION = "/workspaces/{workspace_id}/collections/{collection_id}"


def _raise_mapped(error: Exception) -> NoReturn:
    """Raise the HTTP error of a knowledge error (code only); anything else is re-raised."""
    raise_mapped(error, _ERRORS)


def _decode_file_name(raw: str | None) -> str | None:
    """The percent-decoded UTF-8 file name; None when the header is missing or not valid
    percent-encoding (the service then rejects it as an invalid file name)."""
    if raw is None or _BAD_ESCAPE.search(raw):
        return None
    try:
        return unquote(raw, errors="strict")
    except UnicodeDecodeError:
        return None


def _declared_too_large(request: Request) -> bool:
    """Whether ``Content-Length`` already declares more than the file limit."""
    declared = request.headers.get("content-length", "")
    return declared.isdigit() and int(declared) > MAX_FILE_BYTES


async def _read_body(request: Request) -> bytearray:
    """The request body, read in chunks and abandoned as soon as it passes the file limit.
    The buffer itself is returned: a ``bytes`` copy would hold the body twice."""
    buffer = bytearray()
    async for chunk in request.stream():
        buffer += chunk
        if len(buffer) > MAX_FILE_BYTES:
            raise FileTooLarge
    return buffer


def _item(row: DocumentRow, request: Request, tenant: TenantContext) -> DocumentItem:
    """The response of one document with the status shown now (queued, processing, interrupted)."""
    shown = shown_status(
        row.status,
        row.reason,
        row.updated_at,
        request.app.state.progress_board.read(tenant, row.id),
        request.app.state.clock(),
    )
    uploader = None
    if row.uploaded_by is not None and row.uploader_name is not None:
        uploader = UploadedBy(id=row.uploaded_by, display_name=row.uploader_name)
    return DocumentItem(
        id=row.id,
        folder_id=row.folder_id,
        name=row.name,
        format=row.format,
        size_bytes=row.size_bytes,
        status=shown.status,
        progress=shown.progress,
        reason=shown.reason,
        page_count=row.page_count if shown.status == "ready" else None,
        uploaded_by=uploader,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _submit_ingestion(app: FastAPI, envelope: JobEnvelope) -> None:
    """Hand the job to the runner. Async so it runs on the event loop, which the runner needs."""
    app.state.ingestion_runner.submit(envelope)


@router.post(
    _COLLECTION + "/folders/{folder_id}/documents",
    status_code=201,
    response_model=DocumentItem,
    responses=_UPLOAD_ERRORS,
    openapi_extra=_UPLOAD_BODY,
    summary="Upload one file into a folder (raw body, name in X-File-Name)",
)
async def upload_document(
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
    x_file_name: Annotated[
        str | None,
        Header(
            alias="X-File-Name",
            description="The file name, percent-encoded UTF-8; any path part is dropped",
        ),
    ] = None,
) -> DocumentItem:
    conn: AsyncConnection = await session.connection()
    files = request.app.state.file_store
    try:
        prepared = await documents.prepare_upload(
            conn, tenant, access, collection_id, folder_id, _decode_file_name(x_file_name)
        )
        if _declared_too_large(request):
            raise FileTooLarge
        data = await _read_body(request)
        row = await documents.store_document(
            conn, tenant, access, files, collection_id, folder_id, prepared, data
        )
    except Exception as error:
        _raise_mapped(error)
    logger.info(
        "document_uploaded document_id=%s org_id=%s format=%s size_bytes=%d",
        row.id,
        tenant.org_id,
        row.format,
        row.size_bytes,
    )
    envelope = envelope_for(tenant, INGEST_DOCUMENT, {"document_id": str(row.id)})
    # Background tasks run after the response, so after the transaction has committed.
    background_tasks.add_task(_submit_ingestion, request.app, envelope)
    return _item(row, request, tenant)


@router.get(
    _COLLECTION + "/documents",
    response_model=DocumentList,
    responses=_COMMON,
    summary="The documents of a collection, or of one folder, newest first",
)
async def list_documents(
    collection_id: uuid.UUID,
    request: Request,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
    folder_id: uuid.UUID | None = None,
) -> DocumentList:
    try:
        rows = await documents.list_documents(
            await session.connection(), tenant, access, collection_id, folder_id
        )
    except Exception as error:
        _raise_mapped(error)
    return DocumentList(documents=[_item(row, request, tenant) for row in rows])


@router.get(
    _COLLECTION + "/documents/{document_id}/text",
    response_model=TextPreview,
    responses=_NOT_READY,
    summary="The first 100 000 characters of the extracted text of a ready document",
)
async def get_document_text(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> TextPreview:
    try:
        preview = await documents.get_document_text(
            await session.connection(), tenant, access, collection_id, document_id
        )
    except Exception as error:
        _raise_mapped(error)
    return TextPreview(
        text=preview.text,
        truncated=preview.total_characters > len(preview.text),
        total_characters=preview.total_characters,
    )


@router.get(
    _COLLECTION + "/documents/{document_id}/chunks",
    response_model=ChunkList,
    responses=_NOT_READY,
    summary="The chunks of a ready document, by ordinal",
)
async def get_document_chunks(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> ChunkList:
    try:
        rows = await documents.get_document_chunks(
            await session.connection(), tenant, access, collection_id, document_id
        )
    except Exception as error:
        _raise_mapped(error)
    return ChunkList(
        chunks=[
            ChunkItem(
                ordinal=row.ordinal,
                text=row.text,
                page=row.page,
                heading_path=list(row.heading_path),
                char_start=row.char_start,
                char_end=row.char_end,
                token_estimate=row.token_estimate,
            )
            for row in rows
        ]
    )


@router.delete(
    _COLLECTION + "/documents/{document_id}",
    status_code=204,
    response_class=Response,
    responses=_COMMON,
    summary="Remove a document in any status, with its chunks and stored original",
)
async def remove_document(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> Response:
    try:
        file_id = await documents.remove_document(
            await session.connection(), tenant, access, collection_id, document_id
        )
    except Exception as error:
        _raise_mapped(error)
    # Background tasks run after the response, so after the transaction has committed.
    background_tasks.add_task(
        documents.delete_originals, request.app.state.file_store, tenant, [file_id]
    )
    return Response(status_code=204)
