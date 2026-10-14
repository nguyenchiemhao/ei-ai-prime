"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest

from ei_ai.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://ei_ai_app:s3cret-pw@db:5432/ei_ai",
        valkey_url="redis://valkey:6379/0",
    )


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    for name in ("EI_AI_ENV", "DATABASE_URL", "VALKEY_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch
