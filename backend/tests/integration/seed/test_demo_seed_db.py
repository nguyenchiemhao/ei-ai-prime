"""``seed demo`` against the real database (FND-04 AC3, AC4; EA-94 AC2-AC5).

Variants of the manifests use random Organization ids, suffixed names and their own email
domains and are purged afterwards; the real demo Organizations are left in place (CI seeds them
before these tests).
"""

import uuid
from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import (
    COLLECTION_CREATED,
    ORGANIZATION_CREATED,
    PLATFORM_OPERATOR,
    USER_INVITED,
    WORKSPACE_CREATED,
    record_event,
)
from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.groups import normalise_groups
from ei_ai.knowledge.rows import insert_collection
from ei_ai.members.rows import insert_member
from ei_ai.provisioning.rows import insert_organization, insert_workspace
from ei_ai.provisioning.validation import ProvisioningError
from ei_ai.seed.demo import DemoManifest, SeedResult, seed_manifest
from ei_ai.seed.manifest import SeedFolder, load_manifests
from support.crypto import TEST_MASTER_KEY
from support.seed import TEST_SEED_PASSWORD, demo_seed_password
from support.sign_in import in_tenant
from support.tenants import (
    DELETE_ORDER,
    TwoOrgs,
    count_org_rows,
    tenant_key_column,
)

pytestmark = pytest.mark.integration

MEKONG_COUNTS = {
    "chunk_embeddings": 0,
    "document_chunks": 0,
    "documents": 0,
    "folders": 33,
    "collections": 8,
    "admin_sessions": 0,
    "user_credentials": 10,
    "audit_events": 78,
    "set_password_tokens": 0,
    "workspace_memberships": 11,
    "memberships": 10,
    "workspaces": 2,
    "users": 10,
    # The three platform models of the manifest (EA-24); the seed writes no audit event for them.
    "model_catalog": 3,
    "organization_keys": 1,
    "organizations": 1,
}
SONG_HAN_COUNTS = {
    "chunk_embeddings": 0,
    "document_chunks": 0,
    "documents": 0,
    "folders": 3,
    "collections": 1,
    "admin_sessions": 0,
    "user_credentials": 1,
    "audit_events": 13,
    "set_password_tokens": 0,
    "workspace_memberships": 2,
    "memberships": 2,
    "workspaces": 1,
    "users": 2,
    "model_catalog": 3,
    "organization_keys": 1,
    "organizations": 1,
}
MEKONG_ACTIONS = {
    "organization.created": 1,
    "workspace.created": 2,
    "user.invited": 10,
    "member.org_role_changed": 3,
    "member.workspace_role_changed": 11,
    "user.password_set": 10,
    "collection.created": 8,
    "folder.created": 33,
}
SONG_HAN_ACTIONS = {
    "organization.created": 1,
    "workspace.created": 1,
    "user.invited": 2,
    "member.org_role_changed": 2,
    "member.workspace_role_changed": 2,
    "user.password_set": 1,
    "collection.created": 1,
    "folder.created": 3,
}


async def _all_rows(engine: AsyncEngine, org_id: uuid.UUID) -> dict[str, list[tuple[object, ...]]]:
    rows = {}
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        for table in DELETE_ORDER:
            sql = f"SELECT * FROM {table} WHERE {tenant_key_column(table)} = :org ORDER BY id"
            rows[table] = [tuple(r) for r in await conn.execute(text(sql), {"org": org_id})]
    return rows


async def _actions(engine: AsyncEngine, org_id: uuid.UUID) -> Counter[str]:
    rows = await in_tenant(
        engine, org_id, "SELECT actor, action FROM audit_events WHERE org_id = :org"
    )
    assert {row.actor for row in rows} <= {PLATFORM_OPERATOR}
    return Counter(row.action for row in rows)


