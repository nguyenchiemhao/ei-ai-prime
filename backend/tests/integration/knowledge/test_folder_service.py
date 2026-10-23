"""The folder service: nesting, names, tenant scoping, audit and permission."""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.knowledge import folders, service
from ei_ai.knowledge.errors import (
    CollectionNotFound,
    FolderNotEmpty,
    FolderNotFound,
    FolderTooDeep,
    InvalidKnowledgeInput,
    NameTaken,
)
from ei_ai.knowledge.folder_rows import FolderRow
from ei_ai.rbac.access import PermissionDenied
from support.rbac.orgs import RoleOrg
from support.sign_in import in_tenant

from .conftest import MakeOrg, add_document, run_as

pytestmark = pytest.mark.integration


async def _collection(
    engine: AsyncEngine, org: RoleOrg, name: str = "Handbook", workspace: str = "x"
) -> uuid.UUID:
    async def work(conn: Any, tenant: Any, access: Any) -> uuid.UUID:
        row = await service.create_collection(
            conn,
            tenant,
            access,
            name=name,
            subtitle=None,
            access_level="authenticated",
            groups=[],
            local_only=False,
        )
        return row.id

    return await run_as(engine, org, "ws_admin", work, workspace)  # type: ignore[no-any-return]


async def _folder(
    engine: AsyncEngine,
    org: RoleOrg,
    collection_id: uuid.UUID,
    name: str,
    parent_id: uuid.UUID | None = None,
    actor: str = "ke",
) -> FolderRow:
    async def work(conn: Any, tenant: Any, access: Any) -> FolderRow:
        return await folders.create_folder(
            conn, tenant, access, collection_id, name=name, parent_id=parent_id
        )

    return await run_as(engine, org, actor, work)  # type: ignore[no-any-return]


async def _rename(
    engine: AsyncEngine, org: RoleOrg, collection_id: uuid.UUID, folder_id: uuid.UUID, name: str
) -> FolderRow:
    async def work(conn: Any, tenant: Any, access: Any) -> FolderRow:
        return await folders.rename_folder(
            conn, tenant, access, collection_id, folder_id, name=name
        )

    return await run_as(engine, org, "ke", work)  # type: ignore[no-any-return]


async def _delete(
    engine: AsyncEngine, org: RoleOrg, collection_id: uuid.UUID, folder_id: uuid.UUID
) -> None:
    async def work(conn: Any, tenant: Any, access: Any) -> None:
        await folders.delete_folder(conn, tenant, access, collection_id, folder_id)

    await run_as(engine, org, "ke", work)


async def _audit(engine: AsyncEngine, org: RoleOrg, folder_id: uuid.UUID) -> list[Any]:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT action, target_type, old_value, new_value, workspace_id, actor FROM audit_events"
        " WHERE org_id = :org AND target_id = :id ORDER BY created_at, id",
        {"id": folder_id},
    )
    return [tuple(row) for row in rows]


async def test_create_nested_three_levels(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)

    top = await _folder(app_engine, org, collection_id, "  Policies ")
    middle = await _folder(app_engine, org, collection_id, "2026", top.id)
    leaf = await _folder(app_engine, org, collection_id, "Q1", middle.id)

    async def listing(conn: Any, tenant: Any, access: Any) -> list[FolderRow]:
        return await folders.list_folders(conn, tenant, access, collection_id)

    assert (top.name, top.parent_id, top.depth) == ("Policies", None, 1)
    assert (middle.parent_id, middle.depth) == (top.id, 2)
    assert (leaf.parent_id, leaf.depth) == (middle.id, 3)
    assert await run_as(app_engine, org, "ke", listing) == [top, middle, leaf]
    assert await _audit(app_engine, org, top.id) == [
        ("folder.created", "folder", None, None, org.workspace("x"), f"user:{org.user('ke')}")
    ]


async def test_fourth_level_is_too_deep(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)
    parent = None
    for name in ("a", "b", "c"):
        parent = await _folder(app_engine, org, collection_id, name, parent.id if parent else None)
    assert parent is not None

    with pytest.raises(FolderTooDeep):
        await _folder(app_engine, org, collection_id, "d", parent.id)


async def test_invalid_name_is_rejected(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)

    with pytest.raises(InvalidKnowledgeInput):
        await _folder(app_engine, org, collection_id, "   ")
    with pytest.raises(InvalidKnowledgeInput):
        await _folder(app_engine, org, collection_id, "n" * 201)


async def test_sibling_name_taken_case_insensitive(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)
    first = await _folder(app_engine, org, collection_id, "Policies")
    other = await _folder(app_engine, org, collection_id, "Forms")

    with pytest.raises(NameTaken):
        await _folder(app_engine, org, collection_id, "POLICIES")
    await _folder(app_engine, org, collection_id, "policies", first.id)
    await _folder(app_engine, org, collection_id, "policies", other.id)
    with pytest.raises(NameTaken):
        await _folder(app_engine, org, collection_id, " Policies ", first.id)
    with pytest.raises(NameTaken):
        await _rename(app_engine, org, collection_id, other.id, "policies")


