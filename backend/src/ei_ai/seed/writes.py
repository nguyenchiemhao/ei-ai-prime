"""Row steps of the demo seed, run inside one Organization's tenant transaction (EA-94 spec §2).

Every statement goes through the existing row helpers with the explicit ``org_id`` (D46); the
actor of every audit event is the Platform Operator. A step creates only what is missing: nothing
is updated or deleted, and an existing credential is never read or replaced.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.audit.events import (
    COLLECTION_CREATED,
    FOLDER_CREATED,
    ORGANIZATION_CREATED,
    PLATFORM_OPERATOR,
    USER_INVITED,
    USER_PASSWORD_SET,
    WORKSPACE_CREATED,
    WORKSPACE_MEMBER_ADDED,
    TargetType,
    record_event,
    record_role_change,
)
from ei_ai.auth.credentials import has_credential, insert_credential_if_missing
from ei_ai.auth.passwords import hash_password
from ei_ai.knowledge.folder_rows import insert_folder, list_folder_rows
from ei_ai.knowledge.groups import normalise_groups
from ei_ai.knowledge.rows import insert_collection, list_collection_rows
from ei_ai.members.rows import find_user_id, insert_user, insert_workspace_member
from ei_ai.provisioning.rows import (
    find_workspace_id,
    insert_organization,
    insert_workspace,
    organization_exists,
)
from ei_ai.seed.manifest import DemoManifest, Member, SeedCollection, SeedFolder


class SeedRun:
    """One Organization's seed inside its tenant transaction; counts the audit events written."""

    def __init__(self, conn: AsyncConnection, org_id: uuid.UUID) -> None:
        self.conn = conn
        self.org_id = org_id
        self.events = 0

    async def audit(
        self,
        action: str,
        target_type: TargetType,
        target_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID | None = None,
        new_value: str | None = None,
    ) -> None:
        """Record one event as the Platform Operator."""
        await record_event(
            self.conn,
            self.org_id,
            PLATFORM_OPERATOR,
            action,
            target_type,
            target_id,
            workspace_id=workspace_id,
            new_value=new_value,
        )
        self.events += 1

    async def audit_new_role(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID | None, role: str
    ) -> None:
        """Record a role given to a user who had none (a Workspace role when ``workspace_id``)."""
        await record_role_change(
            self.conn,
            self.org_id,
            PLATFORM_OPERATOR,
            user_id,
            workspace_id=workspace_id,
            old=None,
            new=role,
        )
        self.events += 1


@dataclass(frozen=True)
class _FolderPlace:
    """Where folders of one collection go: its Workspace, the collection and the folders it has,
    by ``(parent id, lower-case name)``."""

    workspace_id: uuid.UUID
    collection_id: uuid.UUID
    existing: dict[tuple[uuid.UUID | None, str], uuid.UUID]


async def _next_millisecond(conn: AsyncConnection) -> None:
    """Let the database clock pass one millisecond, so the next id (UUIDv7, millisecond
    precision) sorts after the previous one. Rows of one transaction share ``created_at``, and
    the default Workspace (R20) then follows the id: People Ops stays first."""
    await conn.execute(text("SELECT pg_sleep(0.001)"))


async def ensure_organization(run: SeedRun, manifest: DemoManifest) -> bool:
    """Create the Organization when missing; True when created."""
    if await organization_exists(run.conn, run.org_id):
        return False
    await insert_organization(run.conn, run.org_id, manifest.organization)
    await run.audit(ORGANIZATION_CREATED, "organization", run.org_id)
    return True


async def ensure_workspaces(
    run: SeedRun, manifest: DemoManifest
) -> dict[str, tuple[uuid.UUID, bool]]:
    """``name -> (id, created)`` of the manifest Workspaces, creating the missing ones."""
    workspaces: dict[str, tuple[uuid.UUID, bool]] = {}
    for workspace in manifest.workspaces:
        found = await find_workspace_id(run.conn, run.org_id, workspace.name)
        if found is not None:
            workspaces[workspace.name] = (found, False)
            continue
        await _next_millisecond(run.conn)
        ws_id = await insert_workspace(run.conn, run.org_id, workspace.name)
        await run.audit(WORKSPACE_CREATED, "workspace", ws_id)
        workspaces[workspace.name] = (ws_id, True)
    return workspaces


