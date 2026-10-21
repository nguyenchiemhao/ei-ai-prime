"""AC4 and the NFR: assigning roles changes what a user can do in that Workspace only, and the
change applies to the user's next request."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from support.rbac.orgs import role_client
from support.sign_in import (
    PASSWORD,
    give_password,
    request_headers,
    session_cookie,
    sign_in,
)

from .conftest import MakeOrg

pytestmark = pytest.mark.integration


async def _permissions(
    client: httpx.AsyncClient, headers: dict[str, str], workspace_id: object
) -> list[str]:
    response = await client.get(f"/workspaces/{workspace_id}", headers=headers)
    assert response.status_code == 200
    permissions: list[str] = response.json()["permissions"]
    return permissions


async def test_org_admin_assigns_builder_in_x_only(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org(
        {
            "admin": ("org_admin", {}),  # not a member of x or y
            "user": (None, {"x": "viewer", "y": "viewer"}),
        }
    )
    x, y = org.workspace("x"), org.workspace("y")

    async with role_client(app_engine, org) as client:
        before = await _permissions(client, org.headers("user"), x)
        assigned = await client.put(
            f"/workspaces/{x}/members/{org.user('user')}",
            headers=org.headers("admin"),
            json={"role": "builder"},
        )
        in_x = await _permissions(client, org.headers("user"), x)
        in_y = await _permissions(client, org.headers("user"), y)
        session = await client.get("/auth/session", headers=org.headers("user"))

    assert "assistants.manage" not in before
    assert assigned.status_code == 200
    assert assigned.json()["role"] == "builder"
    assert "assistants.manage" in in_x
    assert "assistants.manage" not in in_y
    assert {w["id"]: w["role"] for w in session.json()["workspaces"]} == {
        str(x): "builder",
        str(y): "viewer",
    }


async def test_a_role_for_a_user_without_membership_here_needs_an_invitation(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org({"admin": ("org_admin", {}), "user": (None, {"y": "viewer"})})

    async with role_client(app_engine, org) as client:
        changed = await client.put(
            f"/workspaces/{org.workspace('x')}/members/{org.user('user')}",
            headers=org.headers("admin"),
            json={"role": "builder"},
        )
        invited = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("admin"),
            json={"email": org.people["user"].email, "role": "builder"},
        )
        in_x = await _permissions(client, org.headers("user"), org.workspace("x"))

    assert changed.status_code == 404
    assert invited.status_code == 201
    assert "assistants.manage" in in_x


async def test_change_applies_to_open_session_next_request(
    client: httpx.AsyncClient, app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    """NFR: real session cookies, no new sign-in: the very next request sees the new role."""
    org = await make_org(
        {"admin": ("org_admin", {"x": "workspace_admin"}), "user": (None, {"x": "builder"})}
    )
    for name in ("user", "admin"):
        await give_password(app_engine, org.org_id, org.user(name))
    user_cookie = session_cookie(await sign_in(client, org.people["user"].email, PASSWORD))
    admin_cookie = session_cookie(await sign_in(client, org.people["admin"].email, PASSWORD))
    x = org.workspace("x")

    before = (await client.get(f"/workspaces/{x}", headers=request_headers(user_cookie))).json()
    changed = await client.put(
        f"/workspaces/{x}/members/{org.user('user')}",
        headers=request_headers(admin_cookie),
        json={"role": "viewer"},
    )
    after = (await client.get(f"/workspaces/{x}", headers=request_headers(user_cookie))).json()
    listed = await client.get(f"/workspaces/{x}/members", headers=request_headers(user_cookie))

    assert "assistants.manage" in before["permissions"]
    assert changed.status_code == 200
    assert after["role"] == "viewer"
    assert "assistants.manage" not in after["permissions"]
    assert listed.status_code == 200  # a Viewer still sees the Members screen
