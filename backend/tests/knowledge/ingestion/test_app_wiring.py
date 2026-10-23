"""The ingestion wiring of ``create_app``: file store, progress board, clock and runner (EA-33)."""

from datetime import UTC
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runner import IngestionRunner
from ei_ai.main import create_app
from ei_ai.readiness import Readiness
from ei_ai.settings import SettingsError
from ei_ai.storage.files import OrgFileStore
from support.crypto import TEST_MASTER_KEY


async def _ok() -> None:
    return None


class _RecordingRunner:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _settings_env(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    for name, value in {
        "EI_AI_ENV": "test",
        "DATABASE_URL": "postgresql://ei_ai_app:pw@db.invalid:5432/ei_ai",
        "VALKEY_URL": "redis://valkey.invalid:6379/0",
        "SIGNIN_DATABASE_URL": "postgresql://ei_ai_signin:pw@db.invalid:5432/ei_ai",
        "ADMIN_BASE_URL": "https://admin.example",
        "FILE_STORAGE_ROOT": str(root),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("EI_AI_MASTER_KEY", raising=False)
    monkeypatch.delenv("EI_AI_MASTER_KEY_FILE", raising=False)


def test_factory_sets_the_ingestion_parts(tmp_path: Path) -> None:
    store = OrgFileStore(tmp_path, OrgCipher(TEST_MASTER_KEY))

    app = create_app(readiness=Readiness(database=_ok, valkey=_ok), file_store=store)

    assert app.state.file_store is store
    assert isinstance(app.state.progress_board, ProgressBoard)
    assert isinstance(app.state.ingestion_runner, IngestionRunner)
    assert app.state.clock().tzinfo is UTC


def test_lifespan_builds_file_store_from_settings_and_master_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("EI_AI_MASTER_KEY", TEST_MASTER_KEY.key.hex())
    app = create_app()
    runner = _RecordingRunner()
    app.state.ingestion_runner = runner

    with TestClient(app):
        store = app.state.file_store
        assert isinstance(store, OrgFileStore)
        assert store._root == tmp_path
        assert store._cipher._master == TEST_MASTER_KEY

    assert runner.closed


def test_lifespan_without_master_key_fails_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _settings_env(monkeypatch, tmp_path)
    app = create_app()
    app.state.ingestion_runner = _RecordingRunner()

    with pytest.raises(SettingsError, match="EI_AI_MASTER_KEY") as raised, TestClient(app):
        pass

    assert TEST_MASTER_KEY.key.hex() not in str(raised.value)


def test_lifespan_with_malformed_master_key_hides_the_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _settings_env(monkeypatch, tmp_path)
    malformed = "zz" + TEST_MASTER_KEY.key.hex()[2:]
    monkeypatch.setenv("EI_AI_MASTER_KEY", malformed)
    app = create_app()
    app.state.ingestion_runner = _RecordingRunner()

    with pytest.raises(SettingsError, match="EI_AI_MASTER_KEY") as raised, TestClient(app):
        pass

    assert malformed not in str(raised.value)
