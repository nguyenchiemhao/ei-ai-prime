"""Collections and folders API (EA-32, contract "API").

The Organization, Workspace and caller come from the verified session and the path only (D32,
D46); request bodies never carry an id, an Organization or a Workspace (extra fields are
refused). Errors are codes only and never echo the input. Nothing here logs: a collection name,
a subtitle or a group must not reach a log (D52).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ei_ai.api.deps import TenantSession
from ei_ai.api.errors import ErrorCode
from ei_ai.knowledge import folders, service
from ei_ai.knowledge.errors import (
    CollectionNotFound,
    FolderNotEmpty,
    FolderNotFound,
    FolderTooDeep,
    GroupsRequired,
    InvalidGroup,
    InvalidKnowledgeInput,
    NameTaken,
)
from ei_ai.knowledge.folder_rows import FolderRow
from ei_ai.knowledge.rows import CollectionRow
from ei_ai.rbac.access import WorkspaceAccess
from ei_ai.rbac.declarations import requires
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import TenantContext, require_tenant

router = APIRouter()

AccessLevel = Literal["public", "authenticated", "restricted"]

_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (CollectionNotFound, 404, "not_found"),
    (FolderNotFound, 404, "not_found"),
    (GroupsRequired, 422, "groups_required"),
    (InvalidGroup, 422, "invalid_group"),
    (InvalidKnowledgeInput, 422, "invalid_request"),
    (FolderTooDeep, 422, "folder_too_deep"),
    (NameTaken, 409, "name_taken"),
    (FolderNotEmpty, 409, "folder_not_empty"),
)


class CollectionCreate(BaseModel):
    """Only these fields: an ``id``, ``org_id``, ``workspace_id`` or any other field is a 422."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str
    subtitle: str | None = None
    access_level: AccessLevel
    groups: list[str] = []
    local_only: bool = False


