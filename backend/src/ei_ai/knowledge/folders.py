"""Folders: the service layer behind the folder routes of a collection (EA-32).

Same rules as the collection service: permission first, every statement filtered by the caller's
Organization and by a collection of the caller's Workspace (D46), the audit event written in the
same transaction, never a name in an event (D52). Check order: permission, then not found, then
input, then conflict.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.audit.events import (
    FOLDER_CREATED,
    FOLDER_DELETED,
    FOLDER_RENAMED,
    record_event,
    user_actor,
)
from ei_ai.db.constraints import violated_constraint
from ei_ai.knowledge.errors import (
    CollectionNotFound,
    FolderNotEmpty,
    FolderNotFound,
    FolderTooDeep,
    NameTaken,
)
from ei_ai.knowledge.folder_rows import (
    FolderRow,
    delete_folder_row,
    find_folder_row,
    has_subfolders,
    insert_folder,
    list_folder_rows,
    rename_folder_row,
)
from ei_ai.knowledge.names import clean_name
from ei_ai.knowledge.rows import find_collection_row
from ei_ai.rbac.access import WorkspaceAccess, ensure
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import TenantContext

_NAME_KEY = "folders_sibling_name_key"
_MAX_DEPTH = 3


async def _guard(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess, collection_id: uuid.UUID
) -> None:
    """Check the permission, then that the collection belongs to the caller's Workspace."""
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    collection = await find_collection_row(conn, tenant.org_id, access.workspace_id, collection_id)
    if collection is None:
        raise CollectionNotFound


async def _locked(
    conn: AsyncConnection, tenant: TenantContext, collection_id: uuid.UUID, folder_id: uuid.UUID
) -> FolderRow:
    """The folder of the collection with its row locked; ``FolderNotFound`` when there is none."""
    row = await find_folder_row(conn, tenant.org_id, collection_id, folder_id, for_update=True)
    if row is None:
        raise FolderNotFound
    return row


async def _event(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    folder_id: uuid.UUID,
    action: str,
) -> None:
    """Audit one change of a folder of the caller's Workspace."""
    await record_event(
        conn,
        tenant.org_id,
        user_actor(tenant.user_id),
        action,
        "folder",
        folder_id,
        workspace_id=access.workspace_id,
    )


async def list_folders(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess, collection_id: uuid.UUID
) -> list[FolderRow]:
    """The folders of a collection of the caller's Workspace, by depth, then name."""
    await _guard(conn, tenant, access, collection_id)
    return await list_folder_rows(conn, tenant.org_id, collection_id)


async def create_folder(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    *,
    name: str,
    parent_id: uuid.UUID | None,
) -> FolderRow:
    """Create a folder at the top or under a parent of the same collection (up to 3 levels)."""
    await _guard(conn, tenant, access, collection_id)
    depth = 1
    if parent_id is not None:
        parent = await _locked(conn, tenant, collection_id, parent_id)
        if parent.depth >= _MAX_DEPTH:
            raise FolderTooDeep
        depth = parent.depth + 1
    cleaned = clean_name(name)
    try:
        async with conn.begin_nested():
            row = await insert_folder(
                conn,
                tenant.org_id,
                collection_id,
                parent_id=parent_id,
                name=cleaned,
                depth=depth,
            )
    except IntegrityError as error:
        if violated_constraint(error) == _NAME_KEY:
            raise NameTaken from None
        raise
    await _event(conn, tenant, access, row.id, FOLDER_CREATED)
    return row


async def rename_folder(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    name: str,
) -> FolderRow:
    """Rename a folder. The same name again changes nothing and writes no event."""
    await _guard(conn, tenant, access, collection_id)
    current = await _locked(conn, tenant, collection_id, folder_id)
    cleaned = clean_name(name)
    if cleaned == current.name:
        return current
    try:
        async with conn.begin_nested():
            row = await rename_folder_row(conn, tenant.org_id, collection_id, folder_id, cleaned)
    except IntegrityError as error:
        if violated_constraint(error) == _NAME_KEY:
            raise NameTaken from None
        raise
    await _event(conn, tenant, access, folder_id, FOLDER_RENAMED)
    return row


async def delete_folder(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    folder_id: uuid.UUID,
) -> None:
    """Delete a folder that has no subfolders."""
    await _guard(conn, tenant, access, collection_id)
    await _locked(conn, tenant, collection_id, folder_id)
    if await has_subfolders(conn, tenant.org_id, collection_id, folder_id):
        raise FolderNotEmpty
    await delete_folder_row(conn, tenant.org_id, collection_id, folder_id)
    await _event(conn, tenant, access, folder_id, FOLDER_DELETED)
