import pytest
from fastapi.testclient import TestClient

from ei_ai.main import create_app
from ei_ai.readiness import Readiness

DSN_PASSWORD = "s3cret-pw"


async def _ok() -> None:
    return None


async def _fail_with_details() -> None:
    raise ConnectionError(f"could not connect to db:5432 as ei_ai_app password={DSN_PASSWORD}")


def _client(database_ok: bool = True, valkey_ok: bool = True) -> TestClient:
    readiness = Readiness(
        database=_ok if database_ok else _fail_with_details,
        valkey=_ok if valkey_ok else _fail_with_details,
    )
    return TestClient(create_app(readiness=readiness))


def test_healthz_returns_200_with_status_ok() -> None:
    response = _client(database_ok=False, valkey_ok=False).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_returns_200_when_all_checks_pass() -> None:
    response = _client().get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "valkey": "ok"}}


def test_readyz_returns_503_and_hides_connection_details() -> None:
    response = _client(database_ok=False).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "unavailable", "valkey": "ok"},
    }
    for secret in (DSN_PASSWORD, "ei_ai_app", "db:5432", "could not connect"):
        assert secret not in response.text


def test_readyz_does_not_log_exception_messages(caplog: "pytest.LogCaptureFixture") -> None:
    _client(valkey_ok=False).get("/readyz")

    assert DSN_PASSWORD not in caplog.text
    assert "valkey" in caplog.text
    assert "ConnectionError" in caplog.text


def test_openapi_describes_both_probes() -> None:
    schema = _client().get("/openapi.json").json()

    assert set(schema["paths"]) == {"/healthz", "/readyz"}
