"""Migration 0006 (EA-23): ``audit_events.workspace_id``, ``old_value`` and ``new_value``.

Each case runs as the application role in a tenant transaction; a failing statement rolls back.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import PLATFORM_OPERATOR, record_role_change
from ei_ai.db.tenant import tenant_transaction
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration


async def _insert(engine: AsyncEngine, org: uuid.UUID, **values: Any) -> None:
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    async with engine.connect() as conn, tenant_transaction(conn, org):
        await conn.execute(
            text(
                "INSERT INTO audit_events (org_id, actor, action, target_type, target_id"
                f"{', ' + columns if values else ''})"
                " VALUES (:org, 'platform-operator', 'member.workspace_role_changed', 'user',"
                f" :target{', ' + params if values else ''})"
            ),
            {"org": org, "target": uuid.uuid4(), **values},
        )


async def _rows(engine: AsyncEngine, org: uuid.UUID, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as conn, tenant_transaction(conn, org):
        return list((await conn.execute(text(sql), {"org": org, **params})).all())


async def test_columns_are_nullable_text_and_uuid(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    rows = await _rows(
        app_engine,
        two_orgs.a.org_id,
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_name = 'audit_events'"
        " AND column_name IN ('workspace_id', 'old_value', 'new_value') ORDER BY column_name",
    )

    assert rows == [
        ("new_value", "text", "YES"),
        ("old_value", "text", "YES"),
        ("workspace_id", "uuid", "YES"),
    ]


@pytest.mark.parametrize("column", ["old_value", "new_value"])
@pytest.mark.parametrize("value", ["Builder", "x y", "builder1", "a" * 41, "", "o'brien"])
async def test_check_rejects_a_value_that_is_not_a_role_code(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, column: str, value: str
) -> None:
    with pytest.raises(IntegrityError):
        await _insert(app_engine, two_orgs.a.org_id, **{column: value})


async def test_check_accepts_role_codes_and_null(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    org = two_orgs.a.org_id
    await _insert(app_engine, org, old_value="viewer", new_value="knowledge_editor")
    await _insert(app_engine, org, workspace_id=uuid.uuid4(), new_value="builder")
    await _insert(app_engine, org)

    [(count,)] = await _rows(
        app_engine,
        org,
        "SELECT count(*) FROM audit_events WHERE org_id = :org"
        " AND action = 'member.workspace_role_changed'",
    )
    assert count == 3


async def test_another_organizations_role_events_are_invisible(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    workspace = uuid.uuid4()
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        await record_role_change(
            conn,
            b.org_id,
            PLATFORM_OPERATOR,
            b.user_id,
            workspace_id=workspace,
            old=None,
            new="builder",
        )

    seen_by_a = await _rows(
        app_engine,
        a.org_id,
        "SELECT count(*) FROM audit_events WHERE new_value = 'builder' OR workspace_id = :ws",
        ws=workspace,
    )
    seen_by_b = await _rows(
        app_engine,
        b.org_id,
        "SELECT workspace_id, old_value, new_value FROM audit_events WHERE new_value = 'builder'",
    )

    assert seen_by_a == [(0,)]
    assert seen_by_b == [(workspace, None, "builder")]


async def test_workspace_id_outlives_its_workspace(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    org = two_orgs.a.org_id
    gone = uuid.uuid4()  # no such Workspace: the column has no foreign key (append-only rows)

    await _insert(app_engine, org, workspace_id=gone, new_value="viewer")

    assert await _rows(
        app_engine, org, "SELECT count(*) FROM audit_events WHERE workspace_id = :ws", ws=gone
    ) == [(1,)]
