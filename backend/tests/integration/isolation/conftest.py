"""Valkey fixtures of the isolation suite.

Every test of the suite is followed by a scan of the whole Valkey database (and the first test is
preceded by one): a key that does not start with ``org:<uuid>:`` fails the test that was running
when it appeared, and is deleted, so one raw key is one failure. Routes and jobs under test write
only through ``TenantCache``.
"""

import os
from collections.abc import AsyncIterator

import pytest
from redis import asyncio as aioredis

from support.isolation.valkey import assert_only_tenant_keys

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
