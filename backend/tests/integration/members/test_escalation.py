"""AC5 and the escalation attacks: nobody raises themselves or anyone else beyond their grant."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from support.rbac.orgs import RoleOrg, role_client
from support.sign_in import in_tenant

from .conftest import MakeOrg

pytestmark = pytest.mark.integration

FORBIDDEN = {"detail": "forbidden"}


async def _org_role(engine: AsyncEngine, org: RoleOrg, name: str) -> str | None:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT org_role FROM memberships WHERE org_id = :org AND user_id = :user",
        {"user": org.user(name)},
    )
    role: str | None = rows[0][0]
    return role


async def _role_events(engine: AsyncEngine, org: RoleOrg) -> int:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT count(*) FROM audit_events WHERE org_id = :org"
        " AND action = 'member.org_role_changed'",
    )
    count: int = rows[0][0]
    return count


@pytest.mark.parametrize("caller", ["ws_admin", "org_admin", "builder", "viewer", "outsider"])
async def test_nobody_but_an_org_owner_grants_org_owner(
    app_engine: AsyncEngine, make_org: MakeOrg, caller: str
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        to_self = await client.put(
            f"/organization/members/{org.user(caller)}/org-role",
            headers=org.headers(caller),
            json={"org_role": "org_owner"},
        )
        to_other = await client.put(
            f"/organization/members/{org.user('viewer')}/org-role",
            headers=org.headers(caller),
            json={"org_role": "org_admin"},
        )

    for response in (to_self, to_other):
        assert (response.status_code, response.json()) == (403, FORBIDDEN)
    assert await _org_role(app_engine, org, caller) == (
        "org_admin" if caller == "org_admin" else None
    )
    assert await _org_role(app_engine, org, "viewer") is None
    assert await _role_events(app_engine, org) == 0


async def test_org_owner_grants_and_revokes_org_roles(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        granted = await client.put(
            f"/organization/members/{org.user('builder')}/org-role",
            headers=org.headers("owner"),
            json={"org_role": "org_owner"},
        )
        revoked = await client.put(
            f"/organization/members/{org.user('org_admin')}/org-role",
            headers=org.headers("owner"),
            json={"org_role": None},
        )

    assert (granted.status_code, revoked.status_code) == (200, 200)
    assert await _org_role(app_engine, org, "builder") == "org_owner"
    assert await _org_role(app_engine, org, "org_admin") is None


async def test_builder_cannot_make_themselves_workspace_admin(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        response = await client.put(
            f"/workspaces/{org.workspace('x')}/members/{org.user('builder')}",
            headers=org.headers("builder"),
            json={"role": "workspace_admin"},
        )

    assert (response.status_code, response.json()) == (403, FORBIDDEN)
    rows = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT role FROM workspace_memberships WHERE org_id = :org AND user_id = :user",
        {"user": org.user("builder")},
    )
    assert rows == [("builder",)]


async def test_workspace_admin_of_x_cannot_edit_workspace_y(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    y = org.workspace("y")

    async with role_client(app_engine, org) as client:
        change = await client.put(
            f"/workspaces/{y}/members/{org.user('viewer')}",
            headers=org.headers("ws_admin"),
            json={"role": "workspace_admin"},
        )
        invite = await client.post(
            f"/workspaces/{y}/members",
            headers=org.headers("ws_admin"),
            json={"email": f"z.{org.suffix}@example.invalid", "role": "viewer"},
        )
        remove = await client.delete(
            f"/workspaces/{y}/members/{org.user('viewer')}", headers=org.headers("ws_admin")
        )

    for response in (change, invite, remove):
        assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    rows = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT role FROM workspace_memberships WHERE org_id = :org AND user_id = :user"
        " AND workspace_id = :ws",
        {"user": org.user("viewer"), "ws": y},
    )
    assert rows == [("viewer",)]


async def test_workspace_admin_may_grant_workspace_admin_laterally(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        response = await client.put(
            f"/workspaces/{org.workspace('x')}/members/{org.user('viewer')}",
            headers=org.headers("ws_admin"),
            json={"role": "workspace_admin"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == "workspace_admin"


async def test_last_owner_409(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org({"owner": ("org_owner", {}), "admin": ("org_admin", {})})

    async with role_client(app_engine, org) as client:
        demote = await client.put(
            f"/organization/members/{org.user('owner')}/org-role",
            headers=org.headers("owner"),
            json={"org_role": "org_admin"},
        )
        remove = await client.put(
            f"/organization/members/{org.user('owner')}/org-role",
            headers=org.headers("owner"),
            json={"org_role": None},
        )

    for response in (demote, remove):
        assert (response.status_code, response.json()) == (409, {"detail": "last_org_owner"})
    assert await _org_role(app_engine, org, "owner") == "org_owner"
    assert await _role_events(app_engine, org) == 0


async def test_an_owner_may_step_down_while_another_owner_remains(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org({"first": ("org_owner", {}), "second": ("org_owner", {})})

    async with role_client(app_engine, org) as client:
        stepped_down = await client.put(
            f"/organization/members/{org.user('first')}/org-role",
            headers=org.headers("first"),
            json={"org_role": "org_admin"},
        )
        last = await client.put(
            f"/organization/members/{org.user('second')}/org-role",
            headers=org.headers("second"),
            json={"org_role": "org_admin"},
        )

    assert stepped_down.status_code == 200
    assert (last.status_code, last.json()) == (409, {"detail": "last_org_owner"})


async def test_org_role_of_another_organizations_user_is_404(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    mine = await make_org({"owner": ("org_owner", {})})
    theirs = await make_org({"owner": ("org_owner", {})})

    async with role_client(app_engine, mine, theirs) as client:
        response = await client.put(
            f"/organization/members/{theirs.user('owner')}/org-role",
            headers=mine.headers("owner"),
            json={"org_role": None},
        )
        unknown = await client.put(
            f"/organization/members/{uuid.uuid4()}/org-role",
            headers=mine.headers("owner"),
            json={"org_role": None},
        )

    assert (response.status_code, response.content) == (unknown.status_code, unknown.content)
    assert response.status_code == 404
    assert await _org_role(app_engine, theirs, "owner") == "org_owner"
