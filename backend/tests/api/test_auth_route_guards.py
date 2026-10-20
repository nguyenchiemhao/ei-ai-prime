"""Guards of the ``/auth/*`` routes that need no database: set-password looks at the token before
any hashing and has its own rate-limit bucket, the rate-limit check runs on the event loop, and
an unexpected failure answers a plain 500 without a traceback."""

import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from ei_ai.api import auth as auth_routes
from ei_ai.api.csrf import CSRF_COOKIE, CSRF_HEADER
from ei_ai.auth.rate_limit import RateLimiter
from ei_ai.main import create_app
from ei_ai.readiness import Readiness

TOKEN = "t0ken-value"
CSRF = {"Cookie": f"{CSRF_COOKIE}={TOKEN}", CSRF_HEADER: TOKEN}
GOOD_PASSWORD = "a long enough passphrase"
WELL_FORMED_TOKEN = f"0192a000-0000-7000-8000-00000000ea21.{'x' * 43}"


async def _ok() -> None:
    return None


def _client(rate_limiter: RateLimiter | None = None) -> TestClient:
    app = create_app(readiness=Readiness(database=_ok, valkey=_ok), rate_limiter=rate_limiter)
    return TestClient(app)


def _set_password(client: TestClient, token: str, password: str = GOOD_PASSWORD) -> int:
    response = client.post(
        "/auth/set-password", json={"token": token, "password": password}, headers=CSRF
    )
    status: int = response.status_code
    return status


@pytest.fixture
def hash_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def counting_hash(password: str) -> str:
        calls.append(password)
        return "$argon2id$fake"

    monkeypatch.setattr(auth_routes, "hash_password", counting_hash)
    return calls


def test_malformed_set_password_token_is_400_without_hashing(hash_calls: list[str]) -> None:
    for token in ("not-a-token", "", f"not-a-uuid.{'x' * 43}", "0192a000-0000-7000-8000-x.short"):
        response = _client().post(
            "/auth/set-password", json={"token": token, "password": GOOD_PASSWORD}, headers=CSRF
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "invalid_token"}
    assert hash_calls == []


def test_set_password_policy_is_still_checked_before_the_token(hash_calls: list[str]) -> None:
    response = _client().post(
        "/auth/set-password", json={"token": "not-a-token", "password": "short"}, headers=CSRF
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "password_too_short"}
    assert hash_calls == []


def test_set_password_is_rate_limited_in_its_own_bucket(hash_calls: list[str]) -> None:
    client = _client(RateLimiter(2))

    statuses = [_set_password(client, "not-a-token") for _ in range(2)]
    limited = client.post(
        "/auth/set-password", json={"token": "not-a-token", "password": GOOD_PASSWORD}, headers=CSRF
    )
    sign_in = client.post("/auth/sign-in", json={}, headers=CSRF)

    assert statuses == [400, 400]
    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate_limited"}
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert limited.headers["cache-control"] == "no-store"
    assert sign_in.status_code == 422  # sign-in has its own bucket
    assert hash_calls == []


class _ThreadRecordingLimiter(RateLimiter):
    def __init__(self) -> None:
        super().__init__(limit=100)
        self.threads: list[int] = []

    def hit(self, key: str) -> float | None:
        self.threads.append(threading.get_ident())
        return super().hit(key)


async def test_rate_limit_check_runs_on_the_event_loop() -> None:
    """The limiter is not thread-safe: the check must never run in the worker thread pool."""
    limiter = _ThreadRecordingLimiter()
    app = create_app(readiness=Readiness(database=_ok, valkey=_ok), rate_limiter=limiter)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/auth/sign-in", "/auth/forgot-password", "/auth/set-password"):
            await client.post(path, json={}, headers=CSRF)

    assert limiter.threads == [threading.get_ident()] * 3


def test_auth_route_failure_is_a_plain_500_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The failure is handled inside the app (the server never sees an exception, so it prints no
    traceback quoting ``hash_password(body.password)``) and the 500 still passes no-store."""

    async def failing_hash(_password: str) -> str:
        raise RuntimeError("hashing failed for the password")

    monkeypatch.setattr(auth_routes, "hash_password", failing_hash)
    caplog.set_level("DEBUG")
    client = _client()  # raise_server_exceptions: an unhandled exception would fail the test

    response = client.post(
        "/auth/set-password",
        json={"token": WELL_FORMED_TOKEN, "password": GOOD_PASSWORD},
        headers=CSRF,
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert response.headers["cache-control"] == "no-store"
    assert "auth_route_failed operation=hash_secret error=RuntimeError" in caplog.text
    printed = capsys.readouterr()
    # The test client logs its own request lines (the URL path); only the app's logs count.
    app_logs = "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx")
    tracebacks = [r for r in caplog.records if r.exc_info]
    written = "\n".join([app_logs, printed.out, printed.err])
    assert tracebacks == []
    assert "Traceback" not in written
    assert "password" not in written.lower()
