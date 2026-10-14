"""Fixtures for the database integration tests (real PostgreSQL, application and owner roles)."""

import os
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.db.engine import to_sqlalchemy_url
from support.tenants import TwoOrgs, create_org_rows, purge_org_rows


@pytest.fixture
def migrator_url() -> str:
    return os.environ["MIGRATION_DATABASE_URL"]


@pytest.fixture
async def app_engine() -> AsyncIterator[AsyncEngine]:
    """Engine as ``ei_ai_app`` with a single pooled connection, so connection reuse is tested."""
    engine = create_async_engine(
        to_sqlalchemy_url(os.environ["DATABASE_URL"]),
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def app_conn() -> Iterator[psycopg.Connection]:
    """Connection as ``ei_ai_app`` (autocommit: no implicit transaction keeps a tenant context)."""
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


@pytest.fixture
def app_tx_conn() -> Iterator[psycopg.Connection]:
    """``ei_ai_app`` connection whose transaction is ALWAYS rolled back.

    For negative tests (DDL, writes without a tenant context): if the roles or policies ever
    regress and the forbidden statement succeeds, it is undone instead of damaging the shared DB.
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture
def migrator_conn(migrator_url: str) -> Iterator[psycopg.Connection]:
    """Owner-role connection (autocommit); inspection and negative tests only."""
    with psycopg.connect(migrator_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
async def two_orgs(app_engine: AsyncEngine) -> AsyncIterator[TwoOrgs]:
    """Two fresh Organizations (random ids), one row in every tenant table; removed afterwards."""
    a = await create_org_rows(app_engine, "A")
    b = await create_org_rows(app_engine, "B")
    try:
        yield TwoOrgs(a=a, b=b)
    finally:
        await purge_org_rows(app_engine, a, b)
