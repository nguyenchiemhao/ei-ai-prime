"""AC3 (API side) and AC4: the tenant is always the Principal's; forged fields are ignored."""

import logging
import uuid
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from ei_ai.auth.principal import Principal
from ei_ai.tenancy.context import ORG_HEADERS, ORG_QUERY_PARAMS, TenantContext, require_tenant
from support.identity import StaticBearerVerifier

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
USER = uuid.uuid4()
AUTH = {"Authorization": "Bearer token-a"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.state.identity_verifiers = (
        StaticBearerVerifier({"token-a": Principal(user_id=USER, org_id=ORG_A)}),
    )

    @app.get("/probe/{item}")
    def probe(
        item: str, tenant: Annotated[TenantContext, Depends(require_tenant)]
    ) -> dict[str, str]:
        return {"org": str(tenant.org_id), "user": str(tenant.user_id)}

    return TestClient(app)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "ei_ai.tenancy" and r.levelno == logging.WARNING]


def test_missing_principal_returns_401_unauthenticated_code_only(client: TestClient) -> None:
    response = client.get("/probe/1", headers={"X-Org-Id": str(ORG_B)})

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
    assert str(ORG_B) not in response.text


def test_the_tenant_is_the_principals_organization(client: TestClient) -> None:
    response = client.get("/probe/1", headers=AUTH)

    assert response.json() == {"org": str(ORG_A), "user": str(USER)}


@pytest.mark.parametrize("header", ORG_HEADERS)
def test_org_header_differs_uses_principal_org_and_warns(
    client: TestClient, caplog: pytest.LogCaptureFixture, header: str
) -> None:
    caplog.set_level(logging.INFO)

    response = client.get("/probe/1", headers={**AUTH, header: str(ORG_B)})

    assert response.json()["org"] == str(ORG_A)
    (warning,) = _warnings(caplog)
    assert "tenant_override_ignored" in warning.getMessage()
    assert f"field={header}" in warning.getMessage()
    assert "source=header" in warning.getMessage()


@pytest.mark.parametrize("name", ORG_QUERY_PARAMS)
def test_org_query_param_differs_uses_principal_org_and_warns(
    client: TestClient, caplog: pytest.LogCaptureFixture, name: str
) -> None:
    caplog.set_level(logging.INFO)

    response = client.get("/probe/1", params={name: str(ORG_B)}, headers=AUTH)

    assert response.json()["org"] == str(ORG_A)
    (warning,) = _warnings(caplog)
    assert f"field={name}" in warning.getMessage()
    assert "source=query" in warning.getMessage()


def test_org_query_param_name_is_matched_case_insensitively(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    client.get("/probe/1", params={"ORG_ID": str(ORG_B)}, headers=AUTH)

    (warning,) = _warnings(caplog)
    assert "field=org_id" in warning.getMessage()


def test_malformed_org_value_is_ignored_and_warns(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    response = client.get("/probe/1", params={"org_id": "not-a-uuid' OR 1=1"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["org"] == str(ORG_A)
    assert len(_warnings(caplog)) == 1


def test_matching_org_value_does_not_warn(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    response = client.get(
        "/probe/1",
        params={"org_id": str(ORG_A).upper()},
        headers={**AUTH, "X-Org-Id": str(ORG_A)},
    )

    assert response.json()["org"] == str(ORG_A)
    assert _warnings(caplog) == []


def test_warning_never_contains_the_supplied_value(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    client.get("/probe/1", params={"org_id": str(ORG_B)}, headers={**AUTH, "X-Tenant-Id": "evil"})

    assert len(_warnings(caplog)) == 2
    # Only our own loggers: the test client logs the request URL itself.
    ours = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("ei_ai"))
    assert str(ORG_B) not in ours
    assert "evil" not in ours
    assert "path=/probe/{item}" in ours  # the route template, not the URL
    assert f"org_id={ORG_A}" in ours
