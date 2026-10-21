"""Fixtures of the isolation suite: the callers hold every permission, and Valkey is scanned.

Every test of the suite is followed by a scan of the whole Valkey database (and the first test is
preceded by one): a key that does not start with ``org:<uuid>:`` fails the test that was running
when it appeared, and is deleted, so one raw key is one failure. Routes and jobs under test write
only through ``TenantCache``.
"""

import os
from collections.abc import AsyncIterator

import pytest
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine

from support.isolation.privileges import grant_every_permission
from support.isolation.valkey import assert_only_tenant_keys
from support.tenants import TwoOrgs, create_org_rows, purge_org_rows

_started: list[bool] = []  # the scan before a test runs once, for the first test of the run


@pytest.fixture
async def valkey() -> AsyncIterator[aioredis.Redis]:
    client = aioredis.from_url(os.environ["VALKEY_URL"])
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
async def only_tenant_keys_in_valkey(
    valkey: aioredis.Redis, request: pytest.FixtureRequest
) -> AsyncIterator[None]:
    if not _started:
        _started.append(True)
        await assert_only_tenant_keys(valkey, f"before {request.node.name}", purge=True)
    yield
    await assert_only_tenant_keys(valkey, f"after {request.node.name}", purge=True)


@pytest.fixture
async def two_orgs(app_engine: AsyncEngine) -> AsyncIterator[TwoOrgs]:
    """Two fresh Organizations whose fixture users hold every permission (Org Owner + Reviewer),
    so the isolation cases measure tenant isolation, not a missing role."""
    a = await create_org_rows(app_engine, "A")
    b = await create_org_rows(app_engine, "B")
    try:
        await grant_every_permission(app_engine, a)
        await grant_every_permission(app_engine, b)
        yield TwoOrgs(a=a, b=b)
    finally:
        await purge_org_rows(app_engine, a, b)
