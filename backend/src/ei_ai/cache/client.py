"""The Valkey client that application code passes to ``TenantCache``."""

from redis import asyncio as aioredis

DEFAULT_TIMEOUT_SECONDS = 2.0


def create_valkey_client(
    valkey_url: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> aioredis.Redis:
    """A client with timeouts that returns bytes (what ``TenantCache.get`` expects). Create it once
    (for example at startup, with ``Settings.valkey_url``), close it with ``await client.aclose()``,
    and pass it to ``TenantCache(client, tenant)``; never write to it directly."""
    return aioredis.from_url(
        valkey_url, socket_connect_timeout=timeout_seconds, socket_timeout=timeout_seconds
    )
