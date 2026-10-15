"""The Valkey reachability check (readiness). It lives in the cache package so that no module
outside it needs to import a Valkey client."""

from redis import asyncio as aioredis


async def check_valkey(valkey_url: str, timeout_seconds: float) -> None:
    client = aioredis.from_url(
        valkey_url, socket_connect_timeout=timeout_seconds, socket_timeout=timeout_seconds
    )
    try:
        await client.ping()
    finally:
        await client.aclose()