async def ensure_member(
    run: SeedRun, workspaces: Mapping[str, tuple[uuid.UUID, bool]], member: Member
) -> tuple[uuid.UUID, bool]:
    """``(user id, created)``: a new member gets every manifest role; an existing one only joins
    the manifest Workspaces created in this run (R10). Audited as the CLI does (R11)."""
    user_id = await find_user_id(run.conn, run.org_id, member.email)
    created = user_id is None
    if user_id is None:
        user_id = await insert_user(
            run.conn, run.org_id, member.email, member.name, member.org_role
        )
        await run.audit(USER_INVITED, "user", user_id)
        if member.org_role is not None:
            await run.audit_new_role(user_id, None, member.org_role)
    added = 0
    for name, (ws_id, ws_created) in workspaces.items():
        role = member.workspaces.get(name)
        if role is None or not (created or ws_created):
            continue
        if added:
            await _next_millisecond(run.conn)
        await insert_workspace_member(run.conn, run.org_id, ws_id, user_id, role)
        if not created:
            await run.audit(WORKSPACE_MEMBER_ADDED, "user", user_id)
        await run.audit_new_role(user_id, ws_id, role)
        added += 1
    return user_id, created


async def apply_password(run: SeedRun, user_id: uuid.UUID, password: str) -> bool:
    """Give the shared password to a user without a credential; True when stored."""
    if await has_credential(run.conn, run.org_id, user_id):
        return False
    password_hash = await hash_password(password)
    if not await insert_credential_if_missing(run.conn, run.org_id, user_id, password_hash):
        return False
    await run.audit(USER_PASSWORD_SET, "user", user_id)
    return True


async def _ensure_collections(
    run: SeedRun, ws_id: uuid.UUID, collections: Sequence[SeedCollection]
) -> tuple[dict[str, uuid.UUID], int]:
    """``(lower-case name -> id, number created)`` of the Workspace's manifest collections,
    creating the ones missing by name (ignoring case)."""
    ids = {
        row.name.lower(): row.id for row in await list_collection_rows(run.conn, run.org_id, ws_id)
    }
    created = 0
    for item in collections:
        if item.name.lower() in ids:
            continue
        row = await insert_collection(
            run.conn,
            run.org_id,
            ws_id,
            name=item.name,
            subtitle=item.subtitle,
            access_level=item.access_level,
            groups=normalise_groups(item.groups),
            local_only=item.local_only,
        )
        await run.audit(
            COLLECTION_CREATED,
            "collection",
            row.id,
            workspace_id=ws_id,
            new_value=item.access_level,
        )
        ids[item.name.lower()] = row.id
        created += 1
    return ids, created


async def _ensure_folders(
    run: SeedRun,
    place: _FolderPlace,
    folders: Sequence[SeedFolder],
    parent_id: uuid.UUID | None = None,
    depth: int = 1,
) -> int:
    """Create, parents first, the folders missing by (parent, name ignoring case); the number
    created. A renamed folder is left alone and its manifest name is created again."""
    created = 0
    for folder in folders:
        folder_id = place.existing.get((parent_id, folder.name.lower()))
        if folder_id is None:
            row = await insert_folder(
                run.conn,
                run.org_id,
                place.collection_id,
                parent_id=parent_id,
                name=folder.name,
                depth=depth,
            )
            await run.audit(FOLDER_CREATED, "folder", row.id, workspace_id=place.workspace_id)
            folder_id = row.id
            created += 1
        created += await _ensure_folders(run, place, folder.folders, folder_id, depth + 1)
    return created


async def ensure_knowledge(
    run: SeedRun, manifest: DemoManifest, workspaces: Mapping[str, tuple[uuid.UUID, bool]]
) -> tuple[int, int]:
    """``(collections created, folders created)`` over every manifest Workspace."""
    collections_created = folders_created = 0
    for workspace in manifest.workspaces:
        ws_id = workspaces[workspace.name][0]
        ids, created = await _ensure_collections(run, ws_id, workspace.collections)
        collections_created += created
        for item in workspace.collections:
            collection_id = ids[item.name.lower()]
            rows = await list_folder_rows(run.conn, run.org_id, collection_id)
            existing = {(row.parent_id, row.name.lower()): row.id for row in rows}
            place = _FolderPlace(ws_id, collection_id, existing)
            folders_created += await _ensure_folders(run, place, item.folders)
    return collections_created, folders_created
