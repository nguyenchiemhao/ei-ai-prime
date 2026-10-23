"""The collection service: access rules, permission split, audit and tenant scoping. The functions
are called directly (no route), so a removed ``ensure`` cannot hide behind a route dependency."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge import service
from ei_ai.knowledge.documents import delete_originals
from ei_ai.knowledge.errors import (
    CollectionNotFound,
    GroupsRequired,
    InvalidGroup,
    InvalidKnowledgeInput,
    NameTaken,
)
from ei_ai.knowledge.rows import (
    CollectionRow,
    DocumentCounts,
    document_counts,
    insert_collection,
)
from ei_ai.rbac.access import PermissionDenied
from ei_ai.tenancy.context import TenantContext
from support.rbac.orgs import RoleOrg
from support.sign_in import in_tenant

from .conftest import MakeOrg, add_document, file_store, run_as

pytestmark = pytest.mark.integration

SECRET_NAME = "Quỹ lương qa"
SECRET_GROUP = "managers"


async def _create(engine: AsyncEngine, org: RoleOrg, actor: str, **overrides: Any) -> CollectionRow:
    values: dict[str, Any] = {
        "name": "Employee Handbook",
        "subtitle": None,
        "access_level": "authenticated",
        "groups": [],
        "local_only": False,
    } | overrides

    async def work(conn: Any, tenant: Any, access: Any) -> CollectionRow:
        return await service.create_collection(conn, tenant, access, **values)

    return await run_as(engine, org, actor, work)  # type: ignore[no-any-return]


async def _audit(engine: AsyncEngine, org: RoleOrg, collection_id: uuid.UUID) -> list[Any]:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT action, target_type, old_value, new_value, workspace_id, actor FROM audit_events"
        " WHERE org_id = :org AND target_id = :id ORDER BY created_at, id",
        {"id": collection_id},
    )
    return [tuple(row) for row in rows]


async def _row(engine: AsyncEngine, org: RoleOrg, collection_id: uuid.UUID) -> tuple[Any, ...]:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT name, subtitle, access_level, groups, local_only, updated_at FROM collections"
        " WHERE org_id = :org AND id = :id",
        {"id": collection_id},
    )
    return tuple(rows[0])


async def _change_access(
    engine: AsyncEngine,
    org: RoleOrg,
    actor: str,
    collection_id: uuid.UUID,
    level: str,
    groups: list[str],
) -> CollectionRow:
    async def work(conn: Any, tenant: Any, access: Any) -> CollectionRow:
        return await service.change_access(
            conn, tenant, access, collection_id, access_level=level, groups=groups
        )

    return await run_as(engine, org, actor, work)  # type: ignore[no-any-return]


async def _update(
    engine: AsyncEngine, org: RoleOrg, actor: str, collection_id: uuid.UUID, changes: dict[str, Any]
) -> CollectionRow:
    async def work(conn: Any, tenant: Any, access: Any) -> CollectionRow:
        return await service.update_collection(conn, tenant, access, collection_id, changes)

    return await run_as(engine, org, actor, work)  # type: ignore[no-any-return]


async def test_create_authenticated_collection(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    row = await _create(app_engine, org, "ke", name="  Employee Handbook ", subtitle="  ")

    assert (row.name, row.subtitle, row.access_level, row.groups, row.local_only) == (
        "Employee Handbook",
        None,
        "authenticated",
        (),
        False,
    )
    assert row.workspace_id == org.workspace("x")
    assert await _audit(app_engine, org, row.id) == [
        (
            "collection.created",
            "collection",
            None,
            "authenticated",
            org.workspace("x"),
            f"user:{org.user('ke')}",
        )
    ]


async def test_restricted_without_groups_is_rejected(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    with pytest.raises(GroupsRequired):
        await _create(app_engine, org, "ke", access_level="restricted", groups=[])
    with pytest.raises(InvalidGroup):
        await _create(app_engine, org, "ke", access_level="restricted", groups=["a,b"])
    with pytest.raises(InvalidKnowledgeInput):
        await _create(app_engine, org, "ke", access_level="authenticated", groups=["a"])
    with pytest.raises(InvalidKnowledgeInput):
        await _create(app_engine, org, "ke", name="   ")
    with pytest.raises(InvalidKnowledgeInput):
        await _create(app_engine, org, "ke", subtitle="s" * 201)
    with pytest.raises(InvalidKnowledgeInput):
        await _create(app_engine, org, "ke", access_level="secret")


async def test_restricted_stores_normalised_groups(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    row = await _create(
        app_engine, org, "ke", access_level="restricted", groups=[" Managers ", "HR", "managers"]
    )

    assert row.groups == ("managers", "hr")


async def test_ke_cannot_create_public(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    with pytest.raises(PermissionDenied):
        await _create(app_engine, org, "ke", access_level="public")

    rows = await in_tenant(
        app_engine, org.org_id, "SELECT count(*) FROM collections WHERE org_id = :org"
    )
    events = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT count(*) FROM audit_events WHERE org_id = :org AND action = 'collection.created'",
    )
    assert (rows[0][0], events[0][0]) == (0, 0)


async def test_viewer_cannot_use_the_service(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ws_admin")

    async def lists(conn: Any, tenant: Any, access: Any) -> object:
        return await service.list_collections(conn, tenant, access)

    for work in (
        lists,
        _call(service.get_collection, row.id),
        _call(service.delete_collection, row.id),
    ):
        with pytest.raises(PermissionDenied):
            await run_as(app_engine, org, "viewer", work)
    with pytest.raises(PermissionDenied):
        await _create(app_engine, org, "viewer", name="Other")
    with pytest.raises(PermissionDenied):
        await _update(app_engine, org, "viewer", row.id, {"name": "Other"})
    assert (await _row(app_engine, org, row.id))[0] == "Employee Handbook"


async def test_admin_creates_public(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    row = await _create(app_engine, org, "ws_admin", access_level="public")

    assert row.access_level == "public"
    assert (await _audit(app_engine, org, row.id))[0][2:4] == (None, "public")


async def test_admin_changes_access_and_audits_old_new(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ws_admin", access_level="public")

    changed = await _change_access(app_engine, org, "ws_admin", row.id, "restricted", ["Managers"])

    assert (changed.access_level, changed.groups) == ("restricted", ("managers",))
    created, access_changed = await _audit(app_engine, org, row.id)
    assert created[:5] == ("collection.created", "collection", None, "public", org.workspace("x"))
    assert access_changed == (
        "collection.access_changed",
        "collection",
        "public",
        "restricted",
        org.workspace("x"),
        f"user:{org.user('ws_admin')}",
    )


async def test_ke_cannot_change_access(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ws_admin", access_level="public")
    before = await _row(app_engine, org, row.id)

    with pytest.raises(PermissionDenied):
        await _change_access(app_engine, org, "ke", row.id, "restricted", ["managers"])

    assert await _row(app_engine, org, row.id) == before
    assert len(await _audit(app_engine, org, row.id)) == 1


async def test_make_public_is_audited(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke")

    await _change_access(app_engine, org, "ws_admin", row.id, "public", [])

    last = (await _audit(app_engine, org, row.id))[-1]
    assert last[:4] == ("collection.access_changed", "collection", "authenticated", "public")


async def test_groups_only_change_audits_groups_changed(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke", access_level="restricted", groups=["managers"])

    changed = await _change_access(
        app_engine, org, "ws_admin", row.id, "restricted", ["managers", "HR"]
    )

    assert changed.groups == ("managers", "hr")
    last = (await _audit(app_engine, org, row.id))[-1]
    assert last[:4] == ("collection.groups_changed", "collection", "restricted", "restricted")


async def test_same_access_writes_no_event(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke", access_level="restricted", groups=["managers"])
    before = await _row(app_engine, org, row.id)

    again = await _change_access(app_engine, org, "ws_admin", row.id, "restricted", [" MANAGERS"])
    auth = await _create(app_engine, org, "ke", name="Other")
    await _change_access(app_engine, org, "ws_admin", auth.id, "authenticated", [])

    assert again.groups == ("managers",)
    assert await _row(app_engine, org, row.id) == before
    assert len(await _audit(app_engine, org, row.id)) == 1
    assert len(await _audit(app_engine, org, auth.id)) == 1


async def test_access_input_errors_leave_the_row(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke")

    with pytest.raises(GroupsRequired):
        await _change_access(app_engine, org, "ws_admin", row.id, "restricted", [])
    with pytest.raises(InvalidKnowledgeInput):
        await _change_access(app_engine, org, "ws_admin", row.id, "public", ["a"])
    with pytest.raises(InvalidGroup):
        await _change_access(app_engine, org, "ws_admin", row.id, "restricted", ["a,b"])

    assert (await _row(app_engine, org, row.id))[2] == "authenticated"
    assert len(await _audit(app_engine, org, row.id)) == 1


async def test_update_name_and_subtitle_audits_updated(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke", subtitle="Old")

    changed = await _update(app_engine, org, "ke", row.id, {"name": " New name ", "subtitle": ""})
    same = await _update(app_engine, org, "ke", row.id, {"name": "new NAME"})

    assert (changed.name, changed.subtitle) == ("New name", None)
    assert same.name == "new NAME"
    events = [event_[0] for event_ in await _audit(app_engine, org, row.id)]
    assert events == ["collection.created", "collection.updated", "collection.updated"]
    last = (await _audit(app_engine, org, row.id))[-1]
    assert last[2:4] == (None, None)

    await _update(app_engine, org, "ke", row.id, {"name": "new NAME", "subtitle": None})
    assert len(await _audit(app_engine, org, row.id)) == 3


async def test_update_rejects_unknown_keys_and_bad_values(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke")

    for changes in ({"access_level": "public"}, {"name": ""}, {"local_only": "yes"}, {"name": 3}):
        with pytest.raises(InvalidKnowledgeInput):
            await _update(app_engine, org, "ke", row.id, changes)


async def test_local_only_on_by_ke_off_by_admin(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke")

    on = await _update(app_engine, org, "ke", row.id, {"local_only": True})
    before = await _row(app_engine, org, row.id)
    with pytest.raises(PermissionDenied):
        await _update(app_engine, org, "ke", row.id, {"local_only": False})
    after_denied = await _row(app_engine, org, row.id)
    audit_after_denied = await _audit(app_engine, org, row.id)
    off = await _update(app_engine, org, "ws_admin", row.id, {"local_only": False})

    assert on.local_only is True
    assert after_denied == before
    assert [event_[0] for event_ in audit_after_denied] == [
        "collection.created",
        "collection.local_only_changed",
    ]
    assert audit_after_denied[1][2:4] == ("any_model", "local_only")
    assert off.local_only is False
    assert (await _audit(app_engine, org, row.id))[-1][2:4] == ("local_only", "any_model")


async def test_name_taken_case_insensitive(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    first = await _create(app_engine, org, "ke", name="Employee Handbook")
    second = await _create(app_engine, org, "ke", name="Other")

    with pytest.raises(NameTaken):
        await _create(app_engine, org, "ke", name="employee handbook")
    with pytest.raises(NameTaken):
        await _update(app_engine, org, "ke", second.id, {"name": "EMPLOYEE HANDBOOK"})
    same_name_elsewhere = await _create_in(app_engine, org, "ws_admin", "y", "Employee Handbook")

    assert first.name == "Employee Handbook"
    assert same_name_elsewhere.workspace_id == org.workspace("y")


async def test_name_taken_in_one_transaction_keeps_it_usable(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    await _create(app_engine, org, "ke", name="Taken")

    async def work(conn: Any, tenant: Any, access: Any) -> int:
        with pytest.raises(NameTaken):
            await service.create_collection(
                conn,
                tenant,
                access,
                name="TAKEN",
                subtitle=None,
                access_level="authenticated",
                groups=[],
                local_only=False,
            )
        return len(await service.list_collections(conn, tenant, access))

    assert await run_as(app_engine, org, "ke", work) == 1


async def test_other_workspace_collection_is_not_found(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    other_org = await make_org()
    in_y = await _create_in(app_engine, org, "ws_admin", "y", "In workspace y")
    foreign = await _create(app_engine, other_org, "ws_admin")
    before = await _row(app_engine, org, in_y.id)

    for target in (in_y.id, foreign.id, uuid.uuid4()):
        with pytest.raises(CollectionNotFound):
            await run_as(app_engine, org, "ws_admin", _call(service.get_collection, target))
        with pytest.raises(CollectionNotFound):
            await run_as(app_engine, org, "ws_admin", _call(service.delete_collection, target))
        with pytest.raises(CollectionNotFound):
            await _update(app_engine, org, "ws_admin", target, {"name": "Hijacked"})
        with pytest.raises(CollectionNotFound):
            await _change_access(app_engine, org, "ws_admin", target, "public", [])

    assert await _row(app_engine, org, in_y.id) == before
    assert len(await _audit(app_engine, org, in_y.id)) == 1


def _call(function: Any, target: uuid.UUID) -> Any:
    """A ``run_as`` work function calling a service function on ``target``."""

    async def work(conn: Any, tenant: Any, access: Any) -> Any:
        return await function(conn, tenant, access, target)

    return work


async def _create_in(
    engine: AsyncEngine, org: RoleOrg, actor: str, workspace: str, name: str
) -> CollectionRow:
    async def work(conn: Any, tenant: Any, access: Any) -> CollectionRow:
        return await service.create_collection(
            conn,
            tenant,
            access,
            name=name,
            subtitle=None,
            access_level="authenticated",
            groups=[],
            local_only=False,
        )

    return await run_as(engine, org, actor, work, workspace)  # type: ignore[no-any-return]


async def test_delete_removes_collection_and_folders(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke", access_level="restricted", groups=["managers"])
    parent, child = uuid.uuid4(), uuid.uuid4()
    await in_tenant(
        app_engine,
        org.org_id,
        "INSERT INTO folders (id, org_id, collection_id, parent_id, name, depth)"
        " VALUES (:parent, :org, :c, NULL, 'Policies', 1), (:child, :org, :c, :parent, '2026', 2)",
        {"parent": parent, "child": child, "c": row.id},
    )

    async def work(conn: Any, tenant: Any, access: Any) -> None:
        await service.delete_collection(conn, tenant, access, row.id)

    await run_as(app_engine, org, "ke", work)

    counts = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT (SELECT count(*) FROM collections WHERE org_id = :org),"
        " (SELECT count(*) FROM folders WHERE org_id = :org)",
    )
    assert tuple(counts[0]) == (0, 0)
    assert (await _audit(app_engine, org, row.id))[-1][:4] == (
        "collection.deleted",
        "collection",
        "restricted",
        None,
    )


async def test_audit_values_are_codes_only(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    row = await _create(
        app_engine,
        org,
        "ws_admin",
        name=SECRET_NAME,
        subtitle=SECRET_NAME,
        access_level="restricted",
        groups=[SECRET_GROUP],
    )
    await _update(app_engine, org, "ws_admin", row.id, {"name": SECRET_NAME + " 2"})
    await _update(app_engine, org, "ws_admin", row.id, {"local_only": True})
    await _change_access(app_engine, org, "ws_admin", row.id, "restricted", [SECRET_GROUP, "hr"])
    await _change_access(app_engine, org, "ws_admin", row.id, "public", [])

    rows = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT a::text FROM audit_events a WHERE org_id = :org AND target_id = :id",
        {"id": row.id},
    )

    assert len(rows) == 5
    dump = " ".join(str(item[0]) for item in rows).lower()
    assert "quỹ" not in dump and SECRET_GROUP not in dump
    values = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT old_value, new_value FROM audit_events WHERE org_id = :org AND target_id = :id",
        {"id": row.id},
    )
    assert all(value is None or _is_code(value) for pair in values for value in pair)


def _is_code(value: str) -> bool:
    return 1 <= len(value) <= 40 and all(char.islower() or char == "_" for char in value)


async def test_list_uses_one_query_for_100_collections(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    tenant_ws = org.workspace("x")

    async def seed(conn: Any, tenant: Any, access: Any) -> None:
        for number in range(100):
            await insert_collection(
                conn,
                org.org_id,
                tenant_ws,
                name=f"{'b' if number % 2 else 'A'}-collection {number:03d}",
                subtitle=None,
                access_level="restricted" if number % 3 == 0 else "authenticated",
                groups=["managers"] if number % 3 == 0 else [],
                local_only=False,
            )

    await run_as(app_engine, org, "ws_admin", seed)
    statements: list[str] = []

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    async def work(conn: Any, tenant: Any, access: Any) -> list[CollectionRow]:
        listener = app_engine.sync_engine
        event.listen(listener, "before_cursor_execute", count)
        try:
            return await service.list_collections(conn, tenant, access)
        finally:
            event.remove(listener, "before_cursor_execute", count)

    rows = await run_as(app_engine, org, "ke", work)

    assert len(rows) == 100
    assert len(statements) == 1
    names = [row.name.lower() for row in rows]
    assert names == sorted(names)
    assert rows[0].name.startswith("A-") and rows[-1].name.startswith("b-")


async def test_collection_delete_removes_documents_chunks_and_files(
    app_engine: AsyncEngine, make_org: MakeOrg, tmp_path: Path
) -> None:
    org = await make_org()
    row = await _create(app_engine, org, "ke")
    folder = uuid.uuid4()
    await in_tenant(
        app_engine,
        org.org_id,
        "INSERT INTO folders (id, org_id, collection_id, name, depth)"
        " VALUES (:folder, :org, :c, 'Policies', 1)",
        {"folder": folder, "c": row.id},
    )
    tenant = TenantContext(org_id=org.org_id, user_id=org.user("ke"))
    storage = file_store(tmp_path)
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        file_ids = [await storage.put(conn, tenant, b"data") for _ in range(2)]
    first = await add_document(app_engine, org, row.id, folder, "ready", file_ids[0])
    await add_document(app_engine, org, row.id, folder, file_id=file_ids[1])
    await in_tenant(
        app_engine,
        org.org_id,
        "INSERT INTO document_chunks (org_id, document_id, ordinal, text, char_start, char_end,"
        " token_estimate) VALUES (:org, :d, 0, 'qa', 0, 2, 1)",
        {"d": first},
    )

    async def work(conn: Any, tenant: Any, access: Any) -> list[uuid.UUID]:
        return await service.delete_collection(conn, tenant, access, row.id)

    deleted = await run_as(app_engine, org, "ke", work)
    await delete_originals(storage, tenant, deleted)

    assert sorted(deleted) == sorted(file_ids)
    counts = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT (SELECT count(*) FROM documents WHERE org_id = :org),"
        " (SELECT count(*) FROM document_chunks WHERE org_id = :org)",
    )
    assert tuple(counts[0]) == (0, 0)
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


async def test_collection_summary_counts(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    busy = await _create(app_engine, org, "ke", name="Busy")
    empty = await _create(app_engine, org, "ke", name="Empty")
    folder = uuid.uuid4()
    await in_tenant(
        app_engine,
        org.org_id,
        "INSERT INTO folders (id, org_id, collection_id, name, depth)"
        " VALUES (:folder, :org, :c, 'Policies', 1)",
        {"folder": folder, "c": busy.id},
    )
    for status in ("queued", "queued", "ready", "failed", "not_supported", "ready", "ready"):
        await add_document(app_engine, org, busy.id, folder, status)

    async def work(conn: Any, tenant: Any, access: Any) -> dict[uuid.UUID, DocumentCounts]:
        return await document_counts(conn, tenant.org_id, [busy.id, empty.id])

    counts = await run_as(app_engine, org, "ke", work)

    assert counts == {busy.id: DocumentCounts(total=7, ready=3, processing=2, needs_attention=2)}
