"""Migration 0007 (EA-32): ``collections``, ``folders`` and the audit target types.

Each case runs as the application role in a tenant transaction; a failing statement rolls back.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration


async def _insert_collection(engine: AsyncEngine, rows: OrgRows, **overrides: Any) -> uuid.UUID:
    """Insert a collection in the fixture Workspace of ``rows``; returns its id."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "org": rows.org_id,
        "ws": rows.workspace_id,
        "name": f"Handbook {uuid.uuid4().hex[:8]}",
        "level": "authenticated",
        "groups": [],
    }
    values.update(overrides)
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "INSERT INTO collections (id, org_id, workspace_id, name, access_level, groups)"
                " VALUES (:id, :org, :ws, :name, :level, :groups)"
            ),
            values,
        )
    collection_id: uuid.UUID = values["id"]
    return collection_id


async def _insert_folder(
    engine: AsyncEngine,
    rows: OrgRows,
    collection_id: uuid.UUID,
    *,
    parent_id: uuid.UUID | None = None,
    depth: int = 1,
    name: str = "Policies",
) -> uuid.UUID:
    """Insert a folder under ``collection_id``; returns its id."""
    folder_id = uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        await conn.execute(
            text(
                "INSERT INTO folders (id, org_id, collection_id, parent_id, name, depth)"
                " VALUES (:id, :org, :collection, :parent, :name, :depth)"
            ),
            {
                "id": folder_id,
                "org": rows.org_id,
                "collection": collection_id,
                "parent": parent_id,
                "name": name,
                "depth": depth,
            },
        )
    return folder_id


async def _count(engine: AsyncEngine, org: uuid.UUID, table: str, row_id: uuid.UUID) -> int:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        sql = f"SELECT count(*) FROM {table} WHERE org_id = :org AND id = :id"
        total: int = (await conn.execute(text(sql), {"org": org, "id": row_id})).scalar_one()
        return total


async def test_restricted_requires_a_group(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    with pytest.raises(IntegrityError):
        await _insert_collection(app_engine, two_orgs.a, level="restricted", groups=[])


async def test_public_rejects_groups(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    with pytest.raises(IntegrityError):
        await _insert_collection(app_engine, two_orgs.a, level="public", groups=["managers"])


async def test_restricted_with_a_group_is_accepted(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    collection_id = await _insert_collection(
        app_engine, two_orgs.a, level="restricted", groups=["managers"]
    )

    assert await _count(app_engine, two_orgs.a.org_id, "collections", collection_id) == 1


async def test_more_than_20_groups_rejected(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    groups = [f"group-{index}" for index in range(21)]

    with pytest.raises(IntegrityError):
        await _insert_collection(app_engine, two_orgs.a, level="restricted", groups=groups)


@pytest.mark.parametrize("name", ["", "x" * 201])
async def test_collection_name_length_is_checked(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, name: str
) -> None:
    with pytest.raises(IntegrityError):
        await _insert_collection(app_engine, two_orgs.a, name=name)


async def test_unknown_access_level_rejected(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    with pytest.raises(IntegrityError):
        await _insert_collection(app_engine, two_orgs.a, level="everyone")


async def test_depth_above_3_rejected(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    collection_id = await _insert_collection(app_engine, two_orgs.a)

    with pytest.raises(IntegrityError):
        await _insert_folder(app_engine, two_orgs.a, collection_id, depth=4)


async def test_parent_must_be_in_same_collection(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    first = await _insert_collection(app_engine, two_orgs.a)
    second = await _insert_collection(app_engine, two_orgs.a)
    parent = await _insert_folder(app_engine, two_orgs.a, first)

    with pytest.raises(IntegrityError):
        await _insert_folder(app_engine, two_orgs.a, second, parent_id=parent, depth=2)


async def test_collection_delete_cascades_folders(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    collection_id = await _insert_collection(app_engine, a)
    parent = await _insert_folder(app_engine, a, collection_id)
    child = await _insert_folder(app_engine, a, collection_id, parent_id=parent, depth=2)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text("DELETE FROM collections WHERE org_id = :org AND id = :id"),
            {"org": a.org_id, "id": collection_id},
        )

    assert await _count(app_engine, a.org_id, "folders", parent) == 0
    assert await _count(app_engine, a.org_id, "folders", child) == 0


async def test_parent_delete_cascades_subfolders(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    collection_id = await _insert_collection(app_engine, a)
    parent = await _insert_folder(app_engine, a, collection_id)
    child = await _insert_folder(app_engine, a, collection_id, parent_id=parent, depth=2)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text("DELETE FROM folders WHERE org_id = :org AND id = :id"),
            {"org": a.org_id, "id": parent},
        )

    assert await _count(app_engine, a.org_id, "folders", child) == 0


async def test_names_unique_case_insensitive_per_workspace(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    await _insert_collection(app_engine, two_orgs.a, name="Employee Handbook")

    with pytest.raises(IntegrityError) as error:
        await _insert_collection(app_engine, two_orgs.a, name="employee handbook")

    assert "collections_workspace_name_key" in str(error.value.orig)


async def test_same_name_is_allowed_in_another_workspace(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    other_ws = uuid.uuid4()
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text("INSERT INTO workspaces (id, org_id, name) VALUES (:id, :org, 'Second')"),
            {"id": other_ws, "org": a.org_id},
        )
    await _insert_collection(app_engine, a, name="Employee Handbook")

    other_id = await _insert_collection(app_engine, a, name="employee handbook", ws=other_ws)

    assert await _count(app_engine, a.org_id, "collections", other_id) == 1


async def test_sibling_folder_names_unique_case_insensitive(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    collection_id = await _insert_collection(app_engine, a)
    await _insert_folder(app_engine, a, collection_id, name="Policies")

    with pytest.raises(IntegrityError) as error:
        await _insert_folder(app_engine, a, collection_id, name="policies")

    assert "folders_sibling_name_key" in str(error.value.orig)


async def test_same_folder_name_under_different_parents_is_allowed(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    collection_id = await _insert_collection(app_engine, a)
    first = await _insert_folder(app_engine, a, collection_id, name="Policies")
    second = await _insert_folder(app_engine, a, collection_id, name="Guides")

    await _insert_folder(app_engine, a, collection_id, parent_id=first, depth=2, name="2026")
    await _insert_folder(app_engine, a, collection_id, parent_id=second, depth=2, name="2026")


@pytest.mark.parametrize("target_type", ["collection", "folder"])
async def test_audit_accepts_collection_and_folder_targets(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, target_type: str
) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text(
                "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
                " VALUES (:org, 'platform-operator', :action, :target_type, :id)"
            ),
            {
                "org": a.org_id,
                "action": f"{target_type}.created",
                "target_type": target_type,
                "id": uuid.uuid4(),
            },
        )


async def test_audit_still_rejects_unknown_target_type(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a

    with pytest.raises(IntegrityError):
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
                    " VALUES (:org, 'platform-operator', 'x.created', 'assistant', :id)"
                ),
                {"org": a.org_id, "id": uuid.uuid4()},
            )
