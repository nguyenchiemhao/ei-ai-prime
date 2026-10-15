"""Valkey side of the isolation suite: no key may exist outside an Organization's prefix."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis import asyncio as aioredis

from ei_ai.cache.keys import is_tenant_key
from support.tenants import OrgRows


async def non_tenant_keys(client: aioredis.Redis) -> list[str]:
    """Every key of the configured database that does not start with ``org:<uuid>:``.

    Later stories that cache anything call this after exercising their code (see README,
    "Writing isolation tests"); a key written around ``TenantCache`` shows up here.
    """
    keys = [os.fsdecode(key) async for key in client.scan_iter(count=1000)]
    return sorted(key for key in keys if not is_tenant_key(key))


async def assert_only_tenant_keys(client: aioredis.Redis, where: str, purge: bool = False) -> None:
    """Fail when any key outside the Organization prefix exists. Only the part of the key before
    the first colon is shown: the rest may be personal data (an address, an id). With ``purge``
    the keys are deleted first, so the failure is reported once, at the test that wrote them,
    and the tests after it start clean."""
    keys = await non_tenant_keys(client)
    if purge and keys:
        await client.delete(*keys)
    kinds = sorted({key.split(":", 1)[0] for key in keys})
    assert not keys, (
        f"{where}: {len(keys)} Valkey key(s) outside the org:<uuid>: prefix (key families: {kinds})"
    )


@asynccontextmanager
async def open_valkey() -> AsyncIterator[aioredis.Redis]:
    """A client for the Valkey of the test environment (``VALKEY_URL``)."""
    client = aioredis.from_url(os.environ["VALKEY_URL"])
    try:
        yield client
    finally:
        await client.aclose()


KeyState = dict[str, tuple[bytes | None, bool]]


async def snapshot_org_keys(client: aioredis.Redis, org: OrgRows) -> KeyState:
    """Every Valkey key of one Organization with its serialised value and whether it expires
    (the remaining time changes by itself, so only its presence is compared)."""
    state: KeyState = {}
    async for key in client.scan_iter(match=f"org:{org.org_id}:*", count=1000):
        state[os.fsdecode(key)] = (await client.dump(key), await client.ttl(key) >= 0)
    return state


async def assert_org_keys_unchanged(
    client: aioredis.Redis, org: OrgRows, before: KeyState, where: str
) -> None:
    """A call as another Organization may not create, change or delete this one's keys: a valid
    ``org:<uuid>:`` prefix is not enough when the uuid is someone else's."""
    assert await snapshot_org_keys(client, org) == before, (
        f"{where}: Valkey keys of Organization {org.label} changed"
    )
