"""Collections: the service layer behind the Knowledge API (EA-32).

Every function takes the caller's access object and checks the permission itself (``ensure``).
Every statement is filtered by the caller's Organization and Workspace (D46) and the actor of
every audit event is the signed-in caller (D32). A change and its audit event run in the caller's
tenant transaction: they commit together, or neither does. A call that changes nothing writes no
event. Audit values are codes only; names, subtitles and groups are never audited or logged (D52).
Check order: permission, then not found, then input, then conflict.
"""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.audit.events import (
    COLLECTION_ACCESS_CHANGED,
    COLLECTION_CREATED,
    COLLECTION_DELETED,
    COLLECTION_GROUPS_CHANGED,
    COLLECTION_LOCAL_ONLY_CHANGED,
    COLLECTION_UPDATED,
    record_event,
    user_actor,
)
from ei_ai.db.constraints import violated_constraint
from ei_ai.knowledge.document_rows import list_document_file_ids
from ei_ai.knowledge.errors import (
    CollectionNotFound,
    GroupsRequired,
    InvalidKnowledgeInput,
    NameTaken,
)
from ei_ai.knowledge.groups import normalise_groups
from ei_ai.knowledge.indexing.index_rows import sync_collection_access
from ei_ai.knowledge.names import clean_name, clean_subtitle
from ei_ai.knowledge.rows import (
    CollectionRow,
    delete_collection_row,
    find_collection_row,
    insert_collection,
    list_collection_rows,
    update_collection_access_row,
    update_collection_settings_row,
)
from ei_ai.rbac.access import WorkspaceAccess, ensure
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import TenantContext

_LEVELS = frozenset({"public", "authenticated", "restricted"})
_CHANGEABLE = frozenset({"name", "subtitle", "local_only"})
_NAME_KEY = "collections_workspace_name_key"
_ANY_MODEL = "any_model"
_LOCAL_ONLY = "local_only"
_PUBLIC = "public"
_RESTRICTED = "restricted"


def _clean_access(access_level: str, groups: Sequence[str]) -> list[str]:
    """The normalised groups for the level. Groups belong to ``restricted`` only, which needs at
    least one."""
    if access_level not in _LEVELS:
        raise InvalidKnowledgeInput
    if access_level != _RESTRICTED:
        if groups:
            raise InvalidKnowledgeInput
        return []
    normalised = normalise_groups(groups)
    if not normalised:
        raise GroupsRequired
    return normalised


def _handling(local_only: bool) -> str:
    """The audit code of the data-handling setting."""
    return _LOCAL_ONLY if local_only else _ANY_MODEL


async def _event(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    action: str,
    old: str | None,
    new: str | None,
) -> None:
    """Audit one change of a collection of the caller's Workspace."""
    await record_event(
        conn,
        tenant.org_id,
        user_actor(tenant.user_id),
        action,
        "collection",
        collection_id,
        workspace_id=access.workspace_id,
        old_value=old,
        new_value=new,
    )


async def _locked(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess, collection_id: uuid.UUID
) -> CollectionRow:
    """The collection of the caller's Workspace with its row locked; 404 when there is none."""
    row = await find_collection_row(
        conn, tenant.org_id, access.workspace_id, collection_id, for_update=True
    )
    if row is None:
        raise CollectionNotFound
    return row


def _merge_settings(
    current: CollectionRow, changes: Mapping[str, object]
) -> tuple[str, str | None, bool]:
    """The validated name, subtitle and local-only flag after applying ``changes``."""
    name, subtitle, local_only = current.name, current.subtitle, current.local_only
    if "name" in changes:
        raw_name = changes["name"]
        if not isinstance(raw_name, str):
            raise InvalidKnowledgeInput
        name = clean_name(raw_name)
    if "subtitle" in changes:
        raw_subtitle = changes["subtitle"]
        if raw_subtitle is not None and not isinstance(raw_subtitle, str):
            raise InvalidKnowledgeInput
        subtitle = clean_subtitle(raw_subtitle)
    if "local_only" in changes:
        raw_flag = changes["local_only"]
        if not isinstance(raw_flag, bool):
            raise InvalidKnowledgeInput
        local_only = raw_flag
    return name, subtitle, local_only


async def list_collections(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess
) -> list[CollectionRow]:
    """The collections of the caller's Workspace, by name ignoring case."""
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    return await list_collection_rows(conn, tenant.org_id, access.workspace_id)


