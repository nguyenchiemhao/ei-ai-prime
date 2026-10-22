"""The vector partition of each Organization (migrator plane, synchronous psycopg).

Creating a partition needs ownership of ``chunk_embeddings``, so only the owner role runs these
commands (``ei-ai db vector-partition`` in the ``migrate`` service); the application role never
gets DDL rights or a grant on a partition. Only ``ei_ai/cli.py`` imports this module under
``src`` (``tests/test_vector_partition_imports.py``): it takes a raw Organization id, which on the
tenant plane could come from a client.

Both commands accept a ``uuid.UUID`` object only. The partition identifier (``org_id.hex``) and
the ``FOR VALUES IN`` literal (``str(org_id)``) are derived from that object and composed with
``psycopg.sql``, never taken from a caller's string. Nothing here logs. The DDL waits at most
5 s for its lock on the parent, then fails with ``LockNotAvailable``.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql

from ei_ai.db.migrations.roles import check_migration_role

PARENT = "chunk_embeddings"

_ROLE = "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user"
_ORGANIZATION_VISIBLE = "SELECT EXISTS (SELECT 1 FROM organizations WHERE id = %s)"
_PARTITION_EXISTS = (
    "SELECT EXISTS (SELECT 1 FROM pg_inherits h JOIN pg_class c ON c.oid = h.inhrelid"
    " WHERE h.inhparent = 'chunk_embeddings'::regclass AND c.relname = %s)"
)
_HAS_HNSW_INDEX = (
    "SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class x ON x.oid = i.indexrelid"
    " JOIN pg_am am ON am.oid = x.relam"
    " WHERE i.indrelid = to_regclass(%s) AND am.amname = 'hnsw')"
)


class OrganizationNotFound(Exception):
    """No Organization with this id exists. The message is safe to print."""

    def __init__(self) -> None:
        super().__init__("Organization not found")


def partition_name(org_id: uuid.UUID) -> str:
    """``chunk_embeddings_<32 hex characters>`` (49 characters, below the 63-byte limit)."""
    if not isinstance(org_id, uuid.UUID):
        raise TypeError(f"org_id must be a uuid.UUID, got {type(org_id).__name__}")
    return f"{PARENT}_{org_id.hex}"


@contextmanager
def _owner_transaction(conn: psycopg.Connection) -> Iterator[None]:
    """One transaction on an idle connection whose role passes ``check_migration_role``.

    The connection must be idle: inside an open transaction ``transaction()`` would only create
    a savepoint, and a transaction-local ``app.current_org`` would outlive it.
    """
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError("vector partition commands need an idle connection")
    with conn.transaction():
        row = conn.execute(_ROLE).fetchone()
        if row is None:
            raise RuntimeError("the connection role was not found")
        name, is_superuser = row
        check_migration_role(name, is_superuser=is_superuser)
        # The DDL needs ACCESS EXCLUSIVE on the parent. Queued behind a long query, it would
        # block every Organization's vector queries; give up instead (LockNotAvailable).
        conn.execute("SET LOCAL lock_timeout = '5s'")
        yield


def _exists(conn: psycopg.Connection, name: str) -> bool:
    row = conn.execute(_PARTITION_EXISTS, (name,)).fetchone()
    return bool(row and row[0])


def create_vector_partition(conn: psycopg.Connection, org_id: uuid.UUID) -> bool:
    """Create the Organization's partition unless it exists; return whether it was created.

    The Organization row must be visible in its own tenant context (else ``OrganizationNotFound``).
    pgvector builds the partition's HNSW index from the partitioned index on the parent; should
    that ever not happen, ``<partition>_hnsw`` is created here (R28), so every partition ends
    with its own HNSW graph.
    """
    name = partition_name(org_id)
    with _owner_transaction(conn):
        conn.execute("SELECT set_config('app.current_org', %s, true)", (str(org_id),))
        visible = conn.execute(_ORGANIZATION_VISIBLE, (org_id,)).fetchone()
        if not (visible and visible[0]):
            raise OrganizationNotFound()
        created = not _exists(conn, name)
        if created:
            conn.execute(
                sql.SQL("CREATE TABLE {} PARTITION OF {} FOR VALUES IN ({})").format(
                    sql.Identifier(name), sql.Identifier(PARENT), sql.Literal(str(org_id))
                )
            )
        hnsw = conn.execute(_HAS_HNSW_INDEX, (name,)).fetchone()
        if not (hnsw and hnsw[0]):
            conn.execute(
                sql.SQL("CREATE INDEX {} ON {} USING hnsw (embedding vector_cosine_ops)").format(
                    sql.Identifier(f"{name}_hnsw"), sql.Identifier(name)
                )
            )
    return created


def drop_vector_partition(conn: psycopg.Connection, org_id: uuid.UUID) -> bool:
    """Drop the Organization's partition (and its vectors) if present; return whether it was."""
    name = partition_name(org_id)
    with _owner_transaction(conn):
        if not _exists(conn, name):
            return False
        conn.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(name)))
    return True
