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

pytestmark = pytest.mark.integration


@pytest.fixture
def real_settings() -> Settings:
    return Settings.from_env(os.environ)


def test_readyz_ok_against_real_db_and_valkey(real_settings: Settings) -> None:
    client = TestClient(create_app(readiness=build_readiness(real_settings)))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "valkey": "ok"}}


def test_app_role_is_not_superuser_and_cannot_bypass_rls(real_settings: Settings) -> None:
    with psycopg.connect(real_settings.database_url) as connection:
        row = connection.execute(
            "SELECT current_user, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
            "FROM pg_roles WHERE rolname = current_user"
        ).fetchone()

    assert row == ("ei_ai_app", False, False, False, False)


def test_pgvector_extension_is_installed(real_settings: Settings) -> None:
    with psycopg.connect(real_settings.database_url) as connection:
        row = connection.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()

    assert row == ("vector",)


def test_seed_demo_reaches_database_as_app_role(
    real_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert real_settings.environment in ("local", "test")

    assert cli.main(["seed", "demo"]) == 0
    assert "Database: reachable as the application role" in capsys.readouterr().out
