"""AC4-A: the core infrastructure services started by one compose command are usable."""

import os

import psycopg
import pytest
import redis

pytestmark = pytest.mark.stack


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_postgres_has_pgvector_extension():
    with psycopg.connect(os.environ["POC_ADMIN_DSN"], autocommit=True) as conn:
        row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        version = row.fetchone()

    assert version is not None, "the vector extension is not installed"
    assert _version_tuple(version[0]) >= (0, 8)


def test_valkey_answers_ping():
    client = redis.Redis.from_url(os.environ["VALKEY_URL"])

    assert client.ping() is True
