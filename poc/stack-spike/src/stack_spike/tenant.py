"""Tenant context for database access (D46, layer 2)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg


@contextmanager
def tenant_transaction(conn: psycopg.Connection, org_id: uuid.UUID) -> Iterator[psycopg.Connection]:
    """Open a transaction whose queries are limited to one Organization by row-level security.

    The setting is transaction-local (`set_config(..., true)`), so it is cleared on commit and on
    rollback and can never leak to the next user of a pooled connection. `SET LOCAL` cannot take
    bind parameters, which is why `set_config` is used.

    The connection must be idle (no open transaction): inside an open transaction `transaction()`
    only creates a SAVEPOINT, and a `set_config(..., true)` made in a savepoint survives its
    release, so the tenant would leak into the rest of the outer transaction. Nested use is
    rejected.

    In the product, `org_id` comes only from the verified token or session (D32, D46), never from
    request bodies, query strings or model output.
    """
    if not isinstance(org_id, uuid.UUID):
        raise TypeError(f"org_id must be a uuid.UUID, got {type(org_id).__name__}")
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError("tenant_transaction needs an idle connection (no open transaction)")
    with conn.transaction():
        conn.execute("SELECT set_config('app.current_org', %s, true)", (str(org_id),))
        yield conn