async def _folder_paths(engine: AsyncEngine, org_id: uuid.UUID) -> set[tuple[str, str, int]]:
    """(collection, folder path joined by "/", depth) of every folder of the Organization."""
    rows = await in_tenant(
        engine,
        org_id,
        "SELECT f.id, f.parent_id, f.name, f.depth, c.name AS collection FROM folders f"
        " JOIN collections c ON c.org_id = f.org_id AND c.id = f.collection_id"
        " WHERE f.org_id = :org",
    )
    by_id = {row.id: row for row in rows}

    def path(row: object) -> str:
        parent = by_id.get(row.parent_id)  # type: ignore[attr-defined]
        name: str = row.name  # type: ignore[attr-defined]
        return name if parent is None else f"{path(parent)}/{name}"

    return {(row.collection, path(row), row.depth) for row in rows}


def _manifest_paths(
    collection: str, folders: list[SeedFolder], prefix: str = ""
) -> set[tuple[str, str, int]]:
    paths: set[tuple[str, str, int]] = set()
    for folder in folders:
        path = f"{prefix}{folder.name}"
        paths.add((collection, path, path.count("/") + 1))
        paths |= _manifest_paths(collection, folder.folders, f"{path}/")
    return paths


def _expected_paths(manifest: DemoManifest) -> set[tuple[str, str, int]]:
    return {
        path
        for workspace in manifest.workspaces
        for collection in workspace.collections
        for path in _manifest_paths(collection.name, collection.folders)
    }