class CollectionUpdate(BaseModel):
    """At least one of the three fields; the access level is changed on its own route."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = None
    subtitle: str | None = None
    local_only: bool | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "CollectionUpdate":
        if not self.model_fields_set:
            raise ValueError("nothing to change")
        return self


class AccessChange(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    access_level: AccessLevel
    groups: list[str]


class FolderCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str
    # Not strict: a JSON body carries the id as a string.
    parent_id: uuid.UUID | None = Field(default=None, strict=False)


class FolderRename(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str


class DocumentSummary(BaseModel):
    total: int = 0
    ready: int = 0
    processing: int = 0
    needs_attention: int = 0


class UsedBy(BaseModel):
    id: uuid.UUID
    name: str


class CollectionItem(BaseModel):
    id: uuid.UUID
    name: str
    subtitle: str | None
    access_level: str
    groups: list[str]
    local_only: bool
    documents: DocumentSummary
    used_by: list[UsedBy]
    created_at: datetime
    updated_at: datetime


class FolderItem(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    depth: int


class CollectionList(BaseModel):
    collections: list[CollectionItem]


class CollectionDetail(CollectionItem):
    folders: list[FolderItem]


def _item(row: CollectionRow) -> CollectionItem:
    """The response of one collection; documents and agents are not tracked yet (all empty)."""
    return CollectionItem(
        id=row.id,
        name=row.name,
        subtitle=row.subtitle,
        access_level=row.access_level,
        groups=list(row.groups),
        local_only=row.local_only,
        documents=DocumentSummary(),
        used_by=[],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _folder_item(row: FolderRow) -> FolderItem:
    return FolderItem(id=row.id, name=row.name, parent_id=row.parent_id, depth=row.depth)


def _raise_mapped(error: Exception) -> NoReturn:
    """Raise the HTTP error of a knowledge error (code only); anything else is re-raised."""
    for kind, status, code in _ERRORS:
        if isinstance(error, kind):
            raise HTTPException(status_code=status, detail=code) from None
    raise error


_UNAUTHENTICATED = {"model": ErrorCode, "description": "No live session (unauthenticated)"}
_FORBIDDEN = {"model": ErrorCode, "description": "The role lacks the permission (forbidden)"}
_NOT_FOUND = {
    "model": ErrorCode,
    "description": "Unknown or invisible Workspace, collection or folder (not_found)",
}
_INVALID = {
    "model": ErrorCode,
    "description": "Malformed request or an unacceptable value (invalid_request, groups_required,"
    " invalid_group, folder_too_deep)",
}
_CONFLICT = {
    "model": ErrorCode,
    "description": "The name is taken or the folder has subfolders (name_taken, folder_not_empty)",
}
_COMMON: dict[int | str, dict[str, Any]] = {
    401: _UNAUTHENTICATED,
    403: _FORBIDDEN,
    404: _NOT_FOUND,
    422: _INVALID,
}

ManageAccess = Annotated[WorkspaceAccess, Depends(requires(Permission.KNOWLEDGE_MANAGE))]
AccessManage = Annotated[WorkspaceAccess, Depends(requires(Permission.COLLECTIONS_ACCESS_MANAGE))]
Tenant = Annotated[TenantContext, Depends(require_tenant)]

_BASE = "/workspaces/{workspace_id}/collections"


@router.get(
    _BASE,
    response_model=CollectionList,
    responses=_COMMON,
    summary="The collections of a Workspace, by name",
)
async def list_collections(
    tenant: Tenant, access: ManageAccess, session: TenantSession
) -> CollectionList:
    rows = await service.list_collections(await session.connection(), tenant, access)
    return CollectionList(collections=[_item(row) for row in rows])


@router.post(
    _BASE,
    status_code=201,
    response_model=CollectionItem,
    responses={**_COMMON, 409: _CONFLICT},
    summary="Create a collection (Public also needs the access permission)",
)
async def create_collection(
    body: CollectionCreate, tenant: Tenant, access: ManageAccess, session: TenantSession
) -> CollectionItem:
    try:
        row = await service.create_collection(
            await session.connection(),
            tenant,
            access,
            name=body.name,
            subtitle=body.subtitle,
            access_level=body.access_level,
            groups=body.groups,
            local_only=body.local_only,
        )
    except Exception as error:
        _raise_mapped(error)
    return _item(row)


@router.get(
    _BASE + "/{collection_id}",
    response_model=CollectionDetail,
    responses=_COMMON,
    summary="One collection with its folders",
)
async def get_collection(
    collection_id: uuid.UUID, tenant: Tenant, access: ManageAccess, session: TenantSession
) -> CollectionDetail:
    conn = await session.connection()
    try:
        row = await service.get_collection(conn, tenant, access, collection_id)
        folder_rows = await folders.list_folders(conn, tenant, access, collection_id)
    except Exception as error:
        _raise_mapped(error)
    return CollectionDetail(
        **_item(row).model_dump(), folders=[_folder_item(folder) for folder in folder_rows]
    )


@router.patch(
    _BASE + "/{collection_id}",
    response_model=CollectionItem,
    responses={**_COMMON, 409: _CONFLICT},
    summary="Change name, subtitle or data handling (local-only off needs access permission)",
)
async def update_collection(
    collection_id: uuid.UUID,
    body: CollectionUpdate,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> CollectionItem:
    try:
        row = await service.update_collection(
            await session.connection(),
            tenant,
            access,
            collection_id,
            body.model_dump(exclude_unset=True),
        )
    except Exception as error:
        _raise_mapped(error)
    return _item(row)


@router.put(
    _BASE + "/{collection_id}/access",
    response_model=CollectionItem,
    responses=_COMMON,
    summary="Set who can read a collection",
)
async def change_access(
    collection_id: uuid.UUID,
    body: AccessChange,
    tenant: Tenant,
    access: AccessManage,
    session: TenantSession,
) -> CollectionItem:
    try:
        row = await service.change_access(
            await session.connection(),
            tenant,
            access,
            collection_id,
            access_level=body.access_level,
            groups=body.groups,
        )
    except Exception as error:
        _raise_mapped(error)
    return _item(row)


@router.delete(
    _BASE + "/{collection_id}",
    status_code=204,
    response_class=Response,
    responses=_COMMON,
    summary="Delete a collection and its folders",
)
async def delete_collection(
    collection_id: uuid.UUID, tenant: Tenant, access: ManageAccess, session: TenantSession
) -> Response:
    try:
        await service.delete_collection(await session.connection(), tenant, access, collection_id)
    except Exception as error:
        _raise_mapped(error)
    return Response(status_code=204)


@router.post(
    _BASE + "/{collection_id}/folders",
    status_code=201,
    response_model=FolderItem,
    responses={**_COMMON, 409: _CONFLICT},
    summary="Create a folder at the top or under a parent (up to 3 levels)",
)
async def create_folder(
    collection_id: uuid.UUID,
    body: FolderCreate,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> FolderItem:
    try:
        row = await folders.create_folder(
            await session.connection(),
            tenant,
            access,
            collection_id,
            name=body.name,
            parent_id=body.parent_id,
        )
    except Exception as error:
        _raise_mapped(error)
    return _folder_item(row)


@router.patch(
    _BASE + "/{collection_id}/folders/{folder_id}",
    response_model=FolderItem,
    responses={**_COMMON, 409: _CONFLICT},
    summary="Rename a folder",
)
async def rename_folder(
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    body: FolderRename,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> FolderItem:
    try:
        row = await folders.rename_folder(
            await session.connection(), tenant, access, collection_id, folder_id, name=body.name
        )
    except Exception as error:
        _raise_mapped(error)
    return _folder_item(row)


@router.delete(
    _BASE + "/{collection_id}/folders/{folder_id}",
    status_code=204,
    response_class=Response,
    responses={**_COMMON, 409: _CONFLICT},
    summary="Delete a folder that has no subfolders",
)
async def delete_folder(
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> Response:
    try:
        await folders.delete_folder(
            await session.connection(), tenant, access, collection_id, folder_id
        )
    except Exception as error:
        _raise_mapped(error)
    return Response(status_code=204)
