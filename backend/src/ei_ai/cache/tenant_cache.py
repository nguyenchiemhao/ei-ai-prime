"""A Valkey client bound to one Organization. No method takes a raw key."""

from typing import cast

from redis import asyncio as aioredis

from ei_ai.cache.keys import tenant_key
from ei_ai.jobs.envelope import JobContext
from ei_ai.tenancy.context import TenantContext


def _require_ttl(ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive: business keys always expire")


class TenantCache:
    """Rate limits and counters per Organization (there is no answer cache, D58).

    It is built from the verified context itself, never from an id: ``TenantCache(client, tenant)``
    in a route (the ``TenantContext`` that ``require_tenant`` returns) or
    ``TenantCache(client, ctx)`` in a job (its ``JobContext``). An ``org_id`` from a header, a
    body or model output cannot be passed (D32), and both context types are built only by the
    code that verified the identity (a test fails on any other construction). Every key goes
    through :func:`ei_ai.cache.keys.tenant_key`; nothing is logged.
    """

    def __init__(self, client: aioredis.Redis, tenant: TenantContext | JobContext) -> None:
        if not isinstance(tenant, TenantContext | JobContext):
            raise TypeError(
                "TenantCache needs the verified TenantContext or JobContext,"
                f" got {type(tenant).__name__}"
            )
        self._client = client
        self._org_id = tenant.org_id

    def _key(self, namespace: str, parts: tuple[str, ...]) -> str:
        return tenant_key(self._org_id, namespace, *parts)

    async def get(self, namespace: str, *parts: str) -> bytes | None:
        # The client must not decode responses (the default): values come back as bytes.
        return cast(bytes | None, await self._client.get(self._key(namespace, parts)))

    async def set(self, namespace: str, *parts: str, value: bytes | str, ttl_seconds: int) -> None:
        _require_ttl(ttl_seconds)
        await self._client.set(self._key(namespace, parts), value, ex=ttl_seconds)

    async def delete(self, namespace: str, *parts: str) -> None:
        await self._client.delete(self._key(namespace, parts))

    async def incr(self, namespace: str, *parts: str, ttl_seconds: int) -> int:
        """Add one to a counter; the first increment starts its ``ttl_seconds`` window."""
        _require_ttl(ttl_seconds)
        key = self._key(namespace, parts)
        async with self._client.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, ttl_seconds, nx=True)
            results = await pipeline.execute()
        return int(results[0])