async def test_parent_from_other_collection_is_not_found(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    first = await _collection(app_engine, org, "First")
    second = await _collection(app_engine, org, "Second")
    parent = await _folder(app_engine, org, first, "Policies")

    with pytest.raises(FolderNotFound):
        await _folder(app_engine, org, second, "Child", parent.id)
    with pytest.raises(FolderNotFound):
        await _folder(app_engine, org, first, "Child", uuid.uuid4())
    with pytest.raises(FolderNotFound):
        await _rename(app_engine, org, second, parent.id, "Other")
    with pytest.raises(FolderNotFound):
        await _delete(app_engine, org, second, parent.id)


async def test_folder_of_other_workspace_collection_is_not_found(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    in_y = await _collection(app_engine, org, "Elsewhere", workspace="y")

    async def listing(conn: Any, tenant: Any, access: Any) -> list[FolderRow]:
        return await folders.list_folders(conn, tenant, access, in_y)

    with pytest.raises(CollectionNotFound):
        await _folder(app_engine, org, in_y, "Policies")
    with pytest.raises(CollectionNotFound):
        await run_as(app_engine, org, "ke", listing)
    with pytest.raises(CollectionNotFound):
        await _folder(app_engine, org, uuid.uuid4(), "Policies")


async def test_delete_with_children_is_refused(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)
    parent = await _folder(app_engine, org, collection_id, "Policies")
    child = await _folder(app_engine, org, collection_id, "2026", parent.id)

    with pytest.raises(FolderNotEmpty):
        await _delete(app_engine, org, collection_id, parent.id)
    await _delete(app_engine, org, collection_id, child.id)
    await _delete(app_engine, org, collection_id, parent.id)


async def test_folder_with_documents_cannot_be_deleted(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)
    folder = await _folder(app_engine, org, collection_id, "Policies")
    document_id = await add_document(app_engine, org, collection_id, folder.id)

    with pytest.raises(FolderNotEmpty):
        await _delete(app_engine, org, collection_id, folder.id)
    await in_tenant(
        app_engine,
        org.org_id,
        "DELETE FROM documents WHERE org_id = :org AND id = :id",
        {"id": document_id},
    )
    await _delete(app_engine, org, collection_id, folder.id)

    assert len(await _audit(app_engine, org, folder.id)) == 2


async def test_folder_document_count(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)
    parent = await _folder(app_engine, org, collection_id, "Policies")
    child = await _folder(app_engine, org, collection_id, "2026", parent.id)
    await add_document(app_engine, org, collection_id, parent.id)
    await add_document(app_engine, org, collection_id, parent.id, "ready")
    await add_document(app_engine, org, collection_id, child.id, "failed")

    async def work(conn: Any, tenant: Any, access: Any) -> list[FolderRow]:
        return await folders.list_folders(conn, tenant, access, collection_id)

    listed = await run_as(app_engine, org, "ke", work)
    renamed = await _rename(app_engine, org, collection_id, parent.id, "Rules")

    assert {row.name: row.document_count for row in listed} == {"Policies": 2, "2026": 1}
    assert renamed.document_count == 2
    assert child.document_count == 0


async def test_rename_and_delete_are_audited(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)
    folder = await _folder(app_engine, org, collection_id, "Policies")

    renamed = await _rename(app_engine, org, collection_id, folder.id, "  Rules ")
    await _rename(app_engine, org, collection_id, folder.id, "Rules")
    await _delete(app_engine, org, collection_id, folder.id)

    assert (renamed.id, renamed.name, renamed.depth) == (folder.id, "Rules", 1)
    assert [row[:5] for row in await _audit(app_engine, org, folder.id)] == [
        ("folder.created", "folder", None, None, org.workspace("x")),
        ("folder.renamed", "folder", None, None, org.workspace("x")),
        ("folder.deleted", "folder", None, None, org.workspace("x")),
    ]
    with pytest.raises(FolderNotFound):
        await _rename(app_engine, org, collection_id, folder.id, "Again")


async def test_viewer_is_denied(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    collection_id = await _collection(app_engine, org)
    folder = await _folder(app_engine, org, collection_id, "Policies")

    async def create(conn: Any, tenant: Any, access: Any) -> object:
        return await folders.create_folder(
            conn, tenant, access, collection_id, name="New", parent_id=None
        )

    async def rename(conn: Any, tenant: Any, access: Any) -> object:
        return await folders.rename_folder(
            conn, tenant, access, collection_id, folder.id, name="New"
        )

    async def delete(conn: Any, tenant: Any, access: Any) -> None:
        await folders.delete_folder(conn, tenant, access, collection_id, folder.id)

    async def listing(conn: Any, tenant: Any, access: Any) -> object:
        return await folders.list_folders(conn, tenant, access, collection_id)

    for work in (create, rename, delete, listing):
        with pytest.raises(PermissionDenied):
            await run_as(app_engine, org, "viewer", work)
    assert len(await _audit(app_engine, org, folder.id)) == 1
