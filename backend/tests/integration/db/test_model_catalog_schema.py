"""Migration 0005 (EA-24): ``model_catalog``, the Organization cloud switch and the audit target.

Each case runs as the application role in a tenant transaction; a failing statement rolls back.
"""

import datetime
import uuid
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import FIXTURE_MODEL_ID, FIXTURE_MODEL_VERSION, TwoOrgs

pytestmark = pytest.mark.integration

# (column, data type, nullable, default) in table order: the AC7 contract (plan §6).
COLUMNS = [
    ("id", "uuid", "NO", "uuid_generate_v7()"),
    ("org_id", "uuid", "NO", None),
    ("kind", "text", "NO", None),
    ("display_name", "text", "NO", None),
    ("model_id", "text", "NO", None),
    ("version", "text", "NO", None),
    ("digest", "text", "YES", None),
    ("source_revision", "text", "YES", None),
    ("deployment", "text", "NO", None),
    ("provider", "text", "NO", None),
    ("vietnamese_quality", "text", "YES", None),
    ("vietnamese_quality_measured", "boolean", "NO", "false"),
    ("tool_use", "boolean", "NO", "false"),
    ("context_window", "integer", "YES", None),
    ("speed", "text", "YES", None),
    ("status", "text", "NO", "'available'::text"),
    ("retirement_date", "date", "YES", None),
    ("created_at", "timestamp with time zone", "NO", "now()"),
]
PIN_COLUMNS = {
    "kind": "embedding",
    "model_id": "other-model",
    "version": "v2",
    "digest": f"sha256:{'b' * 64}",
    "source_revision": "someone/else@main/file.gguf",
    "deployment": "cloud",
    "provider": "openai",
}
DIGEST = f"sha256:{'a' * 64}"
BASE_ROW: dict[str, Any] = {
    "kind": "chat",
    "display_name": "Schema test",
    "model_id": "schema-test",
    "version": "v1",
    "digest": DIGEST,
    "deployment": "local",
    "provider": "local-chat",
    "status": "available",
    "retirement_date": None,
    "vietnamese_quality": None,
    "speed": None,
    "context_window": None,
}


async def _insert(engine: AsyncEngine, org: uuid.UUID, **overrides: Any) -> uuid.UUID:
    row = {**BASE_ROW, **overrides}
    columns = ", ".join(row)
    values = ", ".join(f":{name}" for name in row)
    async with engine.connect() as conn, tenant_transaction(conn, org):
        result = await conn.execute(
            text(
                f"INSERT INTO model_catalog (org_id, {columns}) VALUES (:org, {values})"
                " RETURNING id"
            ),
            {"org": org, **row},
        )
        new_id: uuid.UUID = result.scalar_one()
    return new_id


async def _scalar(engine: AsyncEngine, org: uuid.UUID, sql: str, **params: object) -> Any:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        return (await conn.execute(text(sql), params)).scalar()


async def test_columns_cover_artboard_fields(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, column_default"
                    " FROM information_schema.columns WHERE table_name = 'model_catalog'"
                    " ORDER BY ordinal_position"
                )
            )
        ).all()

    assert [tuple(row) for row in rows] == COLUMNS
    # SSRF (attack 21): the catalog never holds an endpoint; providers map to configured URLs.
    assert not [name for name, *_ in COLUMNS if "url" in name or "endpoint" in name]


async def test_rls_is_enabled_and_forced(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        flags = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
                    " WHERE relname = 'model_catalog'"
                )
            )
        ).one()

    assert tuple(flags) == (True, True)


async def test_defaults_of_a_minimal_cloud_row(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    org = two_orgs.a.org_id
    async with app_engine.connect() as conn, tenant_transaction(conn, org):
        row = (
            await conn.execute(
                text(
                    "INSERT INTO model_catalog (org_id, kind, display_name, model_id, version,"
                    " deployment, provider) VALUES (:org, 'chat', 'Cloud', 'gpt-4.1-2025-04-14',"
                    " '2025.04', 'cloud', 'openai')"
                    " RETURNING digest, status, vietnamese_quality_measured, tool_use"
                ),
                {"org": org},
            )
        ).one()

    assert tuple(row) == (None, "available", False, False)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "vision"},
        {"deployment": "edge"},
        {"status": "gone"},
        {"vietnamese_quality": "excellent"},
        {"speed": "fast"},
        {"context_window": 0},
        {"digest": None},
        {"digest": "sha256:" + "A" * 64},
        {"digest": "md5:" + "a" * 32},
        {"status": "retiring", "retirement_date": None},
        {"model_id": "Qwen3"},
        {"model_id": "a" * 101},
        {"version": "2026 10"},
        {"provider": "Local_Chat"},
        {"display_name": ""},
    ],
    ids=lambda overrides: ",".join(f"{k}={v!r}"[:30] for k, v in overrides.items()),
)
async def test_check_constraints(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, overrides: dict[str, Any]
) -> None:
    with pytest.raises(IntegrityError) as error:
        await _insert(app_engine, two_orgs.a.org_id, **overrides)

    assert getattr(error.value.orig, "sqlstate", None) == "23514"


