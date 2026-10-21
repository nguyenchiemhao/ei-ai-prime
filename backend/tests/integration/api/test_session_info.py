"""GET /auth/session on the real database: the caller's own user, Organization and Workspaces,
and 401 for every cookie that does not name a live session (AC5, Review Focus 3)."""

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.sessions import IDLE_TIMEOUT
from ei_ai.auth.tokens import hash_secret, parse_token
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


async def _get(client: httpx.AsyncClient, cookie: str | None) -> httpx.Response:
    return await client.get("/auth/session", headers=request_headers(cookie))


async def test_session_info_lists_only_memberships(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    alpha = await _workspace(app_engine, a, f"Alpha {a.suffix}", "builder")
    await _workspace(app_engine, a, f"Beta {a.suffix}", None)
    cookie = await _signed_in(client, app_engine, a)

    response = await _get(client, cookie)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "user": {"id": str(a.user_id), "display_name": a.names.user, "email": a.email},
        "organization": {"id": str(a.org_id), "name": a.names.organization},
        "org_role": None,
        "workspaces": [
            {"id": str(alpha), "name": f"Alpha {a.suffix}", "role": "builder"},
            {"id": str(a.workspace_id), "name": a.names.workspace, "role": "member"},
        ],
        "default_workspace_id": str(a.workspace_id),
    }
    assert f"Beta {a.suffix}" not in response.text
    for marker in b.markers():
        assert marker not in response.text


async def test_org_owner_lists_every_workspace_and_the_org_role(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    unjoined = await _workspace(app_engine, a, f"Unjoined {a.suffix}", None)
    await in_tenant(
        app_engine,
        a.org_id,
        "UPDATE memberships SET org_role = 'org_owner' WHERE org_id = :org AND user_id = :user",
        {"user": a.user_id},
    )
    cookie = await _signed_in(client, app_engine, a)

    body = (await _get(client, cookie)).json()

    assert body["org_role"] == "org_owner"
    assert {w["id"]: w["role"] for w in body["workspaces"]} == {
        str(a.workspace_id): "member",
        str(unjoined): None,
    }
    assert body["default_workspace_id"] == str(a.workspace_id)


async def test_org_admin_without_membership_gets_the_first_workspace_as_default(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await in_tenant(app_engine, a.org_id, "DELETE FROM workspace_memberships WHERE org_id = :org")
    await in_tenant(
        app_engine,
        a.org_id,
        "UPDATE memberships SET org_role = 'org_admin' WHERE org_id = :org AND user_id = :user",
        {"user": a.user_id},
    )
    cookie = await _signed_in(client, app_engine, a)

    body = (await _get(client, cookie)).json()

    assert body["default_workspace_id"] == str(a.workspace_id)
    assert [w["role"] for w in body["workspaces"]] == [None]


async def test_session_info_ignores_forged_organization_fields(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    cookie = await _signed_in(client, app_engine, a)

    response = await client.get(
        "/auth/session",
        headers={**request_headers(cookie), "X-Org-Id": str(b.org_id)},
        params={"org_id": str(b.org_id)},
    )

    assert response.status_code == 200
    assert response.json()["organization"]["id"] == str(a.org_id)


async def test_session_route_without_cookie_is_401(client: httpx.AsyncClient) -> None:
    response = await _get(client, None)

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "cookie",
    [
        "",
        "garbage",
        f"{uuid.uuid4()}.short",
        f"not-a-uuid.{'a' * 43}",
        f"{uuid.uuid4()}.{'a' * 43}",
    ],
)
async def test_malformed_or_unknown_cookie_is_401(client: httpx.AsyncClient, cookie: str) -> None:
    response = await _get(client, cookie)

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}


async def test_idle_expired_session_is_401(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    cookie = await _signed_in(client, app_engine, a)
    parsed = parse_token(cookie)
    assert parsed is not None
    assert (await _get(client, cookie)).status_code == 200

    await in_tenant(
        app_engine,
        a.org_id,
        "UPDATE admin_sessions SET last_seen_at = now() - :age"
        " WHERE org_id = :org AND token_hash = :hash",
        {"age": IDLE_TIMEOUT + timedelta(minutes=1), "hash": hash_secret(parsed[1])},
    )

    assert (await _get(client, cookie)).status_code == 401
