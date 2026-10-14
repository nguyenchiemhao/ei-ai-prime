"""AC4 with a real database: the Organization comes from the verified identity, not the request."""

import logging
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.principal import Principal
from ei_ai.main import create_app
from ei_ai.readiness import Readiness
from support.identity import StaticBearerVerifier
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration


async def _ok() -> None:
    return None


def _client(app_engine: AsyncEngine, *verifiers: StaticBearerVerifier) -> httpx.AsyncClient:
    app = create_app(
        readiness=Readiness(database=_ok, valkey=_ok),
        identity_verifiers=verifiers,
        engine=app_engine,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client_as_a(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> AsyncIterator[httpx.AsyncClient]:
    principal = Principal(user_id=two_orgs.a.user_id, org_id=two_orgs.a.org_id)
    async with _client(app_engine, StaticBearerVerifier({"token-a": principal})) as client:
        yield client


async def test_forged_org_header_and_query_are_ignored_and_real_org_is_returned(
    client_as_a: httpx.AsyncClient, two_orgs: TwoOrgs, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    response = await client_as_a.get(
        "/organization",
        headers={"Authorization": "Bearer token-a", "X-Org-Id": str(two_orgs.b.org_id)},
        params={"org_id": str(two_orgs.b.org_id)},
    )

    assert response.status_code == 200
    assert response.json() == {"id": str(two_orgs.a.org_id), "name": "Org A"}
    assert "Org B" not in response.text
    assert str(two_orgs.b.org_id) not in response.text
    warnings = [r for r in caplog.records if r.name == "ei_ai.tenancy" and r.levelno == 30]
    assert len(warnings) == 2
    ours = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("ei_ai"))
    assert str(two_orgs.b.org_id) not in ours


async def test_the_route_returns_the_organization_without_any_forged_field(
    client_as_a: httpx.AsyncClient, two_orgs: TwoOrgs
) -> None:
    response = await client_as_a.get("/organization", headers={"Authorization": "Bearer token-a"})

    assert response.json() == {"id": str(two_orgs.a.org_id), "name": "Org A"}


async def test_without_verifier_route_is_401_even_with_org_header(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with _client(app_engine) as client:
        response = await client.get("/organization", headers={"X-Org-Id": str(two_orgs.a.org_id)})

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
    assert str(two_orgs.a.org_id) not in response.text


async def test_an_organization_that_no_longer_exists_is_404_without_details(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    ghost = Principal(user_id=uuid.uuid4(), org_id=uuid.uuid4())
    async with _client(app_engine, StaticBearerVerifier({"ghost": ghost})) as client:
        response = await client.get("/organization", headers={"Authorization": "Bearer ghost"})

    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}
