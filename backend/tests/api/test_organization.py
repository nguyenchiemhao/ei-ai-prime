"""AC3/AC4 on the real app wiring, without a database: no verifier means 401 for every request."""

from fastapi.testclient import TestClient

from ei_ai.main import create_app
from ei_ai.readiness import Readiness


async def _ok() -> None:
    return None


def _client() -> TestClient:
    return TestClient(create_app(readiness=Readiness(database=_ok, valkey=_ok)))


def test_without_verifier_the_route_is_401_even_with_an_org_header() -> None:
    response = _client().get(
        "/organization",
        headers={"X-Org-Id": "0b9c1c3e-5f0a-4a52-9a53-2c0f1f6f7a11"},
        params={"org_id": "0b9c1c3e-5f0a-4a52-9a53-2c0f1f6f7a11"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "0b9c1c3e" not in response.text


def test_the_route_is_documented_with_its_error_codes() -> None:
    operation = _client().get("/openapi.json").json()["paths"]["/organization"]["get"]

    assert set(operation["responses"]) == {"200", "401", "404"}
