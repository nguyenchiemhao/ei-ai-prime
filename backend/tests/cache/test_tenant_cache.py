"""``TenantCache``: every key it sends to Valkey carries the bound Organization (AC4)."""

import uuid
from typing import Any, cast

import pytest
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from ei_ai.cache.keys import TENANT_KEY_PATTERN
from ei_ai.cache.tenant_cache import TenantCache
from ei_ai.jobs.envelope import JobContext
from ei_ai.tenancy.context import TenantContext

ORG = uuid.uuid4()
OTHER = uuid.uuid4()


class _Pipeline:
    def __init__(self, client: "_FakeRedis") -> None:
        self._client = client
        self._queued: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __aenter__(self) -> "_Pipeline":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def incr(self, key: str) -> None:
        self._queued.append(("incr", (key,), {}))

    def expire(self, key: str, seconds: int, **options: bool) -> None:
        self._queued.append(("expire", (key, seconds), options))

    async def execute(self) -> list[Any]:
        return [
            await getattr(self._client, name)(*args, **kwargs)
            for name, args, kwargs in self._queued
        ]


class _FakeRedis:
    """Just enough of the Redis client; records every key it receives."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.keys_seen: list[str] = []

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)

    async def get(self, key: str) -> bytes | None:
        self.keys_seen.append(key)
        return self.values.get(key)

    async def set(self, key: str, value: bytes | str, ex: int | None = None) -> bool:
        self.keys_seen.append(key)
        self.values[key] = value.encode() if isinstance(value, str) else value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key: str) -> int:
        self.keys_seen.append(key)
        return 1 if self.values.pop(key, None) is not None else 0

    async def incr(self, key: str) -> int:
        self.keys_seen.append(key)
        self.values[key] = str(int(self.values.get(key, b"0")) + 1).encode()
        return int(self.values[key])

    async def expire(self, key: str, seconds: int, nx: bool = False) -> bool:
        self.keys_seen.append(key)
        if nx and key in self.ttls:
            return False
        self.ttls[key] = seconds
        return True


def _cache(fake: _FakeRedis, org: uuid.UUID = ORG) -> TenantCache:
    return TenantCache(cast(aioredis.Redis, fake), TenantContext(org_id=org, user_id=uuid.uuid4()))


async def test_set_then_get_round_trips_under_the_tenant_key() -> None:
    fake = _FakeRedis()
    cache = _cache(fake)

    await cache.set("rate-limit", "widget", "1", value="v", ttl_seconds=30)

    assert await cache.get("rate-limit", "widget", "1") == b"v"
    assert fake.ttls == {f"org:{ORG}:rate-limit:widget:1": 30}


async def test_two_organizations_do_not_share_a_logical_key() -> None:
    fake = _FakeRedis()
    await _cache(fake, ORG).set("x", "k", value=b"a", ttl_seconds=5)

    assert await _cache(fake, OTHER).get("x", "k") is None
    assert await _cache(fake, ORG).get("x", "k") == b"a"


async def test_delete_removes_only_the_own_key() -> None:
    fake = _FakeRedis()
    await _cache(fake, ORG).set("x", "k", value=b"a", ttl_seconds=5)
    await _cache(fake, OTHER).set("x", "k", value=b"b", ttl_seconds=5)

    await _cache(fake, ORG).delete("x", "k")

    assert await _cache(fake, ORG).get("x", "k") is None
    assert await _cache(fake, OTHER).get("x", "k") == b"b"


async def test_incr_counts_and_sets_the_expiry_once() -> None:
    fake = _FakeRedis()
    cache = _cache(fake)

    assert await cache.incr("rate-limit", "ip", ttl_seconds=60) == 1
    assert await cache.incr("rate-limit", "ip", ttl_seconds=60) == 2
    assert fake.ttls == {f"org:{ORG}:rate-limit:ip": 60}


@pytest.mark.parametrize("ttl", [0, -1])
async def test_a_business_key_needs_a_positive_ttl(ttl: int) -> None:
    cache = _cache(_FakeRedis())

    with pytest.raises(ValueError, match="ttl_seconds"):
        await cache.set("x", "k", value=b"a", ttl_seconds=ttl)
    with pytest.raises(ValueError, match="ttl_seconds"):
        await cache.incr("x", "k", ttl_seconds=ttl)


async def test_every_key_sent_to_the_client_is_tenant_prefixed() -> None:
    fake = _FakeRedis()
    cache = _cache(fake)

    await cache.set("a", "1", value="v", ttl_seconds=5)
    await cache.get("a", "1")
    await cache.incr("b", "x:y", ttl_seconds=5)
    await cache.delete("a", "1")

    assert fake.keys_seen
    assert all(TENANT_KEY_PATTERN.match(key) and f"org:{ORG}:" in key for key in fake.keys_seen)


@pytest.mark.parametrize("not_a_context", [ORG, str(ORG), None])
def test_only_a_verified_context_can_address_a_tenant(not_a_context: object) -> None:
    with pytest.raises(TypeError, match="verified TenantContext or JobContext"):
        TenantCache(cast(aioredis.Redis, _FakeRedis()), not_a_context)  # type: ignore[arg-type]


async def test_a_job_context_addresses_its_own_organization() -> None:
    fake = _FakeRedis()
    job = JobContext(org_id=ORG, session=cast(AsyncSession, None))

    await TenantCache(cast(aioredis.Redis, fake), job).set("x", "k", value="v", ttl_seconds=5)

    assert list(fake.values) == [f"org:{ORG}:x:k"]
