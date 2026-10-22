"""``DbCatalog`` against the real database as ``ei_ai_app`` (EA-24 AC1, AC2, AC5, attacks 1-3, 11).

Every read runs in the caller's tenant transaction with the explicit Organization filter and RLS.
"""

import datetime
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.model_gateway.catalog import DbCatalog
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.factory import build_gateway
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.results import ChatMessage, TextDelta
from ei_ai.seed.demo import DemoManifest, seed_manifest
from ei_ai.settings import ModelSettings
from support.crypto import TEST_MASTER_KEY
from support.fake_model_server import FakeModelServer, running_fake_model_server
from support.seed import TEST_SEED_PASSWORD, variant_manifests
from support.tenants import FIXTURE_MODEL_ID, FIXTURE_MODEL_VERSION, TwoOrgs, purge_org_ids

pytestmark = pytest.mark.integration

FIXTURE_REF = ModelRef(FIXTURE_MODEL_ID, FIXTURE_MODEL_VERSION)
TODAY = datetime.date(2026, 10, 20)
QWEN = ModelRef("qwen3-4b-instruct-2507", "2026.10")


def _ctx(org_id: uuid.UUID) -> ModelCallContext:
    return ModelCallContext(org_id=org_id, actor="platform-operator")


def _catalog(engine: AsyncEngine) -> DbCatalog:
    return DbCatalog(engine, today=lambda: TODAY)


