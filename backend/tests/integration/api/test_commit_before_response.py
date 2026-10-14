"""R1-3: the tenant transaction is committed before the response is sent.

A request-scoped yield dependency would exit after ``http.response.start``, so a commit failure
could not change a 2xx already sent. ``TenantSession`` has function scope; a failing commit must
therefore give an error response.
"""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.api.deps import TenantSession
from ei_ai.auth.principal import Principal
from ei_ai.main import create_app
from ei_ai.readiness import Readiness
from support.identity import StaticBearerVerifier
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration


async def _ok() -> None:
    return None


async def test_a_commit_failure_is_an_error_response_not_a_2xx(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    principal = Principal(user_id=two_orgs.a.user_id, org_id=two_orgs.a.org_id)
    app = create_app(
        readiness=Readiness(database=_ok, valkey=_ok),
        identity_verifiers=(StaticBearerVerifier({"token-a": principal}),),
        engine=app_engine,
    )

    @app.post("/probe/commit-failure")
    async def commit_failure(session: TenantSession) -> dict[str, str]:
        # A deferred unique constraint is checked at COMMIT, after the handler has returned.
        await session.execute(
            text(
                "CREATE TEMP TABLE commit_probe (a int,"
                " CONSTRAINT commit_probe_a UNIQUE (a) DEFERRABLE INITIALLY DEFERRED)"
                " ON COMMIT DROP"
            )
        )
        await session.execute(text("INSERT INTO commit_probe VALUES (1), (1)"))
        return {"status": "created"}

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/probe/commit-failure", headers={"Authorization": "Bearer token-a"}
        )

    assert response.status_code == 500
    assert "created" not in response.text
