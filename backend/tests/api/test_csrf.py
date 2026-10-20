from fastapi.testclient import TestClient

from ei_ai.api.csrf import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from ei_ai.main import create_app
from ei_ai.readiness import Readiness

ORIGIN = "http://localhost:3000"
TOKEN = "t0ken-value"


async def _ok() -> None:
    return None


def _client() -> TestClient:
    app = create_app(readiness=Readiness(database=_ok, valkey=_ok), admin_base_url=ORIGIN)

    @app.post("/auth/probe")
    def auth_probe() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post("/other/probe")
    def other_probe() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def _cookies(*pairs: tuple[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in pairs)


def test_csrf_missing_header_403() -> None:
    response = _client().post("/auth/probe", headers={"Cookie": _cookies((CSRF_COOKIE, TOKEN))})

    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}


def test_csrf_missing_cookie_and_header_403() -> None:
    response = _client().post("/auth/probe")

    assert response.status_code == 403


def test_csrf_mismatch_403() -> None:
    response = _client().post(
        "/auth/probe",
        headers={"Cookie": _cookies((CSRF_COOKIE, TOKEN)), CSRF_HEADER: "other"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}


def test_csrf_foreign_origin_403() -> None:
    response = _client().post(
        "/auth/probe",
        headers={
            "Cookie": _cookies((CSRF_COOKIE, TOKEN)),
            CSRF_HEADER: TOKEN,
            "Origin": "https://evil.example",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}


def test_csrf_ok_passes() -> None:
    response = _client().post(
        "/auth/probe",
        headers={"Cookie": _cookies((CSRF_COOKIE, TOKEN)), CSRF_HEADER: TOKEN, "Origin": ORIGIN},
    )

    assert response.status_code == 200


def test_csrf_ok_without_origin_header_passes() -> None:
    response = _client().post(
        "/auth/probe", headers={"Cookie": _cookies((CSRF_COOKIE, TOKEN)), CSRF_HEADER: TOKEN}
    )

    assert response.status_code == 200


def test_csrf_applies_to_session_cookie_requests_outside_auth() -> None:
    response = _client().post("/other/probe", headers={"Cookie": _cookies((SESSION_COOKIE, "abc"))})

    assert response.status_code == 403


def test_csrf_ignores_bearer_requests_without_session_cookie() -> None:
    response = _client().post("/other/probe", headers={"Authorization": "Bearer abc"})

    assert response.status_code == 200


def test_csrf_does_not_apply_to_get() -> None:
    assert _client().get("/healthz").status_code == 200


def test_get_csrf_sets_cookie_flags() -> None:
    response = _client().get("/auth/csrf")

    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert len(token) >= 32
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{CSRF_COOKIE}={token}")
    assert "Secure" in cookie
    assert "samesite=strict" in cookie.lower()
    assert "Path=/" in cookie
    assert "httponly" not in cookie.lower()