async def get_collection(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess, collection_id: uuid.UUID
) -> CollectionRow:
    """One collection of the caller's Workspace; ``CollectionNotFound`` otherwise."""
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    row = await find_collection_row(conn, tenant.org_id, access.workspace_id, collection_id)
    if row is None:
        raise CollectionNotFound
    return row


async def create_collection(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    *,
    name: str,
    subtitle: str | None,
    access_level: str,
    groups: Sequence[str],
    local_only: bool,
) -> CollectionRow:
    """Create a collection. Making it Public also needs the access permission (OD1)."""
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    if access_level == _PUBLIC:
        ensure(access.permissions, Permission.COLLECTIONS_ACCESS_MANAGE)
    cleaned_name = clean_name(name)
    cleaned_subtitle = clean_subtitle(subtitle)
    cleaned_groups = _clean_access(access_level, groups)
    try:
        async with conn.begin_nested():
            row = await insert_collection(
                conn,
                tenant.org_id,
                access.workspace_id,
                name=cleaned_name,
                subtitle=cleaned_subtitle,
                access_level=access_level,
                groups=cleaned_groups,
                local_only=local_only,
            )
    except IntegrityError as error:
        if violated_constraint(error) == _NAME_KEY:
            raise NameTaken from None
        raise
    await _event(conn, tenant, access, row.id, COLLECTION_CREATED, None, access_level)
    return row


async def update_collection(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    changes: Mapping[str, object],
) -> CollectionRow:
    """Change the name, subtitle or local-only flag (keys of ``changes``). Switching local-only
    off also needs the access permission (OD2). The same values again change nothing."""
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    current = await _locked(conn, tenant, access, collection_id)
    if not set(changes) <= _CHANGEABLE:
        raise InvalidKnowledgeInput
    name, subtitle, local_only = _merge_settings(current, changes)
    if current.local_only and not local_only:
        ensure(access.permissions, Permission.COLLECTIONS_ACCESS_MANAGE)
    text_changed = (name, subtitle) != (current.name, current.subtitle)
    if not text_changed and local_only == current.local_only:
        return current
    try:
        async with conn.begin_nested():
            row = await update_collection_settings_row(
                conn,
                tenant.org_id,
                access.workspace_id,
                collection_id,
                name=name,
                subtitle=subtitle,
                local_only=local_only,
            )
    except IntegrityError as error:
        if violated_constraint(error) == _NAME_KEY:
            raise NameTaken from None
        raise
    if text_changed:
        await _event(conn, tenant, access, collection_id, COLLECTION_UPDATED, None, None)
    if local_only != current.local_only:
        await _event(
            conn,
            tenant,
            access,
            collection_id,
            COLLECTION_LOCAL_ONLY_CHANGED,
            _handling(current.local_only),
            _handling(local_only),
        )
    return row


async def change_access(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    collection_id: uuid.UUID,
    *,
    access_level: str,
    groups: Sequence[str],
) -> CollectionRow:
    """Set who can read the collection. Needs the access permission; the old and new level (or,
    for a groups-only change, the unchanged ``restricted``) are audited."""
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    ensure(access.permissions, Permission.COLLECTIONS_ACCESS_MANAGE)
    current = await _locked(conn, tenant, access, collection_id)
    cleaned_groups = _clean_access(access_level, groups)
    level_changed = access_level != current.access_level
    if not level_changed and tuple(cleaned_groups) == current.groups:
        return current
    row = await update_collection_access_row(
        conn,
        tenant.org_id,
        access.workspace_id,
        collection_id,
        access_level=access_level,
        groups=cleaned_groups,
    )
    await sync_collection_access(conn, tenant.org_id, collection_id, access_level, cleaned_groups)
    action = COLLECTION_ACCESS_CHANGED if level_changed else COLLECTION_GROUPS_CHANGED
    await _event(conn, tenant, access, collection_id, action, current.access_level, access_level)
    return row


async def delete_collection(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess, collection_id: uuid.UUID
) -> list[uuid.UUID]:
    """Delete a collection and, with it, its folders, documents and chunks.

    Returns the file ids of the stored originals of the deleted documents; the caller deletes
    them once the transaction has committed.
    """
    ensure(access.permissions, Permission.KNOWLEDGE_MANAGE)
    current = await _locked(conn, tenant, access, collection_id)
    file_ids = await list_document_file_ids(conn, tenant.org_id, collection_id)
    await delete_collection_row(conn, tenant.org_id, access.workspace_id, collection_id)
    await _event(
        conn, tenant, access, collection_id, COLLECTION_DELETED, current.access_level, None
    )
    return file_ids
