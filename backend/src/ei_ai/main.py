"""FastAPI application factory."""

import logging
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.api import auth, collections, csrf, documents, health, members, organization, workspaces
from ei_ai.api.csrf import CsrfMiddleware, origin_of
from ei_ai.api.no_store import NoStoreAuthMiddleware
from ei_ai.api.validation import install_validation_handler
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.principal import IdentityVerifier
from ei_ai.auth.rate_limit import RateLimiter
from ei_ai.auth.session_verifier import SessionCookieVerifier
from ei_ai.crypto.cipher import OrgCipher
from ei_ai.crypto.master_key import master_key_from_env
from ei_ai.db.engine import create_app_engine
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder, GatewayEmbedder
from ei_ai.knowledge.indexing.embedding_model import platform_embedding_ref
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runner import IngestionRunner
from ei_ai.model_gateway.factory import build_gateway
from ei_ai.model_gateway.gateway import ModelGateway
from ei_ai.rbac.declarations import install_permission_handler
from ei_ai.readiness import Readiness, build_readiness
from ei_ai.settings import ModelSettings, Settings
from ei_ai.storage.files import OrgFileStore

logger = logging.getLogger("uvicorn.error")


def create_app(
    readiness: Readiness | None = None,
    identity_verifiers: Sequence[IdentityVerifier] | None = None,
    engine: AsyncEngine | None = None,
    admin_base_url: str | None = None,
    sign_in_directory: SignInDirectory | None = None,
    rate_limiter: RateLimiter | None = None,
    environment: str | None = None,
    file_store: OrgFileStore | None = None,
    embedder: ChunkEmbedder | None = None,
) -> FastAPI:
    """Build the app. Without ``readiness`` the settings are read from the environment at startup
    (fail fast, error names the variable only); they configure the CSRF origin, the sign-in rate
    limit, the client address source and the session idle timeout, and, unless given, the
    database engine and the sign-in directory are created there and disposed at shutdown.

    ``identity_verifiers`` decide who is calling (D32). By default the admin session cookie
    (``SessionCookieVerifier``) is the only one; tests pass their own. WGT-03 adds the Channel JWT.
    The other arguments let tests supply the parts the settings would build.

    Document ingestion (EA-33) runs in this process: the runner, its progress board and the
    clock are created here, so tests without a lifespan have them too. ``file_store`` (EA-20's
    encrypted store of originals) defaults to ``OrgFileStore`` at ``FILE_STORAGE_ROOT`` with the
    master key of ``EI_AI_MASTER_KEY`` or ``EI_AI_MASTER_KEY_FILE`` (missing or malformed: startup
    aborts with a ``SettingsError`` naming the variable only); the runner is closed at shutdown
    before the engine is disposed.

    After a document is ingested, the runner indexes it with ``embedder`` (EA-35). Without one, a
    lifespan that reads the settings embeds through the Model Gateway with the platform embedding
    model (``EMBEDDING_MODEL_REF``; invalid: startup aborts) and closes that gateway after the
    runner; tests without a lifespan and without an embedder index nothing.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned_engine: AsyncEngine | None = None
        owned_directory: SignInDirectory | None = None
        owned_gateway: ModelGateway | None = None
        if readiness is None:
            settings = Settings.from_env(os.environ)
            # Before anything that needs disposing: a missing master key aborts startup here.
            if file_store is None:
                app.state.file_store = OrgFileStore(
                    Path(settings.file_storage_root), OrgCipher(master_key_from_env(os.environ))
                )
            if embedder is None:
                model_settings = ModelSettings.from_env(os.environ)
                embedding_ref = platform_embedding_ref(os.environ)
            app.state.readiness = build_readiness(settings)
            if engine is None:
                owned_engine = app.state.engine = create_app_engine(settings)
            if embedder is None:
                owned_gateway = build_gateway(model_settings, app.state.engine)
                app.state.embedder = GatewayEmbedder(owned_gateway, embedding_ref)
            if sign_in_directory is None:
                owned_directory = SignInDirectory(settings.signin_database_url)
                app.state.sign_in_directory = owned_directory
            _apply_settings(
                app, settings, admin_base_url, rate_limiter, identity_verifiers, environment
            )
            logger.info("ei-ai api starting: environment=%s", settings.environment)
        try:
            yield
        finally:
            await app.state.ingestion_runner.close()
            if owned_gateway is not None:
                await owned_gateway.aclose()
            if owned_directory is not None:
                await owned_directory.dispose()
            if owned_engine is not None:
                await owned_engine.dispose()

    app = FastAPI(title="ei-ai", version="0.0.0", lifespan=lifespan)
    app.state.readiness = readiness
    app.state.engine = engine
    app.state.sign_in_directory = sign_in_directory
    app.state.file_store = file_store
    app.state.embedder = embedder
    app.state.progress_board = ProgressBoard()
    app.state.clock = lambda: datetime.now(UTC)
    app.state.ingestion_runner = IngestionRunner(
        lambda: app.state.engine,
        lambda: app.state.file_store,
        app.state.progress_board,
        embedder=lambda: app.state.embedder,
    )
    app.state.identity_verifiers = (
        tuple(identity_verifiers)
        if identity_verifiers is not None
        else _session_verifiers(app, timedelta(seconds=Settings.session_idle_timeout_seconds))
    )
    # Settings defaults until the settings are read (tests passing readiness never read them).
    app.state.rate_limiter = rate_limiter or RateLimiter(Settings.auth_rate_limit_per_minute)
    app.state.trust_proxy_headers = Settings.trust_proxy_headers
    # Until the settings are read the CSRF check accepts no Origin (fail closed); if they cannot
    # be read (e.g. ADMIN_BASE_URL invalid in production) startup aborts and nothing is served.
    app.state.admin_origin = origin_of(admin_base_url) if admin_base_url else ""
    # Fail closed: only an explicit local/test environment lets forgot-password print a link.
    app.state.environment = environment or "production"
    app.state.admin_base_url = (admin_base_url or "").rstrip("/")
    install_validation_handler(app)
    install_permission_handler(app)
    auth.install_failure_handler(app)
    app.add_middleware(CsrfMiddleware, allowed_origin=lambda: app.state.admin_origin)
    # Outermost: it also marks the CSRF 403 and the validation 422 of /auth/* as no-store.
    app.add_middleware(NoStoreAuthMiddleware)
    app.include_router(auth.router)
    app.include_router(collections.router)
    app.include_router(csrf.router)
    app.include_router(documents.router)
    app.include_router(health.router)
    app.include_router(members.router)
    app.include_router(organization.router)
    app.include_router(workspaces.router)
    return app


def _session_verifiers(app: FastAPI, idle: timedelta) -> tuple[IdentityVerifier, ...]:
    return (SessionCookieVerifier(lambda: app.state.engine, idle),)


def _apply_settings(
    app: FastAPI,
    settings: Settings,
    admin_base_url: str | None,
    rate_limiter: RateLimiter | None,
    identity_verifiers: Sequence[IdentityVerifier] | None,
    environment: str | None,
) -> None:
    """The auth configuration from the settings: the single source of each value, except the
    parts the caller passed to ``create_app``."""
    base_url = (admin_base_url or settings.admin_base_url).rstrip("/")
    app.state.admin_origin = origin_of(base_url)
    app.state.admin_base_url = base_url
    app.state.environment = environment or settings.environment
    app.state.trust_proxy_headers = settings.trust_proxy_headers
    if rate_limiter is None:
        app.state.rate_limiter = RateLimiter(settings.auth_rate_limit_per_minute)
    if identity_verifiers is None:
        idle = timedelta(seconds=settings.session_idle_timeout_seconds)
        app.state.identity_verifiers = _session_verifiers(app, idle)


app = create_app()
