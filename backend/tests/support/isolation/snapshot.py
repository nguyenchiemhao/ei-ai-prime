"""Snapshot of everything an Organization owns, to prove a call changed nothing of it."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import DELETE_ORDER, OrgRows, tenant_key_column

Snapshot = dict[str, list[tuple[object, ...]]]


async def snapshot_org(engine: AsyncEngine, org: OrgRows) -> Snapshot:
    """Every row of every tenant table, read in the Organization's own tenant transaction."""
    snapshot: Snapshot = {}
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        for table in DELETE_ORDER:
            # The explicit Organization filter is layer 1; row-level security is layer 2.
            query = f"SELECT * FROM {table} WHERE {tenant_key_column(table)} = :org ORDER BY id"
            result = await conn.execute(text(query), {"org": org.org_id})
            snapshot[table] = [tuple(row) for row in result]
    return snapshot
