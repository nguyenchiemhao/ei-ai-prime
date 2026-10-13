import os
from unittest.mock import Mock

import psycopg
import pytest

from stack_spike.tenant import tenant_transaction

pytestmark = pytest.mark.db


class _Boom(Exception):
    pass


@pytest.mark.parametrize(
    "bad_org_id", ["not-a-uuid", "0b9c1c3e-5f0a-4a52-9a53-2c0f1f6f7a11", 42, None]
)
def test_rejects_non_uuid_org_id(bad_org_id):
    conn = Mock(spec=[])  # any database call would raise AttributeError

    with pytest.raises(TypeError):
        with tenant_transaction(conn, bad_org_id):
            pass


def test_tenant_context_is_cleared_after_transaction(app_conn: psycopg.Connection, orgs):
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        assert conn.execute("SELECT count(*) FROM documents").fetchone() == (2,)

    # Same connection, no context: must see nothing and must not raise on the leftover ''
    # setting (pool safety and the NULLIF pitfall).
    assert app_conn.execute("SELECT count(*) FROM documents").fetchone() == (0,)


def test_tenant_context_is_transaction_local_after_rollback(app_conn: psycopg.Connection, orgs):
    with pytest.raises(_Boom):
        with tenant_transaction(app_conn, orgs.org_a):
            raise _Boom

    assert app_conn.execute("SELECT count(*) FROM documents").fetchone() == (0,)
    setting = app_conn.execute("SELECT current_setting('app.current_org', true)").fetchone()[0]
    assert setting in (None, "")


def test_rejects_nested_tenant_transaction(app_conn: psycopg.Connection, orgs):
    # A nested call would become a SAVEPOINT, and set_config(..., true) survives RELEASE SAVEPOINT,
    # so the inner tenant would leak into the rest of the outer block.
    with tenant_transaction(app_conn, orgs.org_a) as conn:
        with pytest.raises(RuntimeError):
            with tenant_transaction(conn, orgs.org_b):
                pass

        # The outer context is untouched: still org A only.
        assert conn.execute("SELECT count(*) FROM documents").fetchone() == (2,)
        titles = conn.execute("SELECT title FROM documents ORDER BY title").fetchall()
        assert titles == [("A1",), ("A2",)]


def test_rejects_tenant_transaction_inside_already_open_transaction(orgs):
    # A non-autocommit connection opens a transaction at its first statement.
    with psycopg.connect(os.environ["POC_APP_DSN"]) as conn:
        conn.execute("SELECT 1")

        with pytest.raises(RuntimeError):
            with tenant_transaction(conn, orgs.org_a):
                pass
