"""Integration tests against the real PostgreSQL and Valkey of the Compose stack.

Run with: npm run backend -- test-integration (starts db and valkey first).
"""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from ei_ai import cli
from ei_ai.main import create_app
from ei_ai.readiness import build_readiness
from ei_ai.settings import Settings
from support.seed import demo_seed_password

pytestmark = pytest.mark.integration


@pytest.fixture
def real_settings() -> Settings:
    return Settings.from_env(os.environ)


def test_readyz_ok_against_real_db_and_valkey(real_settings: Settings) -> None:
    client = TestClient(create_app(readiness=build_readiness(real_settings)))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "valkey": "ok"}}


def test_pgvector_extension_is_installed(real_settings: Settings) -> None:
    with psycopg.connect(real_settings.database_url) as connection:
        row = connection.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()

    assert row == ("vector",)


def test_seed_demo_loads_the_manifests_as_app_role(
    real_settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert real_settings.environment in ("local", "test")
    monkeypatch.setenv("EI_AI_SEED_PASSWORD", demo_seed_password())

    assert cli.main(["seed", "demo"]) == 0
    out = capsys.readouterr().out
    assert "Organization: Mekong Devworks (0192a000-0000-7000-8000-00000000ea21)" in out
    assert "Members: 10" in out
    assert "Organization: Sông Hàn Retail (0192a000-0000-7000-8000-00000000ea94)" in out
    assert "Members: 2" in out
    assert demo_seed_password() not in out
