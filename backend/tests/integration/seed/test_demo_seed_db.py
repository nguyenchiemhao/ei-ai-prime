"""``seed demo`` against the real database (FND-04 AC3, AC4).

Variants of the manifest use a random Organization id and a suffixed name and are purged
afterwards; the real demo Organization is left in place (CI seeds it before these tests).
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.set_password import hash_secret
from ei_ai.db.tenant import tenant_transaction
from ei_ai.provisioning.validation import ProvisioningError
from ei_ai.seed.demo import DemoManifest, load_manifest, seed_manifest
from support.tenants import (
    DELETE_ORDER,
    TwoOrgs,
    count_org_rows,
    purge_org_ids,
    tenant_key_column,
)

pytestmark = pytest.mark.integration

FIRST_RUN_COUNTS = {
    "admin_sessions": 0,
    "user_credentials": 0,
    "audit_events": 8,
    "set_password_tokens": 6,
    "workspace_memberships": 6,
    "memberships": 6,
    "workspaces": 1,
    "users": 6,
    # The three platform models of the manifest (EA-24); the seed writes no audit event for them.
    "model_catalog": 3,
    "organizations": 1,
}


@pytest.fixture
async def variant(app_engine: AsyncEngine) -> AsyncIterator[DemoManifest]:
    """The demo manifest with a random Organization id and name; purged afterwards."""
    manifest = load_manifest().model_copy(
        update={
            "organization_id": uuid.uuid4(),
            "organization": f"Mekong Devworks {uuid.uuid4().hex[:8]}",
        }
    )
    try:
        yield manifest
    finally:
        await purge_org_ids(app_engine, manifest.organization_id)


async def _all_rows(engine: AsyncEngine, org_id: uuid.UUID) -> dict[str, list[tuple[object, ...]]]:
    rows = {}
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        for table in DELETE_ORDER:
            sql = f"SELECT * FROM {table} WHERE {tenant_key_column(table)} = :org ORDER BY id"
            rows[table] = [tuple(r) for r in await conn.execute(text(sql), {"org": org_id})]
    return rows


async def test_seed_twice_on_fresh_manifest_creates_once(
    app_engine: AsyncEngine, variant: DemoManifest
) -> None:
    first = await seed_manifest(app_engine, variant)
    after_first = await _all_rows(app_engine, variant.organization_id)
    second = await seed_manifest(app_engine, variant)

    assert first.organization_created and first.workspace_created
    assert all(secret is not None for secret in first.member_secrets)
    assert first.audit_events == 8
    assert await count_org_rows(app_engine, variant.organization_id) == FIRST_RUN_COUNTS
    assert not second.organization_created and not second.workspace_created
    assert second.member_secrets == (None,) * 6
    assert second.audit_events == 0
    assert second.workspace_id == first.workspace_id
    assert await _all_rows(app_engine, variant.organization_id) == after_first


async def test_first_seed_writes_8_events_second_writes_0(
    app_engine: AsyncEngine, variant: DemoManifest
) -> None:
    org_id = variant.organization_id
    first = await seed_manifest(app_engine, variant)
    async with app_engine.connect() as conn, tenant_transaction(conn, org_id):
        events = sorted(
            tuple(row)
            for row in await conn.execute(
                text("SELECT actor, action, target_type FROM audit_events WHERE org_id = :org"),
                {"org": org_id},
            )
        )
        targets = set(
            (
                await conn.execute(
                    text("SELECT target_id FROM audit_events WHERE org_id = :org"),
                    {"org": org_id},
                )
            ).scalars()
        )
        user_ids = set(
            (
                await conn.execute(
                    text("SELECT id FROM users WHERE org_id = :org"), {"org": org_id}
                )
            ).scalars()
        )
    await seed_manifest(app_engine, variant)

    assert events == sorted(
        [
            ("platform-operator", "organization.created", "organization"),
            ("platform-operator", "workspace.created", "workspace"),
            *[("platform-operator", "user.invited", "user")] * 6,
        ]
    )
    assert targets == {org_id, first.workspace_id, *user_ids}
    assert (await count_org_rows(app_engine, org_id))["audit_events"] == 8


async def test_seed_writes_roles_and_hashed_tokens(
    app_engine: AsyncEngine, variant: DemoManifest
) -> None:
    org_id = variant.organization_id
    result = await seed_manifest(app_engine, variant)
    async with app_engine.connect() as conn, tenant_transaction(conn, org_id):
        rows = (
            await conn.execute(
                text(
                    "SELECT u.email, u.display_name, m.org_role, w.role, w.workspace_id,"
                    " t.token_hash FROM users u"
                    " JOIN memberships m ON m.org_id = u.org_id AND m.user_id = u.id"
                    " JOIN workspace_memberships w ON w.org_id = u.org_id AND w.user_id = u.id"
                    " JOIN set_password_tokens t ON t.org_id = u.org_id AND t.user_id = u.id"
                    " WHERE u.org_id = :org"
                ),
                {"org": org_id},
            )
        ).all()

    expected = {
        (
            member.email,
            member.name,
            "org_admin" if "org_admin" in member.roles else None,
            member.roles[-1],
            result.workspace_id,
            hash_secret(secret or ""),
        )
        for member, secret in zip(variant.members, result.member_secrets, strict=True)
    }
    assert {tuple(row) for row in rows} == expected


async def test_seed_never_changes_existing_rows(
    app_engine: AsyncEngine, variant: DemoManifest
) -> None:
    org_id = variant.organization_id
    await seed_manifest(app_engine, variant)
    async with app_engine.connect() as conn, tenant_transaction(conn, org_id):
        await conn.execute(
            text(
                "UPDATE users SET display_name = 'Renamed by hand'"
                " WHERE org_id = :org AND email = 'minh.pham@mekongdevworks.example'"
            ),
            {"org": org_id},
        )
        await conn.execute(
            text("DELETE FROM set_password_tokens WHERE org_id = :org"), {"org": org_id}
        )
    before = await _all_rows(app_engine, org_id)

    result = await seed_manifest(app_engine, variant)

    assert result.audit_events == 0
    assert await _all_rows(app_engine, org_id) == before
    assert any("Renamed by hand" in row for row in before["users"])


async def test_seed_adds_only_what_is_missing(
    app_engine: AsyncEngine, variant: DemoManifest
) -> None:
    org_id = variant.organization_id
    await seed_manifest(app_engine, variant)
    params = {"org": org_id, "email": "son.hoang@mekongdevworks.example"}
    son = "(SELECT id FROM users WHERE org_id = :org AND email = :email)"
    async with app_engine.connect() as conn, tenant_transaction(conn, org_id):
        for table in ("set_password_tokens", "workspace_memberships", "memberships"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE org_id = :org AND user_id IN {son}"), params
            )
        await conn.execute(text(f"DELETE FROM users WHERE org_id = :org AND id IN {son}"), params)

    result = await seed_manifest(app_engine, variant)

    assert result.member_secrets[:5] == (None,) * 5
    assert result.member_secrets[5] is not None
    assert result.audit_events == 1
    counts = await count_org_rows(app_engine, org_id)
    assert counts["users"] == 6
    assert counts["audit_events"] == 9


async def test_real_manifest_is_idempotent(app_engine: AsyncEngine) -> None:
    manifest = load_manifest()

    await seed_manifest(app_engine, manifest)
    after_first = await _all_rows(app_engine, manifest.organization_id)
    second = await seed_manifest(app_engine, manifest)

    assert second.audit_events == 0
    assert await _all_rows(app_engine, manifest.organization_id) == after_first
    counts = await count_org_rows(app_engine, manifest.organization_id)
    assert (counts["organizations"], counts["workspaces"], counts["users"]) == (1, 1, 6)


async def test_name_taken_by_another_org_exits_1(
    app_engine: AsyncEngine, variant: DemoManifest, two_orgs: TwoOrgs
) -> None:
    taken = variant.model_copy(update={"organization": two_orgs.a.names.organization.upper()})

    with pytest.raises(ProvisioningError) as error:
        await seed_manifest(app_engine, taken)

    assert str(error.value) == (
        f'an Organization named "{taken.organization}" already exists with another id'
    )
    assert await count_org_rows(app_engine, variant.organization_id) == dict.fromkeys(
        DELETE_ORDER, 0
    )
