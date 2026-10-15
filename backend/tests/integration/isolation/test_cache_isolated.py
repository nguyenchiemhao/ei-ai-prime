"""AC4: every business cache key contains the Organization, against a real Valkey.

Organization ids are random and the keys of this module are removed afterwards, so the tests do
not depend on, or disturb, other data in the database.
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from redis import asyncio as aioredis

from ei_ai.cache.keys import TENANT_KEY_PATTERN
from ei_ai.cache.tenant_cache import TenantCache
from ei_ai.tenancy.context import TenantContext
from support.isolation.valkey import assert_only_tenant_keys, non_tenant_keys


def _tenant(org_id: uuid.UUID) -> TenantContext:
    return TenantContext(org_id=org_id, user_id=uuid.uuid4())


RAW_KEY = "probe:raw"


@pytest.fixture
async def orgs(valkey: aioredis.Redis) -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    a, b = uuid.uuid4(), uuid.uuid4()
    try:
        yield a, b
    finally:
        for org in (a, b):
            async for key in valkey.scan_iter(match=f"org:{org}:*"):
                await valkey.delete(key)


async def test_same_logical_key_is_separate_per_org(
    valkey: aioredis.Redis, orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    cache_a, cache_b = TenantCache(valkey, _tenant(orgs[0])), TenantCache(valkey, _tenant(orgs[1]))

    await cache_a.set("rate-limit", "widget", value="from-a", ttl_seconds=30)

    assert await cache_b.get("rate-limit", "widget") is None
    await cache_b.set("rate-limit", "widget", value="from-b", ttl_seconds=30)
    assert await cache_a.get("rate-limit", "widget") == b"from-a"
    assert await cache_b.get("rate-limit", "widget") == b"from-b"


async def test_keys_written_by_the_wrapper_are_org_prefixed_and_expire(
    valkey: aioredis.Redis, orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    cache = TenantCache(valkey, _tenant(orgs[0]))

    await cache.set("rate-limit", "ip", "2001:db8::1", value="x", ttl_seconds=30)
    assert await cache.incr("counter", "logins", ttl_seconds=30) == 1
    assert await cache.incr("counter", "logins", ttl_seconds=30) == 2

    keys = sorted(os.fsdecode(key) for key in await valkey.keys(f"org:{orgs[0]}:*"))
    assert keys == [
        f"org:{orgs[0]}:counter:logins",
        f"org:{orgs[0]}:rate-limit:ip:2001%3Adb8%3A%3A1",
    ]
    assert all(TENANT_KEY_PATTERN.match(key) for key in keys)
    assert [await valkey.ttl(key) for key in keys] == [pytest.approx(30, abs=5)] * 2
    assert await valkey.keys(f"org:{orgs[1]}:*") == []


async def test_every_key_in_valkey_is_tenant_prefixed(
    valkey: aioredis.Redis, orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    for org in orgs:
        cache = TenantCache(valkey, _tenant(org))
        await cache.set("rate-limit", "k", value="v", ttl_seconds=30)
        await cache.incr("counter", "k", ttl_seconds=30)

    assert await non_tenant_keys(valkey) == []


async def test_scan_check_fails_on_a_raw_key(valkey: aioredis.Redis) -> None:
    await valkey.set(RAW_KEY, "x", ex=30)
    try:
        assert RAW_KEY in await non_tenant_keys(valkey)
        with pytest.raises(
            AssertionError, match=r"1 Valkey key\(s\) outside the org:<uuid>: prefix"
        ):
            await assert_only_tenant_keys(valkey, "after the test")
    finally:
        await valkey.delete(RAW_KEY)


async def test_a_raw_key_is_reported_once_and_removed(valkey: aioredis.Redis) -> None:
    # Reported at the test that created it, then gone, so the later tests do not all error.
    await valkey.set(RAW_KEY, "x", ex=30)
    try:
        with pytest.raises(
            AssertionError, match=r"1 Valkey key\(s\) outside the org:<uuid>: prefix"
        ):
            await assert_only_tenant_keys(valkey, "after the test", purge=True)

        assert await non_tenant_keys(valkey) == []
        await assert_only_tenant_keys(valkey, "next test", purge=True)
    finally:
        await valkey.delete(RAW_KEY)
