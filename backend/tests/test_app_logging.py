"""The api process sends the ``ei_ai.*`` INFO lines to stderr (EA-37 Q1-1).

Uvicorn's own logging config sets up the ``uvicorn.*`` loggers only, so without this the masked
``answer_done`` trace (and every other ``ei_ai`` INFO line) was dropped in the container."""

import logging

import pytest
from fastapi.testclient import TestClient

from ei_ai.app_logging import APP_LOGGER, configure_app_logging
from ei_ai.main import create_app
from ei_ai.settings import SettingsError
from support.crypto import TEST_MASTER_KEY

LINE = "answer_done org_id=x outcome=answered rule=cited passages=3 cited=1"


def _ours() -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger(APP_LOGGER).handlers
        if type(h).__module__ == "ei_ai.app_logging"
    ]


def test_info_records_reach_stderr_until_restored(capsys: pytest.CaptureFixture[str]) -> None:
    restore = configure_app_logging()
    try:
        logging.getLogger("ei_ai.knowledge.answers").info(LINE)
        logging.getLogger("ei_ai.knowledge.answers").debug("debug-is-not-shown")
    finally:
        restore()
    logging.getLogger("ei_ai.knowledge.answers").info("after-restore")

    err = capsys.readouterr().err
    assert err.count("answer_done") == 1
    assert "INFO" in err and "ei_ai.knowledge.answers" in err
    assert "debug-is-not-shown" not in err
    assert "after-restore" not in err
    assert _ours() == []


def test_configuring_twice_adds_one_handler() -> None:
    first = configure_app_logging()
    second = configure_app_logging()
    try:
        assert len(_ours()) == 1
    finally:
        second()
        first()
    assert _ours() == []


def test_restore_keeps_a_level_set_before() -> None:
    logger = logging.getLogger(APP_LOGGER)
    before = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        restore = configure_app_logging()
        assert logger.level == logging.DEBUG
        restore()
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(before)


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "EI_AI_ENV": "test",
        "DATABASE_URL": "postgresql://ei_ai_app:pw@db.invalid:5432/ei_ai",
        "VALKEY_URL": "redis://valkey.invalid:6379/0",
        "SIGNIN_DATABASE_URL": "postgresql://ei_ai_signin:pw@db.invalid:5432/ei_ai",
        "ADMIN_BASE_URL": "https://admin.example",
        "EI_AI_MASTER_KEY": TEST_MASTER_KEY.key.hex(),
    }.items():
        monkeypatch.setenv(name, value)


@pytest.mark.usefixtures("app_env")
def test_the_lifespan_configures_app_logging(capsys: pytest.CaptureFixture[str]) -> None:
    with TestClient(create_app()):
        logging.getLogger("ei_ai.knowledge.answers").info(LINE)

    assert "answer_done" in capsys.readouterr().err
    assert _ours() == []


def test_a_failed_startup_restores_logging(app_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EI_AI_MASTER_KEY")

    with pytest.raises(SettingsError), TestClient(create_app()):
        pass

    assert _ours() == []
