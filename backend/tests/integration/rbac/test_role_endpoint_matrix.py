"""AC1-AC3: every role against every endpoint that declares a permission, generated.

The endpoints are the production routes that declare a permission plus the test-only probes of the
sensitive permissions (they do not exist as real routes yet, R1). A route added later is covered
the day it lands: the declaration guard forces it to declare a permission, and it appears here.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.main import create_app
from ei_ai.rbac.declarations import PUBLIC, SIGNED_IN
from ei_ai.rbac.permissions import Permission
from support.rbac.kinds import KINDS, TARGET, WORKSPACE, Kind, create_kinds_org
from support.rbac.orgs import RoleOrg, role_client
from support.rbac.probes import router as probes
from support.rbac.routes import declared_routes
from support.tenants import purge_org_ids

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    permission: Permission

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"

    def url(self, org: RoleOrg, workspace_id: uuid.UUID | None = None) -> str:
        values = {
            "workspace_id": workspace_id or org.workspace(WORKSPACE),
            "user_id": org.user(TARGET),
        }
        url = self.path
        for name in ("workspace_id", "user_id"):
            url = url.replace("{" + name + "}", str(values[name]))
        while "{" in url:  # any other parameter is a random id
            start = url.index("{")
            url = url[:start] + str(uuid.uuid4()) + url[url.index("}") + 1 :]
        return url


def _endpoints() -> list[Endpoint]:
    app = create_app()
    app.include_router(probes)
    found: list[Endpoint] = []
    for route in declared_routes(app):
        assert len(route.declarations) == 1, f"{route.label} must declare exactly one permission"
        declaration = route.declarations[0]
        if declaration not in (PUBLIC, SIGNED_IN):
            found.append(Endpoint(route.method, route.path, Permission(declaration)))
    return found


ENDPOINTS = _endpoints()
PROBES = [e for e in ENDPOINTS if e.path.startswith("/rbac-probe/")]


@pytest.fixture
async def org(app_engine: AsyncEngine) -> AsyncIterator[RoleOrg]:
    created = await create_kinds_org(app_engine)
    try:
        yield created
    finally:
        await purge_org_ids(app_engine, created.org_id)


async def _call(
    client: httpx.AsyncClient, endpoint: Endpoint, org: RoleOrg, kind: Kind, url: str | None = None
) -> httpx.Response:
    return await client.request(
        endpoint.method,
        url or endpoint.url(org),
        headers=org.headers(kind.name),
        json={} if endpoint.method in ("PUT", "POST") else None,
    )


def test_the_endpoint_list_is_not_vacuous() -> None:
    assert len(ENDPOINTS) >= 11  # the 5 member routes, the Workspace route and the 6 probes
    assert {e.permission for e in PROBES} == {
        Permission.CONVERSATIONS_READ,
        Permission.CONNECTORS_MANAGE,
        Permission.ASSISTANTS_PUBLISH,
        Permission.COLLECTIONS_ACCESS_MANAGE,
    }
    assert len(KINDS) == 10


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.label)
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.name)
async def test_role_against_endpoint(
    app_engine: AsyncEngine, org: RoleOrg, endpoint: Endpoint, kind: Kind
) -> None:
    async with role_client(app_engine, org, extra_routers=[probes]) as client:
        response = await _call(client, endpoint, org, kind)
        if "{workspace_id}" in endpoint.path and not kind.sees_workspace:
            unknown = await _call(
                client, endpoint, org, kind, endpoint.url(org, workspace_id=uuid.uuid4())
            )

    if kind.holds(endpoint.permission):
        assert response.status_code not in (401, 403), response.text
    elif "{workspace_id}" in endpoint.path and not kind.sees_workspace:
        # Not in W and no Organization role: W looks exactly like an unknown Workspace (404).
        assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
        assert (response.status_code, response.content) == (unknown.status_code, unknown.content)
    else:
        assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.label)
async def test_no_session_is_401(app_engine: AsyncEngine, org: RoleOrg, endpoint: Endpoint) -> None:
    async with role_client(app_engine, org, extra_routers=[probes]) as client:
        response = await client.request(endpoint.method, endpoint.url(org))

    assert (response.status_code, response.json()) == (401, {"detail": "unauthenticated"})


# The sensitive rules of AC2/AC3, stated independently of the matrix code: who reaches each probe.
SENSITIVE_HOLDERS = {
    ("GET", "/conversations"): {"reviewer"},
    ("GET", "/connector-secrets"): {"workspace_admin", "developer", "org_owner", "org_admin"},
    ("PUT", "/connector-secrets"): {"workspace_admin", "developer", "org_owner", "org_admin"},
    ("PUT", "/signing-keys"): {"workspace_admin", "developer", "org_owner", "org_admin"},
    ("POST", "/publish"): {"workspace_admin", "builder", "org_owner", "org_admin"},
    ("PUT", "/collection-access"): {"workspace_admin", "org_owner", "org_admin"},
}


@pytest.mark.parametrize("route", list(SENSITIVE_HOLDERS), ids=lambda r: f"{r[0]} {r[1]}")
async def test_sensitive_probes_are_reached_only_by_the_named_roles(
    app_engine: AsyncEngine, org: RoleOrg, route: tuple[str, str]
) -> None:
    method, suffix = route
    url = f"/rbac-probe/workspaces/{org.workspace(WORKSPACE)}{suffix}"

    async with role_client(app_engine, org, extra_routers=[probes]) as client:
        reached = {
            kind.name
            for kind in KINDS
            if (
                await client.request(
                    method,
                    url,
                    headers=org.headers(kind.name),
                    json={} if method != "GET" else None,
                )
            ).status_code
            == 204
        }

    assert reached == SENSITIVE_HOLDERS[route]
