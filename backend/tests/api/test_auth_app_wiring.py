"""The auth wiring of ``create_app``: ``Cache-Control: no-store`` on every ``/auth/*`` answer (also
the ones produced outside a route) and the settings that reach the CSRF check, the rate limiter
and the session verifier. No database: every request here stops before the sign-in itself."""

from datetime import timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient

from ei_ai.api.csrf import CSRF_COOKIE, CSRF_HEADER
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.session_verifier import SessionCookieVerifier
from ei_ai.main import create_app
from ei_ai.readiness import Readiness
from support.crypto import TEST_MASTER_KEY

TOKEN = "t0ken-value"
CSRF = {"Cookie": f"{CSRF_COOKIE}={TOKEN}", CSRF_HEADER: TOKEN}


async def _ok() -> None:
    return None


def _client() -> TestClient:
    return TestClient(create_app(readiness=Readiness(database=_ok, valkey=_ok)))


def test_csrf_rejection_is_no_store() -> None:
    response = _client().post("/auth/sign-in", json={"email": "x", "password": "y"})

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_validation_rejection_is_no_store() -> None:
    response = _client().post("/auth/sign-in", json={"email": "x"}, headers=CSRF)

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    assert response.headers["cache-control"] == "no-store"


def test_csrf_token_route_is_no_store_once() -> None:
    response = _client().get("/auth/csrf")

    assert response.headers.get_list("cache-control") == ["no-store"]


def test_other_routes_keep_their_cache_headers() -> None:
    assert "cache-control" not in _client().get("/healthz").headers


def test_default_verifier_is_the_session_cookie() -> None:
    app = create_app(readiness=Readiness(database=_ok, valkey=_ok))

    (verifier,) = app.state.identity_verifiers
    assert isinstance(verifier, SessionCookieVerifier)
    assert verifier.idle == timedelta(seconds=43200)


@pytest.fixture
def auth_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in {
        "EI_AI_ENV": "test",
        "DATABASE_URL": "postgresql://ei_ai_app:pw@db.invalid:5432/ei_ai",
        "VALKEY_URL": "redis://valkey.invalid:6379/0",
        "SIGNIN_DATABASE_URL": "postgresql://ei_ai_signin:pw@db.invalid:5432/ei_ai",
        "ADMIN_BASE_URL": "https://admin.example",
        "AUTH_RATE_LIMIT_PER_MINUTE": "2",
        "SESSION_IDLE_TIMEOUT_SECONDS": "120",
        "TRUST_PROXY_HEADERS": "true",
        # The lifespan builds the encrypted file store of originals (EA-33), which needs the key.
        "EI_AI_MASTER_KEY": TEST_MASTER_KEY.key.hex(),
    }.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def _sign_in(client: TestClient, **headers: str) -> int:
    status: int = client.post("/auth/sign-in", json={}, headers={**CSRF, **headers}).status_code
    return status


def test_settings_reach_the_csrf_origin(auth_env: pytest.MonkeyPatch) -> None:
    with TestClient(create_app()) as client:
        assert _sign_in(client, Origin="https://admin.example") == 422
        assert _sign_in(client, Origin="http://localhost:3000") == 403


def test_settings_reach_the_rate_limiter_and_proxy_trust(auth_env: pytest.MonkeyPatch) -> None:
    with TestClient(create_app()) as client:
        statuses = [_sign_in(client, **{"X-Forwarded-For": "203.0.113.1"}) for _ in range(3)]
        other_ip = _sign_in(client, **{"X-Forwarded-For": "203.0.113.2"})

    assert statuses == [422, 422, 429]
    assert other_ip == 422


def test_settings_reach_the_session_verifier(auth_env: pytest.MonkeyPatch) -> None:
    app = create_app()
    with TestClient(app):
        (verifier,) = app.state.identity_verifiers

    assert isinstance(verifier, SessionCookieVerifier)
    assert verifier.idle == timedelta(seconds=120)


def test_given_verifiers_are_kept(auth_env: pytest.MonkeyPatch) -> None:
    app = create_app(identity_verifiers=())
    with TestClient(app):
        assert app.state.identity_verifiers == ()


class _FailingDirectory:
    async def find_accounts(self, email: str) -> list[object]:
        raise ValueError(f"lookup failed for {email}")


def test_unexpected_sign_in_failure_logs_the_exception_class_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(
        readiness=Readiness(database=_ok, valkey=_ok),
        sign_in_directory=cast(SignInDirectory, _FailingDirectory()),
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/auth/sign-in", json={"email": "who@example.invalid", "password": "s3cret"}, headers=CSRF
    )

    assert response.status_code == 500
    assert "auth_route_failed operation=sign_in error=ValueError" in caplog.text
    for value in ("who@example.invalid", "s3cret"):
        assert value not in caplog.text
        assert value not in response.text
