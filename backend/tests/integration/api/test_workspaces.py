"""GET /workspaces/{id} on the real database: members get their Workspace; an unknown id, a
same-Organization Workspace without membership and another Organization's Workspace all answer
alike (AC6, Review Focus 2). The default Workspace is read through sign-in and the session route."""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from support.sign_in import (
    PASSWORD,
    give_password,
    in_tenant,
    request_headers,
    session_cookie,
    sign_in,
)
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration


async def _signed_in(client: httpx.AsyncClient, engine: AsyncEngine, org: OrgRows) -> str:
    await give_password(engine, org.org_id, org.user_id)
    return session_cookie(await sign_in(client, org.email, PASSWORD))


async def _workspace(engine: AsyncEngine, org: OrgRows, name: str, role: str | None) -> uuid.UUID:
    """A new Workspace in ``org``; the fixture user joins it with ``role`` unless that is None."""
    workspace_id = uuid.uuid4()
    params = {"ws": workspace_id, "name": name, "user": org.user_id, "role": role}
    await in_tenant(
        engine,
        org.org_id,
        "INSERT INTO workspaces (id, org_id, name) VALUES (:ws, :org, :name)",
        params,
    )
    if role is not None:
        await in_tenant(
            engine,
            org.org_id,
            "INSERT INTO workspace_memberships (org_id, workspace_id, user_id, role)"
            " VALUES (:org, :ws, :user, :role)",
            params,
        )
    return workspace_id


async def _get(
    client: httpx.AsyncClient, cookie: str | None, workspace_id: uuid.UUID | str
) -> httpx.Response:
    return await client.get(f"/workspaces/{workspace_id}", headers=request_headers(cookie))


async def test_member_gets_workspace(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    builder = await _workspace(app_engine, a, f"Builder {a.suffix}", "builder")
    cookie = await _signed_in(client, app_engine, a)

    own = await _get(client, cookie, a.workspace_id)
    other = await _get(client, cookie, builder)

    assert own.status_code == 200
    assert own.json() == {
        "id": str(a.workspace_id),
        "name": a.names.workspace,
        "role": "member",
        "org_role": None,
        "permissions": ["workspace.access"],
    }
    assert other.status_code == 200
    assert other.json() == {
        "id": str(builder),
        "name": f"Builder {a.suffix}",
        "role": "builder",
        "org_role": None,
        "permissions": [
            "assistants.manage",
            "assistants.publish",
            "dashboard.view",
            "knowledge.manage",
            "members.view",
            "playground.use",
            "workspace.access",
        ],
    }


async def _set_org_role(engine: AsyncEngine, org: OrgRows, org_role: str | None) -> None:
    await in_tenant(
        engine,
        org.org_id,
        "UPDATE memberships SET org_role = :role WHERE org_id = :org AND user_id = :user",
        {"role": org_role, "user": org.user_id},
    )


async def test_org_admin_sees_every_workspace(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    others = await _workspace(app_engine, a, f"Others {a.suffix}", None)
    await _set_org_role(app_engine, a, "org_admin")
    cookie = await _signed_in(client, app_engine, a)

    member_of = await _get(client, cookie, a.workspace_id)
    not_member_of = await _get(client, cookie, others)
    other_org = await _get(client, cookie, b.workspace_id)

    assert member_of.json()["role"] == "member"
    assert not_member_of.status_code == 200
    body = not_member_of.json()
    assert (body["role"], body["org_role"]) == (None, "org_admin")
    assert "members.manage" in body["permissions"]
    assert "org.settings.manage" in body["permissions"]
    assert "org.roles.manage" not in body["permissions"]
    assert "conversations.read" not in body["permissions"]
    assert other_org.status_code == 404
    assert other_org.json() == {"detail": "not_found"}


async def test_non_member_still_404(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    hidden = await _workspace(app_engine, a, f"Hidden {a.suffix}", None)
    cookie = await _signed_in(client, app_engine, a)

    unknown = await _get(client, cookie, uuid.uuid4())
    not_member = await _get(client, cookie, hidden)

    assert (not_member.status_code, not_member.json()) == (404, {"detail": "not_found"})
    assert (not_member.status_code, not_member.content) == (unknown.status_code, unknown.content)


async def test_workspace_route_404_for_non_member_and_other_org(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    not_member = await _workspace(app_engine, a, f"Hidden {a.suffix}", None)
    cookie = await _signed_in(client, app_engine, a)

    unknown = await _get(client, cookie, uuid.uuid4())
    same_org = await _get(client, cookie, not_member)
    other_org = await _get(client, cookie, b.workspace_id)

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "not_found"}
    for response in (same_org, other_org):
        assert response.status_code == unknown.status_code
        assert response.json() == unknown.json()
        assert f"Hidden {a.suffix}" not in response.text
        for marker in b.markers():
            assert marker not in response.text


async def test_workspace_route_unauthenticated_is_401(
    client: httpx.AsyncClient, two_orgs: TwoOrgs
) -> None:
    response = await _get(client, None, two_orgs.a.workspace_id)

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}


async def test_default_workspace_is_earliest_membership(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    earlier = await _workspace(app_engine, a, f"Earlier {a.suffix}", "builder")
    await in_tenant(
        app_engine,
        a.org_id,
        "UPDATE workspace_memberships SET created_at = now() - interval '1 day'"
        " WHERE org_id = :org AND workspace_id = :ws",
        {"ws": earlier},
    )
    await give_password(app_engine, a.org_id, a.user_id)

    signed_in = await sign_in(client, a.email, PASSWORD)
    session = await client.get("/auth/session", headers=request_headers(session_cookie(signed_in)))

    assert signed_in.json() == {"default_workspace_id": str(earlier)}
    assert session.json()["default_workspace_id"] == str(earlier)
    assert (await _get(client, session_cookie(signed_in), earlier)).status_code == 200


async def test_no_membership_default_is_null(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await in_tenant(app_engine, a.org_id, "DELETE FROM workspace_memberships WHERE org_id = :org")
    await give_password(app_engine, a.org_id, a.user_id)

    signed_in = await sign_in(client, a.email, PASSWORD)
    cookie = session_cookie(signed_in)
    session = await client.get("/auth/session", headers=request_headers(cookie))

    assert signed_in.json() == {"default_workspace_id": None}
    assert session.json()["default_workspace_id"] is None
    assert session.json()["workspaces"] == []
    assert (await _get(client, cookie, a.workspace_id)).status_code == 404


async def test_malformed_workspace_id_is_422_without_echo(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    cookie = await _signed_in(client, app_engine, two_orgs.a)

    response = await _get(client, cookie, "not-a-uuid")

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    assert "not-a-uuid" not in response.text
