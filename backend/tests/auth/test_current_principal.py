"""AC4 (identity side): the Principal comes from a verifier, anything else is 401."""

import uuid
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from ei_ai.auth.dependencies import current_principal
from ei_ai.auth.principal import IdentityVerifier, InvalidCredentials, Principal
from support.identity import StaticBearerVerifier

USER = uuid.uuid4()
ORG = uuid.uuid4()
PRINCIPAL = Principal(user_id=USER, org_id=ORG)


def _client(*verifiers: IdentityVerifier) -> TestClient:
    app = FastAPI()
    app.state.identity_verifiers = tuple(verifiers)

    @app.get("/whoami")
    def whoami(principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, str]:
        return {"user": str(principal.user_id), "org": str(principal.org_id)}

    return TestClient(app)


class _Never:
    async def verify(self, request: Request) -> Principal | None:
        return None


class _Fixed:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self.calls = 0

    async def verify(self, request: Request) -> Principal | None:
        self.calls += 1
        return self.principal


class _Invalid:
    async def verify(self, request: Request) -> Principal | None:
        raise InvalidCredentials


class _Broken:
    async def verify(self, request: Request) -> Principal | None:
        raise RuntimeError("token abc.def.ghi could not be parsed")


def test_without_any_verifier_every_request_is_401() -> None:
    response = _client().get("/whoami")

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_verifier_that_finds_no_credential_gives_401() -> None:
    response = _client(_Never()).get("/whoami")

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}


def test_the_first_matching_verifier_wins() -> None:
    first, second = _Fixed(PRINCIPAL), _Fixed(Principal(uuid.uuid4(), uuid.uuid4()))

    response = _client(_Never(), first, second).get("/whoami")

    assert response.status_code == 200
    assert response.json() == {"user": str(USER), "org": str(ORG)}
    assert (first.calls, second.calls) == (1, 0)


def test_invalid_credentials_give_401_even_when_a_later_verifier_would_accept() -> None:
    response = _client(_Invalid(), _Fixed(PRINCIPAL)).get("/whoami")

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}


def test_a_verifier_error_gives_401_without_details(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")

    response = _client(_Broken()).get("/whoami")

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
    assert "abc.def.ghi" not in response.text
    assert "abc.def.ghi" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_the_test_verifier_reads_a_bearer_token() -> None:
    client = _client(StaticBearerVerifier({"token-a": PRINCIPAL}))

    ok = client.get("/whoami", headers={"Authorization": "Bearer token-a"})
    bad = client.get("/whoami", headers={"Authorization": "Bearer nope"})
    none = client.get("/whoami")

    assert ok.status_code == 200
    assert ok.json()["org"] == str(ORG)
    assert bad.status_code == 401
    assert none.status_code == 401
