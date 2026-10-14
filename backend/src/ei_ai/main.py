"""FastAPI application factory."""

import logging
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.api import health, organization
from ei_ai.auth.principal import IdentityVerifier
from ei_ai.db.engine import create_app_engine
from ei_ai.readiness import Readiness, build_readiness
from ei_ai.settings import Settings

logger = logging.getLogger("uvicorn.error")


def create_app(
    readiness: Readiness | None = None,
    identity_verifiers: Sequence[IdentityVerifier] = (),
    engine: AsyncEngine | None = None,
) -> FastAPI:
    """Build the app. Without ``readiness`` the settings are read from the environment at startup
    (fail fast, error names the variable only) and, unless given, the database engine is created
    there and disposed at shutdown.

    ``identity_verifiers`` decide who is calling (D32). The production app has none yet, so every
    tenant route answers 401; FND-05 (admin session) and WGT-03 (Channel JWT) add theirs.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned_engine: AsyncEngine | None = None
        if readiness is None:
            settings = Settings.from_env(os.environ)
            app.state.readiness = build_readiness(settings)
            if engine is None:
                owned_engine = app.state.engine = create_app_engine(settings)
            logger.info("ei-ai api starting: environment=%s", settings.environment)
        try:
            yield
        finally:
            if owned_engine is not None:
                await owned_engine.dispose()

    app = FastAPI(title="ei-ai", version="0.0.0", lifespan=lifespan)
    app.state.readiness = readiness
    app.state.engine = engine
    app.state.identity_verifiers = tuple(identity_verifiers)
    app.include_router(health.router)
    app.include_router(organization.router)
    return app


app = create_app()
