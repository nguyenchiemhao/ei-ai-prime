"""The app under test: the production ``create_app`` with two known callers.

Test-only probe routers (the suite's self-tests) are added through ``extra_routers`` on the
instance built here; they are never part of ``create_app`` itself.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.principal import Principal
from ei_ai.main import create_app
from ei_ai.readiness import Readiness
from support.identity import StaticBearerVerifier
from support.tenants import TwoOrgs

TOKENS = {"A": "token-a", "B": "token-b"}


async def _ok() -> None:
    return None


def build_app(
    engine: AsyncEngine, orgs: TwoOrgs, extra_routers: Sequence[APIRouter] = ()
) -> FastAPI:
    """Both Organizations' users can authenticate (``token-a``, ``token-b``); readiness is ok."""
    principals = {
        TOKENS[rows.label]: Principal(user_id=rows.user_id, org_id=rows.org_id)
        for rows in (orgs.a, orgs.b)
    }
    app = create_app(
        readiness=Readiness(database=_ok, valkey=_ok),
        identity_verifiers=(StaticBearerVerifier(principals),),
        engine=engine,
    )
    for router in extra_routers:
        app.include_router(router)
    return app


@asynccontextmanager
async def isolation_client(
    engine: AsyncEngine, orgs: TwoOrgs, extra_routers: Sequence[APIRouter] = ()
) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(engine, orgs, extra_routers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
