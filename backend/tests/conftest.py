"""Shared pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ei_ai.settings import Settings

ISOLATION_FOLDER = Path(__file__).parent / "integration" / "isolation"


def pytest_itemcollected(item: pytest.Item) -> None:
    """Everything under tests/integration/isolation/ is part of the tenant-isolation suite.

    Runs at collection, before `-m` deselects, so the folder needs no per-file marker and a new
    isolation test cannot be left out of the `tenant-isolation` CI job by accident.
    """
    if ISOLATION_FOLDER in item.path.parents:
        item.add_marker(pytest.mark.integration)
        item.add_marker(pytest.mark.isolation)


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
