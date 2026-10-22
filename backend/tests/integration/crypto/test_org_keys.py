"""EA-20 AC1: every Organization has its own wrapped data key (table, provisioning, seed)."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.crypto.envelope import WRAPPED_KEY_BYTES, unwrap_data_key
from ei_ai.crypto.errors import DecryptionFailed
from ei_ai.crypto.lifecycle import destroy_org_key, ensure_org_key
from ei_ai.db.tenant import tenant_transaction
from ei_ai.provisioning.service import create_organization
from ei_ai.seed.demo import DemoManifest, seed_manifest
from ei_ai.tenancy.context import TenantContext
from support.crypto import TEST_MASTER_KEY
from support.seed import TEST_SEED_PASSWORD, variant_manifests
from support.tenants import TwoOrgs, purge_org_ids

pytestmark = pytest.mark.integration

COLUMNS = "id, org_id, wrapped_key, kek_id, created_at, destroyed_at"


@pytest.fixture
async def created(app_engine: AsyncEngine) -> AsyncIterator[list[uuid.UUID]]:
    ids: list[uuid.UUID] = []
    try:
        yield ids
    finally:
        await purge_org_ids(app_engine, *ids)


@pytest.fixture
async def variants(app_engine: AsyncEngine) -> AsyncIterator[tuple[DemoManifest, ...]]:
    manifests = variant_manifests()
    try:
        yield manifests
    finally:
        await purge_org_ids(app_engine, *(m.organization_id for m in manifests))


async def _new_org(engine: AsyncEngine, created: list[uuid.UUID]) -> uuid.UUID:
    sfx = uuid.uuid4().hex[:8]
    result = await create_organization(
        engine, f"Keys {sfx}", f"owner.{sfx}@example.com", master=TEST_MASTER_KEY
    )
    created.append(result.org_id)
    return result.org_id


async def _rows(engine: AsyncEngine, org_id: uuid.UUID) -> list[Any]:
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        result = await conn.execute(
            text(f"SELECT {COLUMNS} FROM organization_keys WHERE org_id = :org"), {"org": org_id}
        )
        return list(result.all())


async def _insert(
    engine: AsyncEngine, context: uuid.UUID, org_id: uuid.UUID, wrapped: bytes | None, live: bool
) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, context):
        await conn.execute(
            text(
                "INSERT INTO organization_keys (org_id, wrapped_key, kek_id, destroyed_at)"
                " VALUES (:org, :wrapped, '0123456789abcdef',"
                " CASE WHEN :live THEN NULL ELSE now() END)"
            ),
            {"org": org_id, "wrapped": wrapped, "live": live},
        )


def test_organization_keys_has_rls_and_grants(migrator_conn: psycopg.Connection) -> None:
    rls = migrator_conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner)"
        " FROM pg_class WHERE relname = 'organization_keys'"
    ).fetchone()
    grants = migrator_conn.execute(
        "SELECT privilege_type FROM information_schema.role_table_grants"
        " WHERE table_name = 'organization_keys' AND grantee = 'ei_ai_app'"
        " ORDER BY privilege_type"
    ).fetchall()
    policies = migrator_conn.execute(
        "SELECT count(*) FROM pg_policies WHERE tablename = 'organization_keys'"
    ).fetchone()

    assert rls == (True, True, "ei_ai_migrator")
    assert [g[0] for g in grants] == ["DELETE", "INSERT", "SELECT", "UPDATE"]
    assert policies == (1,)


async def test_organization_keys_has_rls_and_constraints(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, created: list[uuid.UUID]
) -> None:
    org = two_orgs.a.org_id
    live = bytes(WRAPPED_KEY_BYTES)

    with pytest.raises(IntegrityError):  # UNIQUE (org_id): the fixture already created the key
        await _insert(app_engine, org, org, live, True)

    sfx = uuid.uuid4().hex[:8]
    other = uuid.uuid4()
    created.append(other)
    async with app_engine.connect() as conn, tenant_transaction(conn, other):
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": other, "name": f"Constraint {sfx}"},
        )
    for wrapped, is_live in [
        (bytes(59), True),  # the 60-byte check
        (bytes(61), True),
        (None, True),  # wrapped_key NULL needs destroyed_at
        (live, False),  # destroyed_at needs wrapped_key NULL
    ]:
        with pytest.raises(IntegrityError):
            await _insert(app_engine, other, other, wrapped, is_live)

    # Row-level security: without a tenant context no row is visible.
    async with app_engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM organization_keys"))).scalar_one()
    assert count == 0


async def test_each_organization_gets_its_own_wrapped_data_key(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    first = await _new_org(app_engine, created)
    second = await _new_org(app_engine, created)

    rows = {org: await _rows(app_engine, org) for org in (first, second)}

    assert [len(r) for r in rows.values()] == [1, 1]
    wrapped = {org: bytes(r[0].wrapped_key) for org, r in rows.items()}
    assert wrapped[first] != wrapped[second]
    assert all(len(w) == WRAPPED_KEY_BYTES for w in wrapped.values())
    assert all(r[0].kek_id == TEST_MASTER_KEY.kek_id for r in rows.values())
    deks = {org: unwrap_data_key(TEST_MASTER_KEY, org, w) for org, w in wrapped.items()}
    distinct = deks[first] != deks[second]
    assert distinct, "two Organizations share a data key"
    for org_rows in rows.values():
        cells = [str(value) for value in org_rows[0]]
        raw = bytes(org_rows[0].wrapped_key)
        for dek in deks.values():
            hex_in_row = any(dek.hex() in cell for cell in cells)
            assert not hex_in_row, "a data key appears in hex in a key row"
            bytes_in_row = dek in raw
            assert not bytes_in_row, "a data key appears in plaintext in a wrapped key"


async def test_ensure_org_key_creates_once_and_never_recreates_a_destroyed_key(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    org = await _new_org(app_engine, created)
    async with app_engine.connect() as conn, tenant_transaction(conn, org):
        await conn.execute(text("DELETE FROM organization_keys WHERE org_id = :org"), {"org": org})
    results = []
    for step in ("ensure", "ensure", "destroy", "ensure"):
        async with app_engine.connect() as conn, tenant_transaction(conn, org):
            if step == "destroy":
                results.append(await destroy_org_key(conn, org))
            else:
                results.append(await ensure_org_key(conn, org, TEST_MASTER_KEY))

    assert results == [True, False, True, False]
    (row,) = await _rows(app_engine, org)
    assert row.wrapped_key is None
    assert row.destroyed_at is not None


@pytest.mark.isolation
async def test_wrapped_key_copied_to_another_org_does_not_unwrap(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    (row_a,) = await _rows(app_engine, a.org_id)
    wrapped_a = bytes(row_a.wrapped_key)

    with pytest.raises(DecryptionFailed):
        unwrap_data_key(TEST_MASTER_KEY, b.org_id, wrapped_a)

    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        await conn.execute(
            text("UPDATE organization_keys SET wrapped_key = :w WHERE org_id = :org"),
            {"w": wrapped_a, "org": b.org_id},
        )
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        tenant = TenantContext(org_id=b.org_id, user_id=b.user_id)
        with pytest.raises(DecryptionFailed):
            await OrgCipher(TEST_MASTER_KEY).encrypt(conn, tenant, b"payload")


@pytest.mark.isolation
async def test_other_orgs_key_row_is_invisible_and_cannot_be_forged(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        seen = (
            await conn.execute(
                text("SELECT count(*) FROM organization_keys WHERE org_id = :org"),
                {"org": two_orgs.b.org_id},
            )
        ).scalar_one()

    assert seen == 0
    with pytest.raises(DBAPIError):
        await _insert(
            app_engine, two_orgs.a.org_id, two_orgs.b.org_id, bytes(WRAPPED_KEY_BYTES), True
        )


async def test_seed_creates_one_key_per_organization_and_rerun_keeps_it(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    for manifest in variants:
        await seed_manifest(app_engine, manifest, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
    first = {m.organization_id: await _rows(app_engine, m.organization_id) for m in variants}
    for manifest in variants:
        await seed_manifest(app_engine, manifest, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
    second = {m.organization_id: await _rows(app_engine, m.organization_id) for m in variants}

    assert [len(rows) for rows in first.values()] == [1, 1]
    assert second == first
