"""SQLAlchemy engine for the application role."""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.settings import Settings

# CLI commands fail fast on an unreachable host instead of waiting for the OS TCP timeout.
CLI_CONNECT_TIMEOUT_SECONDS = 5
_PLAIN = "postgresql://"
_DRIVER = "postgresql+psycopg://"


def to_sqlalchemy_url(url: str) -> str:
    """The URL with the psycopg 3 driver named (``postgresql://`` alone selects psycopg2).

    Raises ``ValueError`` for anything that is not PostgreSQL; the message never contains the URL.
    """
    if url.startswith(_PLAIN):
        return _DRIVER + url[len(_PLAIN) :]
    if url.startswith(_DRIVER):
        return url
    raise ValueError("database URL must start with postgresql://")


def to_libpq_url(url: str) -> str:
    """The URL without the SQLAlchemy driver name, for psycopg.connect and libpq."""
    return _PLAIN + url[len(_DRIVER) :] if url.startswith(_DRIVER) else url


def create_app_engine(settings: Settings) -> AsyncEngine:
    """Engine for ``ei_ai_app``. ``pool_pre_ping`` replaces dead connections; returned connections
    are rolled back (the default), which also clears any transaction-local tenant setting."""
    return create_async_engine(to_sqlalchemy_url(settings.database_url), pool_pre_ping=True)


def create_cli_engine(database_url: str) -> AsyncEngine:
    """Engine for ``ei_ai_app`` in a CLI command, with a connect timeout."""
    return create_async_engine(
        to_sqlalchemy_url(database_url),
        pool_pre_ping=True,
        connect_args={"connect_timeout": CLI_CONNECT_TIMEOUT_SECONDS},
    )


async def run_with_app_engine[T](
    database_url: str, work: Callable[[AsyncEngine], Awaitable[T]]
) -> T:
    """Run ``work`` with a fresh CLI engine and dispose of it afterwards (CLI commands)."""
    engine = create_cli_engine(database_url)
    try:
        return await work(engine)
    finally:
        await engine.dispose()