async def _seed_all(engine: AsyncEngine, manifests: tuple[DemoManifest, ...]) -> list[SeedResult]:
    return [
        await seed_manifest(engine, m, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
        for m in manifests
    ]


async def test_fresh_seed_writes_the_expected_rows_and_events(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong, song_han = variants

    first, second = await _seed_all(app_engine, variants)

    assert await count_org_rows(app_engine, mekong.organization_id) == MEKONG_COUNTS
    assert await count_org_rows(app_engine, song_han.organization_id) == SONG_HAN_COUNTS
    assert await _actions(app_engine, mekong.organization_id) == MEKONG_ACTIONS
    assert await _actions(app_engine, song_han.organization_id) == SONG_HAN_ACTIONS
    assert first.organization_created
    assert [(name, created) for name, _, created in first.workspaces] == [
        ("People Ops", True),
        ("Engineering", True),
    ]
    assert first.members_created == (True,) * 10
    assert (first.collections_created, first.folders_created) == (8, 33)
    assert (first.passwords_applied, first.audit_events) == (10, 78)
    assert (second.collections_created, second.folders_created) == (1, 3)
    assert (second.passwords_applied, second.audit_events) == (1, 13)


async def test_seeded_roles_match_the_manifest(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    result = (await _seed_all(app_engine, variants[:1]))[0]
    names = {ws_id: name for name, ws_id, _ in result.workspaces}
    rows = await in_tenant(
        app_engine,
        mekong.organization_id,
        "SELECT u.email, u.display_name, m.org_role, w.workspace_id, w.role FROM users u"
        " JOIN memberships m ON m.org_id = u.org_id AND m.user_id = u.id"
        " LEFT JOIN workspace_memberships w ON w.org_id = u.org_id AND w.user_id = u.id"
        " WHERE u.org_id = :org",
    )

    seeded: dict[tuple[str, str, str | None], dict[str, str]] = {}
    for row in rows:
        roles = seeded.setdefault((row.email, row.display_name, row.org_role), {})
        if row.workspace_id is not None:
            roles[names[row.workspace_id]] = row.role
    assert seeded == {
        (member.email, member.name, member.org_role): member.workspaces for member in mekong.members
    }


async def test_second_run_writes_nothing(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    first = await _seed_all(app_engine, variants)
    before = [await _all_rows(app_engine, m.organization_id) for m in variants]

    again = await _seed_all(app_engine, variants)

    assert [await _all_rows(app_engine, m.organization_id) for m in variants] == before
    for result, earlier in zip(again, first, strict=True):
        assert result.audit_events == 0
        assert not result.organization_created
        assert not any(result.members_created)
        assert (result.collections_created, result.folders_created) == (0, 0)
        assert result.passwords_applied == 0
        assert [(n, i) for n, i, _ in result.workspaces] == [
            (n, i) for n, i, _ in earlier.workspaces
        ]
        assert not any(created for _, _, created in result.workspaces)


async def test_folders_are_created_once_with_depth(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    await _seed_all(app_engine, variants[:1])
    paths = await _folder_paths(app_engine, org_id)
    await in_tenant(
        app_engine,
        org_id,
        "UPDATE folders SET name = 'Perks' WHERE org_id = :org AND name = 'Benefits'",
    )

    result = await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)

    assert paths == _expected_paths(mekong)
    assert len(paths) == 33
    assert ("Employee Handbook", "Templates/Contracts/Labor contracts", 3) in paths
    assert max(depth for _, _, depth in paths) == 3
    assert result.folders_created == 3
    assert result.audit_events == 3
    after = await _folder_paths(app_engine, org_id)
    assert after == _expected_paths(mekong) | {
        ("Employee Handbook", "Perks", 1),
        ("Employee Handbook", "Perks/Allowances", 2),
        ("Employee Handbook", "Perks/Insurance & health care", 2),
    }
    unmatched = await in_tenant(
        app_engine,
        org_id,
        "SELECT count(*) FROM audit_events e"
        " LEFT JOIN folders f ON f.org_id = e.org_id AND f.id = e.target_id"
        " LEFT JOIN collections c ON c.org_id = f.org_id AND c.id = f.collection_id"
        " WHERE e.org_id = :org AND e.action = 'folder.created'"
        " AND (e.target_type <> 'folder' OR e.workspace_id IS DISTINCT FROM c.workspace_id)",
    )
    assert unmatched[0][0] == 0


async def _seed_v2(engine: AsyncEngine, manifest: DemoManifest) -> None:
    """The rows the pre-EA-94 seed wrote: the Organization, People Ops, its six members with
    set-password tokens and its six collections without folders, with their audit events."""
    org_id = manifest.organization_id
    people_ops = manifest.workspaces[0]
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        await insert_organization(conn, org_id, manifest.organization)
        await record_event(
            conn, org_id, PLATFORM_OPERATOR, ORGANIZATION_CREATED, "organization", org_id
        )
        ws_id = await insert_workspace(conn, org_id, people_ops.name)
        await record_event(conn, org_id, PLATFORM_OPERATOR, WORKSPACE_CREATED, "workspace", ws_id)
        for member in manifest.members[:6]:
            role = member.workspaces[people_ops.name]
            user_id, _ = await insert_member(
                conn, org_id, member.email, member.name, member.org_role, (ws_id, role)
            )
            await record_event(conn, org_id, PLATFORM_OPERATOR, USER_INVITED, "user", user_id)
        for item in people_ops.collections:
            row = await insert_collection(
                conn,
                org_id,
                ws_id,
                name=item.name,
                subtitle=item.subtitle,
                access_level=item.access_level,
                groups=normalise_groups(item.groups),
                local_only=item.local_only,
            )
            await record_event(
                conn,
                org_id,
                PLATFORM_OPERATOR,
                COLLECTION_CREATED,
                "collection",
                row.id,
                workspace_id=ws_id,
                new_value=item.access_level,
            )


async def test_v2_seeded_database_is_upgraded_without_changing_rows(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    await _seed_v2(app_engine, mekong)
    before = await _all_rows(app_engine, org_id)
    actions_before = await _actions(app_engine, org_id)

    result = await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)

    after = await _all_rows(app_engine, org_id)
    for table, rows in before.items():
        assert all(row in after[table] for row in rows), f"a pre-existing {table} row changed"
    assert not result.organization_created
    assert [(name, created) for name, _, created in result.workspaces] == [
        ("People Ops", False),
        ("Engineering", True),
    ]
    assert result.members_created == (False,) * 6 + (True,) * 4
    assert (result.collections_created, result.folders_created) == (2, 33)
    assert result.passwords_applied == 10
    assert result.audit_events == 58
    assert (await _actions(app_engine, org_id)) - actions_before == {
        "workspace.created": 1,
        "user.invited": 4,
        "member.org_role_changed": 2,
        "member.workspace_role_changed": 5,
        "workspace.member_added": 1,
        "user.password_set": 10,
        "collection.created": 2,
        "folder.created": 33,
    }
    counts = await count_org_rows(app_engine, org_id)
    assert counts == {**MEKONG_COUNTS, "audit_events": 72, "set_password_tokens": 6}
    engineering = result.workspaces[1][1]
    quang = await in_tenant(
        app_engine,
        org_id,
        "SELECT w.workspace_id, w.role FROM workspace_memberships w"
        " JOIN users u ON u.org_id = w.org_id AND u.id = w.user_id"
        " WHERE w.org_id = :org AND u.email = :email",
        {"email": mekong.members[3].email},
    )
    assert {tuple(row) for row in quang} == {
        (result.workspaces[0][1], "developer"),
        (engineering, "workspace_admin"),
    }
    added = await in_tenant(
        app_engine,
        org_id,
        "SELECT e.target_id FROM audit_events e JOIN users u ON u.org_id = e.org_id"
        " AND u.id = e.target_id WHERE e.org_id = :org AND e.action = 'workspace.member_added'",
    )
    quang_id = await in_tenant(
        app_engine,
        org_id,
        "SELECT id FROM users WHERE org_id = :org AND email = :email",
        {"email": mekong.members[3].email},
    )
    assert [row[0] for row in added] == [quang_id[0][0]]


async def test_recreated_workspace_gets_the_existing_members_back(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    first = await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
    await in_tenant(
        app_engine,
        org_id,
        "UPDATE workspaces SET name = 'People Ops (renamed)' WHERE org_id = :org AND id = :ws",
        {"ws": first.workspaces[0][1]},
    )
    actions_before = await _actions(app_engine, org_id)

    result = await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)

    assert [(name, created) for name, _, created in result.workspaces] == [
        ("People Ops", True),
        ("Engineering", False),
    ]
    assert result.members_created == (False,) * 10
    recreated = result.workspaces[0][1]
    members = await in_tenant(
        app_engine,
        org_id,
        "SELECT user_id FROM workspace_memberships WHERE org_id = :org AND workspace_id = :ws",
        {"ws": recreated},
    )
    assert len(members) == 7
    assert (await _actions(app_engine, org_id)) - actions_before == {
        "workspace.created": 1,
        "workspace.member_added": 7,
        "member.workspace_role_changed": 7,
        "collection.created": 6,
        "folder.created": 28,
    }


async def test_each_org_rows_carry_only_its_org_id(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    await _seed_all(app_engine, variants)

    seen_ids: list[set[uuid.UUID]] = []
    for manifest in variants:
        org_id = manifest.organization_id
        users = await in_tenant(app_engine, org_id, "SELECT email FROM users WHERE org_id = :org")
        collections = await in_tenant(
            app_engine, org_id, "SELECT name FROM collections WHERE org_id = :org"
        )
        ids: set[uuid.UUID] = {org_id}
        for table in ("users", "workspaces", "collections", "folders"):
            rows = await in_tenant(
                app_engine, org_id, f"SELECT id FROM {table} WHERE org_id = :org"
            )
            ids |= {row[0] for row in rows}
        targets = await in_tenant(
            app_engine,
            org_id,
            "SELECT target_id, workspace_id FROM audit_events WHERE org_id = :org",
        )

        assert {row.email for row in users} == {member.email for member in manifest.members}
        assert {row.name for row in collections} == {
            c.name for workspace in manifest.workspaces for c in workspace.collections
        }
        assert {row.target_id for row in targets} <= ids
        assert {row.workspace_id for row in targets} - {None} <= ids
        seen_ids.append(ids)
    assert seen_ids[0].isdisjoint(seen_ids[1])


async def test_one_org_failure_leaves_the_other_org_untouched(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...], two_orgs: TwoOrgs
) -> None:
    mekong, song_han = variants
    taken = song_han.model_copy(update={"organization": two_orgs.a.names.organization.upper()})

    await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
    with pytest.raises(ProvisioningError) as error:
        await seed_manifest(app_engine, taken, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)

    assert str(error.value) == (
        f'an Organization named "{taken.organization}" already exists with another id'
    )
    assert await count_org_rows(app_engine, mekong.organization_id) == MEKONG_COUNTS
    assert await count_org_rows(app_engine, song_han.organization_id) == dict.fromkeys(
        DELETE_ORDER, 0
    )
    rerun = await _seed_all(app_engine, variants)
    assert [result.audit_events for result in rerun] == [0, 13]
    assert await count_org_rows(app_engine, song_han.organization_id) == SONG_HAN_COUNTS


async def test_seed_keeps_a_renamed_or_changed_collection(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
    await in_tenant(
        app_engine,
        org_id,
        "UPDATE collections SET subtitle = 'Edited', access_level = 'authenticated',"
        " groups = '{}', local_only = false, name = 'MANAGER HANDBOOK'"
        " WHERE org_id = :org AND name = 'Manager Handbook'",
    )
    await in_tenant(
        app_engine,
        org_id,
        "DELETE FROM folders WHERE org_id = :org AND collection_id IN"
        " (SELECT id FROM collections WHERE org_id = :org AND name = 'IT & Security')",
    )
    await in_tenant(
        app_engine, org_id, "DELETE FROM collections WHERE org_id = :org AND name = 'IT & Security'"
    )
    sql = (
        "SELECT name, subtitle, access_level, groups, local_only FROM collections"
        " WHERE org_id = :org ORDER BY lower(name)"
    )
    before = [tuple(row) for row in await in_tenant(app_engine, org_id, sql)]

    result = await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)

    assert result.collections_created == 1
    assert result.folders_created == 3
    assert result.audit_events == 4
    after = [tuple(row) for row in await in_tenant(app_engine, org_id, sql)]
    assert [row for row in after if row[0] != "IT & Security"] == before
    assert ("MANAGER HANDBOOK", "Edited", "authenticated", [], False) in after
    assert ("IT & Security", None, "authenticated", [], False) in after


async def test_seed_adds_only_a_missing_member(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
    son = "(SELECT id FROM users WHERE org_id = :org AND email = :email)"
    params = {"email": mekong.members[5].email}
    for table in ("user_credentials", "workspace_memberships", "memberships"):
        await in_tenant(
            app_engine,
            org_id,
            f"DELETE FROM {table} WHERE org_id = :org AND user_id IN {son}",
            params,
        )
    await in_tenant(
        app_engine, org_id, f"DELETE FROM users WHERE org_id = :org AND id IN {son}", params
    )

    result = await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)

    assert result.members_created == (False,) * 5 + (True,) + (False,) * 4
    assert result.passwords_applied == 1
    # user.invited, member.workspace_role_changed, user.password_set
    assert result.audit_events == 3
    assert (await count_org_rows(app_engine, org_id))["users"] == 10


async def test_real_manifests_are_idempotent(app_engine: AsyncEngine) -> None:
    password = demo_seed_password()
    for manifest in load_manifests():
        await seed_manifest(app_engine, manifest, password, master=TEST_MASTER_KEY)
        after_first = await _all_rows(app_engine, manifest.organization_id)
        second = await seed_manifest(app_engine, manifest, password, master=TEST_MASTER_KEY)

        assert second.audit_events == 0
        assert await _all_rows(app_engine, manifest.organization_id) == after_first
        counts = await count_org_rows(app_engine, manifest.organization_id)
        assert counts["organizations"] == 1
        assert counts["workspaces"] >= len(manifest.workspaces)
        assert counts["users"] >= len(manifest.members)
