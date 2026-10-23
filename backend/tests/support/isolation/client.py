"""The app under test: the production ``create_app`` with two known callers.

Test-only probe routers (the suite's self-tests) are added through ``extra_routers`` on the
instance built here; they are never part of ``create_app`` itself.
"""

import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.api.csrf import CSRF_COOKIE, CSRF_HEADER
from ei_ai.auth.principal import Principal
from ei_ai.crypto.cipher import OrgCipher
from ei_ai.jobs.envelope import JobEnvelope
from ei_ai.main import create_app
from ei_ai.readiness import Readiness
from ei_ai.storage.files import OrgFileStore
from support.crypto import TEST_MASTER_KEY
from support.identity import StaticBearerVerifier
from support.tenants import TwoOrgs

TOKENS = {"A": "token-a", "B": "token-b"}

# Every call passes the CSRF check, so state-changing public routes (POST /auth/*) reach their
# handler instead of stopping at the middleware's 403.
_CSRF_TOKEN = "isolation-csrf-token"
CSRF_HEADERS = {"Cookie": f"{CSRF_COOKIE}={_CSRF_TOKEN}", CSRF_HEADER: _CSRF_TOKEN}


async def _ok() -> None:
    return None


class RecordingRunner:
    """Stands in for the ingestion runner: it records the envelopes and runs nothing, so no job
    changes rows between the snapshots of a check."""

    def __init__(self) -> None:
        self.submitted: list[JobEnvelope] = []

    def submit(self, envelope: JobEnvelope) -> None:
        self.submitted.append(envelope)

    async def close(self) -> None:
        return None


def build_app(
    engine: AsyncEngine,
    orgs: TwoOrgs,
    extra_routers: Sequence[APIRouter] = (),
    storage_root: Path | None = None,
) -> FastAPI:
    """Both Organizations' users can authenticate (``token-a``, ``token-b``); readiness is ok.
    Originals go encrypted to ``storage_root`` (a temporary directory when none is given) and
    ingestion jobs are recorded, not run."""
    principals = {
        TOKENS[rows.label]: Principal(user_id=rows.user_id, org_id=rows.org_id)
        for rows in (orgs.a, orgs.b)
    }
    app = create_app(
        readiness=Readiness(database=_ok, valkey=_ok),
        identity_verifiers=(StaticBearerVerifier(principals),),
        engine=engine,
        file_store=OrgFileStore(
            storage_root or Path(tempfile.mkdtemp()), OrgCipher(TEST_MASTER_KEY)
        ),
    )
    app.state.ingestion_runner = RecordingRunner()
    for router in extra_routers:
        app.include_router(router)
    return app


@asynccontextmanager
async def isolation_client(
    engine: AsyncEngine, orgs: TwoOrgs, extra_routers: Sequence[APIRouter] = ()
) -> AsyncIterator[httpx.AsyncClient]:
    with tempfile.TemporaryDirectory() as storage_root:
        app = build_app(engine, orgs, extra_routers, Path(storage_root))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=CSRF_HEADERS
        ) as client:
            yield client
