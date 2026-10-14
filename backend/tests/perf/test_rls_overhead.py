"""NFR: RLS adds at most 1 ms per query, or at most 10 % for queries of 10 ms or more.

Owner decision 2026-10-14 for a 100 000-row table, measured once; see ``support.overhead``.

Run with ``npm run backend -- bench-rls`` (excluded from the unit and integration runs).

Two identical temporary tables hold 100 000 rows over 10 Organizations, with the same primary key
and index. One has ENABLE + FORCE RLS and the production ``tenant_isolation`` policy (NULLIF form),
the other none. Both are queried by the same role, in the same kind of tenant transaction (so
``app.current_org`` is set in both and only the policy differs). Each query shape runs 20 warm-up
and 200 measured ``EXPLAIN (ANALYZE, FORMAT JSON)`` executions per table, alternating between the
two tables to spread drift; the rule is applied to the medians of the Execution Time.
Planning time (where RLS adds its qualifier) is printed for information.
"""

import hashlib
import json
import os
import statistics
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.migrations.rls import tenant_rls_statements
from ei_ai.db.tenant import tenant_transaction
from support.overhead import overhead_percent, within_rls_budget

pytestmark = pytest.mark.benchmark

ORGS = 10
ROWS_PER_ORG = 10_000
WARMUP = 20
RUNS = 200
TABLES = {"on": "rls_bench_on", "off": "rls_bench_off"}


def _org(k: int) -> uuid.UUID:
    return uuid.UUID(bytes=hashlib.md5(f"org-{k}".encode()).digest())


def _row(k: int, n: int) -> uuid.UUID:
    return uuid.UUID(bytes=hashlib.md5(f"row-{k}-{n}".encode()).digest())


@dataclass(frozen=True)
class Shape:
    name: str
    sql: str  # {table} is replaced; constants are literals because EXPLAIN takes no parameters


SHAPES = (
    Shape(
        "org-scoped aggregate",
        f"SELECT count(*), max(name) FROM {{table}} WHERE org_id = '{_org(3)}'",
    ),
    Shape(
        "org-scoped page (ORDER BY id LIMIT 50)",
        f"SELECT id, name FROM {{table}} WHERE org_id = '{_org(3)}' ORDER BY id LIMIT 50",
    ),
    Shape("point lookup by id", f"SELECT * FROM {{table}} WHERE id = '{_row(3, 5000)}'"),
)


@pytest.fixture
async def bench_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=1, max_overflow=0
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def _create_tables(conn: AsyncConnection) -> None:
    for table in TABLES.values():
        await conn.execute(
            text(
                f"CREATE TEMP TABLE {table} (org_id uuid NOT NULL, id uuid NOT NULL,"
                " name text NOT NULL, payload text NOT NULL, PRIMARY KEY (org_id, id))"
            )
        )
        await conn.execute(text(f"CREATE INDEX ON {table} (id)"))
    for statement in tenant_rls_statements(TABLES["on"]):
        await conn.execute(text(statement))
    await conn.commit()


async def _load(conn: AsyncConnection) -> None:
    for k in range(ORGS):
        for table in TABLES.values():
            async with tenant_transaction(conn, _org(k)):
                await conn.execute(
                    text(
                        f"INSERT INTO {table} SELECT '{_org(k)}'::uuid,"
                        f" md5('row-{k}-' || g)::uuid, 'name-' || g, repeat('x', 100)"
                        f" FROM generate_series(1, {ROWS_PER_ORG}) g"
                    )
                )
    for table in TABLES.values():
        await conn.execute(text(f"ANALYZE {table}"))
    await conn.commit()


async def _explain(conn: AsyncConnection, sql: str, org: uuid.UUID) -> tuple[float, float]:
    """(execution ms, planning ms) of one EXPLAIN ANALYZE inside a tenant transaction."""
    async with tenant_transaction(conn, org):
        result = (await conn.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"))).scalar_one()
    document = json.loads(result) if isinstance(result, str) else result
    return float(document[0]["Execution Time"]), float(document[0]["Planning Time"])


async def _measure(conn: AsyncConnection, shape: Shape) -> dict[str, list[tuple[float, float]]]:
    org = _org(3)
    samples: dict[str, list[tuple[float, float]]] = {"on": [], "off": []}
    for i in range(WARMUP + RUNS):
        order = ("on", "off") if i % 2 == 0 else ("off", "on")
        for variant in order:
            measured = await _explain(conn, shape.sql.format(table=TABLES[variant]), org)
            if i >= WARMUP:
                samples[variant].append(measured)
    return samples


async def test_rls_overhead_on_100k_rows_is_within_budget(bench_engine: AsyncEngine) -> None:
    rows = []
    async with bench_engine.connect() as conn:
        server = (await conn.execute(text("SHOW server_version"))).scalar_one()
        await conn.rollback()
        await _create_tables(conn)
        await _load(conn)
        count = (await conn.execute(text(f"SELECT count(*) FROM {TABLES['off']}"))).scalar_one()
        assert count == ORGS * ROWS_PER_ORG
        await conn.rollback()  # tenant_transaction needs an idle connection
        for shape in SHAPES:
            samples = await _measure(conn, shape)
            exec_off = statistics.median([e for e, _ in samples["off"]])
            exec_on = statistics.median([e for e, _ in samples["on"]])
            plan_off = statistics.median([p for _, p in samples["off"]])
            plan_on = statistics.median([p for _, p in samples["on"]])
            rows.append((shape.name, exec_off, exec_on, plan_off, plan_on))

    print(f"\nRLS overhead, PostgreSQL {server}, {ORGS * ROWS_PER_ORG} rows")
    print(f"{WARMUP} warm-up + {RUNS} measured runs per table and shape; medians in ms")
    header = ("shape", "exec off", "exec on", "added ms", "overhead", "plan off", "plan on")
    print(f"{header[0]:42}" + "".join(f" {column:>9}" for column in header[1:]))
    for name, exec_off, exec_on, plan_off, plan_on in rows:
        overhead = overhead_percent(exec_off, exec_on)
        print(
            f"{name:42} {exec_off:9.4f} {exec_on:9.4f} {exec_on - exec_off:9.4f} {overhead:8.1f}% "
            f"{plan_off:9.4f} {plan_on:9.4f}"
        )
    for name, exec_off, exec_on, _, _ in rows:
        added = exec_on - exec_off
        assert within_rls_budget(exec_off, exec_on), f"{name}: RLS adds {added:.3f} ms"
