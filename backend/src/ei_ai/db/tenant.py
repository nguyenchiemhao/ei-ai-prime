"""Tenant context for database access (D46, layer 2).

Row-level security policies read ``app.current_org``; this module is the only place that sets it.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession


async def _driver_is_idle(conn: AsyncConnection) -> bool:
    raw = await conn.get_raw_connection()
    status = raw.driver_connection.info.transaction_status  # type: ignore[union-attr]
    return bool(status == psycopg.pq.TransactionStatus.IDLE)


@asynccontextmanager
async def tenant_transaction(
    conn: AsyncConnection, org_id: uuid.UUID
) -> AsyncIterator[AsyncConnection]:
    """Open a transaction whose queries are limited to one Organization by row-level security.

    The setting is transaction-local (``set_config(..., true)``), so it is cleared on commit and on
    rollback and can never leak to the next user of a pooled connection. ``SET LOCAL`` cannot take
    bind parameters, which is why ``set_config`` is used.

    The connection must be idle (no open transaction): inside an open transaction ``begin()`` only
    creates a SAVEPOINT, and a ``set_config(..., true)`` made in a savepoint survives its release,
    so the tenant would leak into the rest of the outer transaction. Nested use is rejected.

    ``org_id`` comes only from the verified identity (D32, D46): the ``Principal`` that
    ``ei_ai.tenancy.context.require_tenant`` returns, never a request body, query string or
    model output.
    """
    if not isinstance(org_id, uuid.UUID):
        raise TypeError(f"org_id must be a uuid.UUID, got {type(org_id).__name__}")
    if conn.in_transaction() or not await _driver_is_idle(conn):
        raise RuntimeError("tenant_transaction needs an idle connection (no open transaction)")
    async with conn.begin():
        await conn.execute(
            text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)}
        )
        yield conn


@asynccontextmanager
async def tenant_session(engine: AsyncEngine, org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """A session on one pooled connection, inside a tenant transaction.

    The transaction commits when the block ends normally and rolls back on an exception; the
    session joins it without committing it itself (``rollback_only``), so the tenant setting is
    always cleared with the transaction.
    """
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        session = AsyncSession(
            bind=conn, join_transaction_mode="rollback_only", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
