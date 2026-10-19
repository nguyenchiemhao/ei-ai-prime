from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db import engine as engine_module
from ei_ai.db.engine import create_app_engine, to_libpq_url, to_sqlalchemy_url
from ei_ai.settings import Settings


def test_converts_a_plain_postgresql_url_to_the_psycopg_driver() -> None:
    url = to_sqlalchemy_url("postgresql://ei_ai_app:s3cret-pw@db:5432/ei_ai")

    assert url == "postgresql+psycopg://ei_ai_app:s3cret-pw@db:5432/ei_ai"


def test_keeps_a_url_that_already_names_the_driver() -> None:
    url = "postgresql+psycopg://ei_ai_app:s3cret-pw@db:5432/ei_ai"

    assert to_sqlalchemy_url(url) == url


def test_refuses_another_database_without_echoing_the_url() -> None:
    with pytest.raises(ValueError) as error:
        to_sqlalchemy_url("mysql://user:s3cret-pw@db/ei_ai")

    assert "s3cret-pw" not in str(error.value)


async def test_app_engine_pings_connections_and_does_not_print_the_password(
    settings: Settings,
) -> None:
    engine = create_app_engine(settings)
    try:
        assert isinstance(engine, AsyncEngine)
        assert engine.pool._pre_ping is True
        assert "s3cret-pw" not in repr(engine.url)
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        await engine.dispose()


def test_libpq_url_drops_the_driver_name_only() -> None:
    assert (
        to_libpq_url("postgresql+psycopg://u:pw@db:5432/ei_ai") == "postgresql://u:pw@db:5432/ei_ai"
    )
    assert to_libpq_url("postgresql://u:pw@db:5432/ei_ai") == "postgresql://u:pw@db:5432/ei_ai"


async def test_cli_engine_fails_fast_on_an_unreachable_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create(url: str, **kwargs: Any) -> str:
        captured.update(kwargs, url=url)
        return "engine"

    monkeypatch.setattr(engine_module, "create_async_engine", fake_create)

    assert engine_module.create_cli_engine("postgresql://u:pw@db:5432/ei_ai") == "engine"
    assert captured == {
        "url": "postgresql+psycopg://u:pw@db:5432/ei_ai",
        "pool_pre_ping": True,
        "connect_args": {"connect_timeout": engine_module.CLI_CONNECT_TIMEOUT_SECONDS},
    }
    assert 1 <= engine_module.CLI_CONNECT_TIMEOUT_SECONDS <= 10


async def test_run_with_app_engine_disposes_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _Engine:
        async def dispose(self) -> None:
            events.append("disposed")

    async def work(engine: Any) -> str:
        events.append("work")
        return "done"

    monkeypatch.setattr(engine_module, "create_cli_engine", lambda url: _Engine())

    assert await engine_module.run_with_app_engine("postgresql://x", work) == "done"
    assert events == ["work", "disposed"]
