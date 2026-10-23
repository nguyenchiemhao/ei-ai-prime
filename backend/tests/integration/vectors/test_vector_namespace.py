"""EA-20 AC4: a vector query in the context of Organization A scans only A's partition.

Every Organization has its own LIST partition of ``chunk_embeddings`` with its own HNSW index;
the application role queries the parent only, with the explicit ``org_id`` filter (layer 1) on
top of row-level security (layer 2). There is no DEFAULT partition.
"""

import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai import cli
from ei_ai.db.migrations.roles import MigrationRoleError
from ei_ai.db.tenant import tenant_session, tenant_transaction
from ei_ai.jobs.envelope import JobContext
from ei_ai.tenancy.context import TenantContext
from ei_ai.vectors.partitions import (
    OrganizationNotFound,
    create_vector_partition,
    drop_vector_partition,
    partition_name,
)
from ei_ai.vectors.search import EMBEDDING_DIMENSIONS, MAX_K, NEAREST_SQL, nearest
from support.tenants import OrgRows, TwoOrgs, purge_org_ids
from support.vectors import DEFAULT_MODEL, insert_vector

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

APP = "ei_ai_app"
MIGRATOR = "ei_ai_migrator"

_PARTITIONS = (
    "SELECT c.relname, pg_get_userbyid(c.relowner), pg_get_expr(c.relpartbound, c.oid),"
    " EXISTS (SELECT 1 FROM pg_index i JOIN pg_class x ON x.oid = i.indexrelid"
    "         JOIN pg_am am ON am.oid = x.relam"
    "         WHERE i.indrelid = c.oid AND am.amname = 'hnsw')"
    " FROM pg_inherits h JOIN pg_class c ON c.oid = h.inhrelid"
    " WHERE h.inhparent = 'chunk_embeddings'::regclass ORDER BY c.relname"
)


def _unit(index: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


def _literal(values: list[float]) -> str:
    return "[" + ",".join(repr(value) for value in values) + "]"


def _tenant(org: OrgRows) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user_id)


async def _insert_raw_vector(
    engine: AsyncEngine, org_id: uuid.UUID, values: list[float]
) -> uuid.UUID:
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        result = await conn.execute(
            text(
                "INSERT INTO chunk_embeddings (org_id, embedding, chunk_id, document_id,"
                " workspace_id, collection_id, folder_id, access_level, groups, model_id,"
                " model_version) VALUES (:org, CAST(:v AS vector), gen_random_uuid(),"
                " gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),"
                " 'authenticated', '{}', 'bge-m3', '2026.10') RETURNING id"
            ),
            {"org": org_id, "v": _literal(values)},
        )
        vector_id: uuid.UUID = result.scalar_one()
    return vector_id


def _partitions(conn: psycopg.Connection) -> dict[str, tuple[str, str, bool]]:
    return {name: (owner, bound, hnsw) for name, owner, bound, hnsw in conn.execute(_PARTITIONS)}


def _plan_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


@pytest.fixture
async def bare_org(app_engine: AsyncEngine) -> AsyncIterator[uuid.UUID]:
    """An Organization row without a vector partition; removed (with any partition) afterwards."""
    org_id = uuid.uuid4()
    async with app_engine.connect() as conn, tenant_transaction(conn, org_id):
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": org_id, "name": f"Org bare {org_id.hex[:8]}"},
        )
    try:
        yield org_id
    finally:
        await purge_org_ids(app_engine, org_id)


