"""Readiness checks for the backing services. Failures report component names only."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import psycopg
from redis import asyncio as aioredis

from ei_ai.settings import Settings

logger = logging.getLogger("uvicorn.error")

CHECK_TIMEOUT_SECONDS = 2.0
Status = Literal["ok", "unavailable"]
Check = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class Readiness:
    """One async check per component; a check returns normally when the component is usable."""

    database: Check
    valkey: Check


async def check_database(database_url: str) -> None:
    async with await psycopg.AsyncConnection.connect(
        database_url, connect_timeout=int(CHECK_TIMEOUT_SECONDS)
    ) as connection:
        await connection.execute("SELECT 1")


async def check_valkey(valkey_url: str) -> None:
    client = aioredis.from_url(
        valkey_url,
        socket_connect_timeout=CHECK_TIMEOUT_SECONDS,
        socket_timeout=CHECK_TIMEOUT_SECONDS,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


def build_readiness(settings: Settings) -> Readiness:
    return Readiness(
        database=lambda: check_database(settings.database_url),
        valkey=lambda: check_valkey(settings.valkey_url),
    )


async def _run(name: str, check: Check) -> Status:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS + 1)
    except Exception as error:
        # Component name and exception class only: messages can carry DSNs and passwords (D52).
        logger.warning("readiness check failed: component=%s error=%s", name, type(error).__name__)
        return "unavailable"
    return "ok"


async def run_checks(readiness: Readiness) -> dict[str, Status]:
    database, valkey = await asyncio.gather(
        _run("database", readiness.database), _run("valkey", readiness.valkey)
    )
    return {"database": database, "valkey": valkey}