async def test_retiring_with_a_date_is_accepted(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    new_id = await _insert(
        app_engine,
        two_orgs.a.org_id,
        status="retiring",
        retirement_date=datetime.date(2026, 11, 20),
        vietnamese_quality="good",
        speed="faster",
        context_window=32768,
    )

    assert isinstance(new_id, uuid.UUID)


async def test_ref_is_unique_per_organization(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    # Both fixture Organizations already hold FIXTURE_MODEL_ID@FIXTURE_MODEL_VERSION.
    with pytest.raises(IntegrityError) as error:
        await _insert(
            app_engine,
            two_orgs.a.org_id,
            model_id=FIXTURE_MODEL_ID,
            version=FIXTURE_MODEL_VERSION,
        )

    assert getattr(error.value.orig, "sqlstate", None) == "23505"


@pytest.mark.parametrize(("column", "value"), list(PIN_COLUMNS.items()))
async def test_pin_columns_cannot_be_updated(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, column: str, value: str
) -> None:
    a = two_orgs.a
    before = await _scalar(
        app_engine,
        a.org_id,
        f"SELECT {column} FROM model_catalog WHERE id = :id",
        id=a.model_catalog_entry_id,
    )

    with pytest.raises(DBAPIError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            await conn.execute(
                text(f"UPDATE model_catalog SET {column} = :value WHERE id = :id"),
                {"value": value, "id": a.model_catalog_entry_id},
            )

    assert "pin columns are immutable" in str(error.value.orig)
    after = await _scalar(
        app_engine,
        a.org_id,
        f"SELECT {column} FROM model_catalog WHERE id = :id",
        id=a.model_catalog_entry_id,
    )
    assert after == before


def test_pin_columns_cannot_be_updated_by_the_owner_role(
    migrator_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    migrator_conn.autocommit = False
    try:
        migrator_conn.execute("SELECT set_config('app.current_org', %s, true)", (str(a.org_id),))
        with pytest.raises(psycopg.errors.RaiseException) as error:
            migrator_conn.execute(
                "UPDATE model_catalog SET digest = %s WHERE id = %s",
                (f"sha256:{'c' * 64}", a.model_catalog_entry_id),
            )
    finally:
        migrator_conn.rollback()
        migrator_conn.autocommit = True

    assert "pin columns are immutable" in str(error.value)


async def test_status_retirement_and_labels_can_be_updated(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        result = await conn.execute(
            text(
                "UPDATE model_catalog SET status = 'retiring', retirement_date = '2026-11-20',"
                " display_name = 'Renamed', vietnamese_quality = 'fair',"
                " vietnamese_quality_measured = true, tool_use = true, context_window = 8192,"
                " speed = 'slower' WHERE id = :id"
            ),
            {"id": a.model_catalog_entry_id},
        )

    assert result.rowcount == 1


async def test_allow_cloud_models_defaults_to_false(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn:
        column = (
            await conn.execute(
                text(
                    "SELECT data_type, is_nullable, column_default FROM information_schema.columns"
                    " WHERE table_name = 'organizations' AND column_name = 'allow_cloud_models'"
                )
            )
        ).one()
    value = await _scalar(
        app_engine,
        two_orgs.a.org_id,
        "SELECT allow_cloud_models FROM organizations WHERE id = :id",
        id=two_orgs.a.org_id,
    )

    assert tuple(column) == ("boolean", "NO", "false")
    assert value is False


async def test_audit_target_type_model_is_accepted(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(
            text(
                "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
                " VALUES (:org, 'platform-operator', 'model.catalog_entry_added', 'model', :id)"
            ),
            {"org": a.org_id, "id": a.model_catalog_entry_id},
        )

    with pytest.raises(IntegrityError):
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
                    " VALUES (:org, 'platform-operator', 'model.x', 'assistant', :id)"
                ),
                {"org": a.org_id, "id": a.model_catalog_entry_id},
            )