async def test_nearest_as_a_never_returns_b_even_when_b_is_nearest(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    query = _unit(0)
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        b_nearest = await insert_vector(conn, b, query)  # distance 0: global nearest
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        a_far = await insert_vector(conn, a, _unit(1))  # distance 1

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        route_hits = await nearest(conn, _tenant(a), query, MAX_K, model=DEFAULT_MODEL)
    async with tenant_session(app_engine, a.org_id) as session:
        job_hits = await nearest(
            session, JobContext(org_id=a.org_id, session=session), query, 1, model=DEFAULT_MODEL
        )
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        b_hits = await nearest(conn, _tenant(b), query, 1, model=DEFAULT_MODEL)

    assert [hit.id for hit in route_hits] == [a.chunk_embedding_id, a_far]
    assert route_hits[0].distance < route_hits[1].distance
    assert route_hits[1].distance == pytest.approx(1.0)
    assert [hit.id for hit in job_hits] == [a.chunk_embedding_id]
    assert [hit.id for hit in b_hits] == [b_nearest]
    assert b_hits[0].distance == pytest.approx(0.0)
    assert b_nearest not in {hit.id for hit in route_hits + job_hits}


async def test_query_plan_scans_only_the_own_partition(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    params = {
        "q": _literal(_unit(0)),
        "org": a.org_id,
        "k": 5,
        "model_id": DEFAULT_MODEL.model_id,
        "model_version": DEFAULT_MODEL.version,
        "collections": [a.collection_id],
        "filtered": True,
        "levels": ["public", "authenticated"],
        "groups": ["hr"],
    }

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await conn.execute(text("SET LOCAL plan_cache_mode = force_custom_plan"))
        plan = (
            await conn.execute(text("EXPLAIN (FORMAT JSON) " + NEAREST_SQL), params)
        ).scalar_one()

    nodes = list(_plan_nodes(plan[0]["Plan"]))
    relations = {node["Relation Name"] for node in nodes if "Relation Name" in node}
    removed = [node["Subplans Removed"] for node in nodes if "Subplans Removed" in node]
    assert relations == {partition_name(a.org_id)}, f"the plan scans {sorted(relations)}"
    assert removed == [], "the plan pruned partitions at executor start, not at plan time"


async def test_app_role_cannot_read_a_partition_directly(
    app_tx_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    for org in (two_orgs.a, two_orgs.b):
        partition = sql.Identifier(partition_name(org.org_id))
        for statement in (
            sql.SQL("SELECT count(*) FROM {}").format(partition),
            sql.SQL("DELETE FROM {}").format(partition),
        ):
            with app_tx_conn.transaction(), pytest.raises(psycopg.errors.InsufficientPrivilege):
                app_tx_conn.execute(
                    sql.SQL("SELECT set_config('app.current_org', {}, true)").format(
                        sql.Literal(str(org.org_id))
                    )
                )
                app_tx_conn.execute(statement)


def test_app_role_cannot_create_a_partition(app_tx_conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_tx_conn.execute(
            sql.SQL("CREATE TABLE {} PARTITION OF chunk_embeddings FOR VALUES IN ({})").format(
                sql.Identifier(partition_name(uuid.uuid4())), sql.Literal(str(uuid.uuid4()))
            )
        )


def test_chunk_embeddings_is_a_partitioned_tenant_table(migrator_conn: psycopg.Connection) -> None:
    kind, owner, enabled, forced = migrator_conn.execute(
        "SELECT relkind, pg_get_userbyid(relowner), relrowsecurity, relforcerowsecurity"
        " FROM pg_class WHERE relname = 'chunk_embeddings'"
    ).fetchone() or (None, None, None, None)
    privileges = {
        row[0]
        for row in migrator_conn.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants"
            " WHERE table_name = 'chunk_embeddings' AND grantee = %s",
            (APP,),
        )
    }
    parent_index = migrator_conn.execute(
        "SELECT x.relkind, am.amname FROM pg_class x JOIN pg_am am ON am.oid = x.relam"
        " WHERE x.relname = 'chunk_embeddings_embedding_hnsw'"
    ).fetchone()

    assert (kind, owner, enabled, forced) == ("p", MIGRATOR, True, True)
    assert privileges == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert parent_index == ("I", "hnsw")


def test_every_partition_has_an_hnsw_index(
    migrator_conn: psycopg.Connection, two_orgs: TwoOrgs
) -> None:
    partitions = _partitions(migrator_conn)
    without_hnsw = sorted(name for name, (_, _, hnsw) in partitions.items() if not hnsw)
    not_owned = sorted(name for name, (owner, _, _) in partitions.items() if owner != MIGRATOR)

    assert {partition_name(two_orgs.a.org_id), partition_name(two_orgs.b.org_id)} <= set(partitions)
    assert without_hnsw == [], f"partitions without an hnsw index: {without_hnsw}"
    assert not_owned == [], f"partitions not owned by {MIGRATOR}: {not_owned}"
    for name in partitions:
        granted = migrator_conn.execute(
            "SELECT count(*) FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a"
            " WHERE c.relname = %s AND a.grantee <> c.relowner",
            (name,),
        ).fetchone()
        assert granted == (0,), f"partition {name} grants a privilege"


async def test_no_default_partition_and_org_without_partition_gets_nothing(
    app_engine: AsyncEngine, migrator_conn: psycopg.Connection, bare_org: uuid.UUID
) -> None:
    bounds = [bound for _, bound, _ in _partitions(migrator_conn).values()]
    assert "DEFAULT" not in bounds

    with pytest.raises(DBAPIError) as error:
        await _insert_raw_vector(app_engine, bare_org, _unit(0))
    assert getattr(error.value.orig, "sqlstate", None) == "23514"  # no partition for the row

    tenant = TenantContext(org_id=bare_org, user_id=uuid.uuid4())
    async with app_engine.connect() as conn, tenant_transaction(conn, bare_org):
        assert await nearest(conn, tenant, _unit(0), MAX_K, model=DEFAULT_MODEL) == []


def test_create_vector_partition_is_idempotent_and_rejects_unknown_org(
    migrator_conn: psycopg.Connection, two_orgs: TwoOrgs, bare_org: uuid.UUID
) -> None:
    name = partition_name(bare_org)

    assert create_vector_partition(migrator_conn, two_orgs.a.org_id) is False
    assert create_vector_partition(migrator_conn, bare_org) is True
    owner, bound, hnsw = _partitions(migrator_conn)[name]
    assert (owner, bound, hnsw) == (MIGRATOR, f"FOR VALUES IN ('{bare_org}')", True)
    assert create_vector_partition(migrator_conn, bare_org) is False
    assert drop_vector_partition(migrator_conn, bare_org) is True
    assert drop_vector_partition(migrator_conn, bare_org) is False
    assert name not in _partitions(migrator_conn)

    unknown = uuid.uuid4()
    with pytest.raises(OrganizationNotFound):
        create_vector_partition(migrator_conn, unknown)
    assert partition_name(unknown) not in _partitions(migrator_conn)
    assert migrator_conn.execute("SELECT current_setting('app.current_org', true)").fetchone() in {
        ("",),
        (None,),
    }


def test_db_vector_partition_command(
    migrator_conn: psycopg.Connection,
    bare_org: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["db", "vector-partition", "--org", str(bare_org)]) == 0
    assert capsys.readouterr().out == f"vector partition created: {bare_org}\n"
    assert cli.main(["db", "vector-partition", "--org", str(bare_org)]) == 0
    assert capsys.readouterr().out == f"vector partition already present: {bare_org}\n"
    assert partition_name(bare_org) in _partitions(migrator_conn)

    unknown = uuid.uuid4()
    assert cli.main(["db", "vector-partition", "--org", str(unknown)]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "error: Organization not found\n")
    assert partition_name(unknown) not in _partitions(migrator_conn)


@pytest.fixture
def parent_locked(migrator_url: str) -> Iterator[None]:
    """Another session holds ACCESS SHARE on the parent, as a running vector query would."""
    with psycopg.connect(migrator_url) as blocker:
        blocker.execute("LOCK TABLE chunk_embeddings IN ACCESS SHARE MODE")
        try:
            yield
        finally:
            blocker.rollback()


def test_partition_ddl_gives_up_on_a_held_lock_instead_of_queueing(
    migrator_url: str,
    migrator_conn: psycopg.Connection,
    bare_org: uuid.UUID,
    parent_locked: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Safety net only: without the lock timeout the DDL would queue until this cancels it.
    migrator_conn.execute("SET statement_timeout = '20s'")
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=20000")

    started = time.monotonic()
    with pytest.raises(psycopg.errors.LockNotAvailable):
        create_vector_partition(migrator_conn, bare_org)
    assert time.monotonic() - started < 15
    assert migrator_conn.execute("SHOW lock_timeout").fetchone() == ("0",)

    assert cli.main(["db", "vector-partition", "--org", str(bare_org)]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "db vector-partition failed (LockNotAvailable)\n")
    assert partition_name(bare_org) not in _partitions(migrator_conn)


def test_partition_commands_refuse_non_migrator_role(
    app_conn: psycopg.Connection,
    migrator_conn: psycopg.Connection,
    two_orgs: TwoOrgs,
    bare_org: uuid.UUID,
) -> None:
    with pytest.raises(MigrationRoleError):
        create_vector_partition(app_conn, bare_org)
    with pytest.raises(MigrationRoleError):
        drop_vector_partition(app_conn, two_orgs.a.org_id)

    partitions = _partitions(migrator_conn)
    assert partition_name(bare_org) not in partitions
    assert partition_name(two_orgs.a.org_id) in partitions
