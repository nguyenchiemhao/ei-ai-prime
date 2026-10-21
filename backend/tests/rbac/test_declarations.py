"""The enforcement dependencies without a database: a fake verifier, a fake session and a
monkeypatched loader. 404 for a Workspace the caller cannot see, 403 for a missing permission,
code-only bodies, and no client-sent role ever counts (D32)."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from ei_ai.api.deps import tenant_db
from ei_ai.auth.principal import Principal
from ei_ai.rbac import declarations
from ei_ai.rbac.access import OrgAccess, PermissionDenied, WorkspaceAccess, ensure
from ei_ai.rbac.declarations import (
    declared,
    install_permission_handler,
    public,
    requires,
    requires_org,
    signed_in,
)
from ei_ai.rbac.permissions import Permission, permissions_for
from ei_ai.tenancy.context import TenantContext
from support.identity import StaticBearerVerifier

ORG = uuid.uuid4()
USER = uuid.uuid4()
WORKSPACE = uuid.uuid4()
AUTH = {"Authorization": "Bearer token"}


class _FakeSession:
    async def connection(self) -> object:
        return object()


async def _fake_session() -> AsyncIterator[_FakeSession]:
    yield _FakeSession()


def _access(org_role: str | None, role: str | None) -> WorkspaceAccess:
    return WorkspaceAccess(WORKSPACE, "Fixture", role, org_role, permissions_for(org_role, role))


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.state.identity_verifiers = (
        StaticBearerVerifier({"token": Principal(user_id=USER, org_id=ORG)}),
    )
    app.dependency_overrides[tenant_db] = _fake_session
    install_permission_handler(app)

    @app.get("/w/{workspace_id}/manage")
    async def manage(
        access: Annotated[WorkspaceAccess, Depends(requires(Permission.MEMBERS_MANAGE))],
    ) -> dict[str, object]:
        return {"role": access.role}

    @app.get("/org/roles")
    async def org_roles(
        access: Annotated[OrgAccess, Depends(requires_org(Permission.ORG_ROLES_MANAGE))],
    ) -> dict[str, object]:
        return {"org_role": access.org_role}

    @app.get("/me")
    async def me(tenant: Annotated[TenantContext, Depends(signed_in())]) -> dict[str, str]:
        return {"user": str(tenant.user_id)}

    @app.get("/open", dependencies=[Depends(public("probe"))])
    async def open_route() -> dict[str, str]:
        return {}

    @app.get("/service/{workspace_id}")
    async def service(
        access: Annotated[WorkspaceAccess, Depends(requires(Permission.WORKSPACE_ACCESS))],
    ) -> dict[str, str]:
        ensure(access.permissions, Permission.MEMBERS_MANAGE)  # the service-layer check
        return {}

    return app


def _loader(monkeypatch: pytest.MonkeyPatch, access: WorkspaceAccess | None) -> list[object]:
    seen: list[object] = []

    async def load(conn: object, tenant: TenantContext, workspace_id: uuid.UUID) -> object:
        seen.append((tenant, workspace_id))
        return access

    monkeypatch.setattr(declarations, "load_workspace_access", load)
    return seen


def _org_loader(monkeypatch: pytest.MonkeyPatch, org_role: str | None) -> None:
    async def load(conn: object, tenant: TenantContext) -> OrgAccess:
        return OrgAccess(org_role, permissions_for(org_role, None))

    monkeypatch.setattr(declarations, "load_org_access", load)


def test_a_workspace_the_caller_cannot_see_is_404_not_found(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loader(monkeypatch, None)

    response = TestClient(app).get(f"/w/{WORKSPACE}/manage", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}


def test_a_visible_workspace_without_the_permission_is_403_forbidden(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loader(monkeypatch, _access(None, "builder"))

    response = TestClient(app).get(f"/w/{WORKSPACE}/manage", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


def test_the_permission_holder_passes_and_the_tenant_is_the_principals(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _loader(monkeypatch, _access(None, "workspace_admin"))

    response = TestClient(app).get(f"/w/{WORKSPACE}/manage", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"role": "workspace_admin"}
    assert seen == [(TenantContext(org_id=ORG, user_id=USER), WORKSPACE)]


def test_an_org_admin_passes_a_workspace_route_without_a_membership(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loader(monkeypatch, _access("org_admin", None))

    assert TestClient(app).get(f"/w/{WORKSPACE}/manage", headers=AUTH).status_code == 200


def test_an_org_route_needs_the_org_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(app)

    _org_loader(monkeypatch, "org_admin")
    denied = client.get("/org/roles", headers=AUTH)
    _org_loader(monkeypatch, None)
    nobody = client.get("/org/roles", headers=AUTH)
    _org_loader(monkeypatch, "org_owner")
    allowed = client.get("/org/roles", headers=AUTH)

    assert (denied.status_code, denied.json()) == (403, {"detail": "forbidden"})
    assert (nobody.status_code, nobody.json()) == (403, {"detail": "forbidden"})
    assert (allowed.status_code, allowed.json()) == (200, {"org_role": "org_owner"})


def test_every_dependency_answers_401_without_a_session(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loader(monkeypatch, _access("org_owner", None))
    client = TestClient(app)

    for path in (f"/w/{WORKSPACE}/manage", "/org/roles", "/me"):
        response = client.get(path)
        assert (response.status_code, response.json()) == (401, {"detail": "unauthenticated"})


def test_signed_in_and_public_need_no_permission(app: FastAPI) -> None:
    client = TestClient(app)

    assert client.get("/me", headers=AUTH).json() == {"user": str(USER)}
    assert client.get("/open").status_code == 200


def test_service_layer_denial_is_403_forbidden(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loader(monkeypatch, _access(None, "viewer"))

    response = TestClient(app).get(f"/service/{WORKSPACE}", headers=AUTH)

    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})


@pytest.mark.parametrize(
    ("headers", "params"),
    [
        ({"X-Role": "workspace_admin"}, {}),
        ({"X-Permissions": "members.manage"}, {}),
        ({"X-Org-Role": "org_owner", "X-Workspace-Role": "workspace_admin"}, {}),
        ({}, {"role": "workspace_admin"}),
        ({}, {"permissions": "members.manage", "org_role": "org_owner"}),
    ],
)
def test_ignores_client_role_header(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    params: dict[str, str],
) -> None:
    _loader(monkeypatch, _access(None, "viewer"))

    response = TestClient(app).get(
        f"/w/{WORKSPACE}/manage", headers={**AUTH, **headers}, params=params
    )

    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})


def test_a_permission_of_the_wrong_scope_fails_at_import() -> None:
    with pytest.raises(ValueError, match="org permission"):
        requires(Permission.ORG_ROLES_MANAGE)
    with pytest.raises(ValueError, match="workspace permission"):
        requires_org(Permission.MEMBERS_MANAGE)
    with pytest.raises(ValueError, match="platform permission"):
        requires(Permission.PLATFORM_ORGANIZATIONS_LIST)
    with pytest.raises(ValueError, match="reason"):
        public(" ")


def test_each_dependency_carries_its_declaration() -> None:
    assert declared(requires(Permission.MEMBERS_VIEW)) == "members.view"
    assert declared(requires_org(Permission.ORG_SETTINGS_MANAGE)) == "org.settings.manage"
    assert declared(signed_in()) == "signed_in"
    assert declared(public("probe")) == "public"
    assert declared(lambda: None) is None


def test_ensure_raises_permission_denied_for_a_missing_permission() -> None:
    ensure(frozenset({Permission.MEMBERS_MANAGE}), Permission.MEMBERS_MANAGE)
    with pytest.raises(PermissionDenied):
        ensure(frozenset({Permission.MEMBERS_VIEW}), Permission.MEMBERS_MANAGE)
    with pytest.raises(PermissionDenied):
        ensure(frozenset(), Permission.WORKSPACE_ACCESS)