async def _execute(engine: AsyncEngine, org: uuid.UUID, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        return (await conn.execute(text(sql), {"org": org, **params})).all()


async def _insert_row(engine: AsyncEngine, org: uuid.UUID, **values: Any) -> uuid.UUID:
    row = {
        "kind": "chat",
        "display_name": "Test row",
        "digest": f"sha256:{'e' * 64}",
        "deployment": "local",
        "provider": "local-chat",
        "status": "available",
        "retirement_date": None,
        **values,
    }
    columns = ", ".join(row)
    params = ", ".join(f":{name}" for name in row)
    rows = await _execute(
        engine,
        org,
        f"INSERT INTO model_catalog (org_id, {columns}) VALUES (:org, {params}) RETURNING id",
        **row,
    )
    new_id: uuid.UUID = rows[0][0]
    return new_id


async def _block_events(engine: AsyncEngine, org: uuid.UUID) -> list[tuple[Any, ...]]:
    rows = await _execute(
        engine,
        org,
        "SELECT actor, action, target_type, target_id FROM audit_events"
        " WHERE org_id = :org AND action = 'model.cloud_call_blocked'",
    )
    return [tuple(row) for row in rows]


@pytest.fixture
async def seeded(app_engine: AsyncEngine) -> AsyncIterator[DemoManifest]:
    """The demo manifest seeded into a random Organization; purged afterwards."""
    manifest = variant_manifests()[0]
    await seed_manifest(app_engine, manifest, TEST_SEED_PASSWORD, master=TEST_MASTER_KEY)
    try:
        yield manifest
    finally:
        await purge_org_ids(app_engine, manifest.organization_id)


async def test_resolves_seeded_local_chat_model(
    app_engine: AsyncEngine, seeded: DemoManifest
) -> None:
    resolved = await _catalog(app_engine).resolve(_ctx(seeded.organization_id), QWEN, "chat")

    entry = resolved.entry
    assert (entry.model_id, entry.version, entry.kind) == (QWEN.model_id, QWEN.version, "chat")
    assert entry.digest == (
        "sha256:3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
    )
    assert (entry.deployment, entry.provider) == ("local", "local-chat")
    assert resolved.cloud_allowed is False


async def test_ref_of_other_org_is_model_not_found(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    await _insert_row(app_engine, two_orgs.b.org_id, model_id="only-in-b", version="v1")

    with pytest.raises(ModelError) as error:
        await _catalog(app_engine).resolve(_ctx(two_orgs.a.org_id), ModelRef("only-in-b", "v1"))

    assert error.value.code is ModelErrorCode.MODEL_NOT_FOUND
    assert str(error.value) == "no chat model only-in-b@v1 in this Organization's catalog"


async def test_same_ref_resolves_to_own_org_digest(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    catalog = _catalog(app_engine)

    in_a = await catalog.resolve(_ctx(two_orgs.a.org_id), FIXTURE_REF)
    in_b = await catalog.resolve(_ctx(two_orgs.b.org_id), FIXTURE_REF)

    assert in_a.entry.digest == two_orgs.a.model_digest
    assert in_b.entry.digest == two_orgs.b.model_digest
    assert in_a.entry.id == two_orgs.a.model_catalog_entry_id
    assert in_b.entry.id == two_orgs.b.model_catalog_entry_id


async def test_other_kind_is_model_not_found(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    with pytest.raises(ModelError) as error:
        await _catalog(app_engine).resolve(_ctx(two_orgs.a.org_id), FIXTURE_REF, "embedding")

    assert error.value.code is ModelErrorCode.MODEL_NOT_FOUND
    assert str(error.value) == (f"no embedding model {FIXTURE_REF} in this Organization's catalog")


@pytest.mark.parametrize(
    ("status", "retirement_date"),
    [
        ("retired", None),
        ("retiring", TODAY),
        ("retiring", TODAY - datetime.timedelta(days=1)),
        ("available", TODAY),
    ],
)
async def test_retired_or_past_date_is_model_retired(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    status: str,
    retirement_date: datetime.date | None,
) -> None:
    await _insert_row(
        app_engine,
        two_orgs.a.org_id,
        model_id="old-model",
        version="v1",
        status=status,
        retirement_date=retirement_date,
    )

    with pytest.raises(ModelError) as error:
        await _catalog(app_engine).resolve(_ctx(two_orgs.a.org_id), ModelRef("old-model", "v1"))

    assert error.value.code is ModelErrorCode.MODEL_RETIRED
    assert str(error.value) == "model old-model@v1 is retired"


async def test_retiring_before_its_date_is_still_callable(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    await _insert_row(
        app_engine,
        two_orgs.a.org_id,
        model_id="old-model",
        version="v1",
        status="retiring",
        retirement_date=TODAY + datetime.timedelta(days=1),
    )

    resolved = await _catalog(app_engine).resolve(
        _ctx(two_orgs.a.org_id), ModelRef("old-model", "v1")
    )

    assert resolved.entry.status == "retiring"


async def test_cloud_switch_is_read_from_the_organization_row(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    await _execute(
        app_engine,
        two_orgs.a.org_id,
        "UPDATE organizations SET allow_cloud_models = true WHERE id = :org RETURNING id",
    )
    catalog = _catalog(app_engine)

    in_a = await catalog.resolve(_ctx(two_orgs.a.org_id), FIXTURE_REF)
    in_b = await catalog.resolve(_ctx(two_orgs.b.org_id), FIXTURE_REF)

    assert in_a.cloud_allowed is True
    assert in_b.cloud_allowed is False


async def test_blocked_cloud_call_writes_committed_audit_event(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    catalog = _catalog(app_engine)
    entry = (await catalog.resolve(_ctx(a.org_id), FIXTURE_REF)).entry

    await catalog.record_cloud_block(ModelCallContext(org_id=a.org_id, actor="user:x"), entry)

    # Read back in a new transaction: the event is committed, not part of an open one.
    assert await _block_events(app_engine, a.org_id) == [
        ("user:x", "model.cloud_call_blocked", "model", a.model_catalog_entry_id)
    ]


async def test_block_audit_lands_only_in_caller_org(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    catalog = _catalog(app_engine)
    entry = (await catalog.resolve(_ctx(two_orgs.a.org_id), FIXTURE_REF)).entry

    await catalog.record_cloud_block(_ctx(two_orgs.a.org_id), entry)

    assert len(await _block_events(app_engine, two_orgs.a.org_id)) == 1
    assert await _block_events(app_engine, two_orgs.b.org_id) == []


@pytest.fixture
def local_server() -> Iterator[FakeModelServer]:
    yield from running_fake_model_server()


def _settings(local: FakeModelServer) -> ModelSettings:
    return ModelSettings(environment="test", local_base_url=local.base_url, retry_delay_seconds=0)


async def test_gateway_streams_the_seeded_model_from_the_database(
    app_engine: AsyncEngine, seeded: DemoManifest, local_server: FakeModelServer
) -> None:
    local_server.listed_ids = ["qwen3-4b-instruct-2507@sha256-3605803b982c"]
    gateway = build_gateway(_settings(local_server), app_engine, observers=[])
    try:
        events = [
            event
            async for event in gateway.stream_chat(
                _ctx(seeded.organization_id), QWEN, [ChatMessage("user", "hi")]
            )
        ]
    finally:
        await gateway.aclose()

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Xin", " chào"]
    assert local_server.requests[1].body["model"] == "qwen3-4b-instruct-2507@sha256-3605803b982c"


async def test_gateway_block_audit_is_committed_although_the_call_fails(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, local_server: FakeModelServer
) -> None:
    a = two_orgs.a
    cloud_id = await _insert_row(
        app_engine,
        a.org_id,
        model_id="gpt-4.1-2025-04-14",
        version="2025.04",
        digest=None,
        deployment="cloud",
        provider="openai",
    )
    gateway = build_gateway(_settings(local_server), app_engine, observers=[])

    try:
        with pytest.raises(ModelError) as error:
            await gateway.chat(
                ModelCallContext(org_id=a.org_id, actor="platform-operator"),
                ModelRef("gpt-4.1-2025-04-14", "2025.04"),
                [ChatMessage("user", "hi")],
            )
    finally:
        await gateway.aclose()

    assert error.value.code is ModelErrorCode.CLOUD_DISABLED
    assert await _block_events(app_engine, a.org_id) == [
        ("platform-operator", "model.cloud_call_blocked", "model", cloud_id)
    ]
    assert await _block_events(app_engine, two_orgs.b.org_id) == []
    assert local_server.requests == []
