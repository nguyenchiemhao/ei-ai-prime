"""FastAPI application factory."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ei_ai.api import health
from ei_ai.readiness import Readiness, build_readiness
from ei_ai.settings import Settings

logger = logging.getLogger("uvicorn.error")


def create_app(readiness: Readiness | None = None) -> FastAPI:
    """Build the app. Without ``readiness`` the settings are read from the environment at startup
    (fail fast, error names the variable only)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if readiness is None:
            settings = Settings.from_env(os.environ)
            app.state.readiness = build_readiness(settings)
            logger.info("ei-ai api starting: environment=%s", settings.environment)
        yield

    app = FastAPI(title="ei-ai", version="0.0.0", lifespan=lifespan)
    app.state.readiness = readiness
    app.include_router(health.router)
    return app


app = create_app()
