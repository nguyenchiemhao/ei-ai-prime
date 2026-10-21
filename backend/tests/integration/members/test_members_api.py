"""The Members & roles API on the real database: list, invite, change, revoke, and its refusals."""

import logging
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from support.rbac.orgs import RoleOrg, role_client
from support.sign_in import in_tenant

from .conftest import MakeOrg

pytestmark = pytest.mark.integration


async def _rows(engine: AsyncEngine, org: RoleOrg, sql: str, **params: object) -> list[object]:
    return list(await in_tenant(engine, org.org_id, sql, params))


async def test_list_returns_members_in_joining_order_with_roles(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org(
        {
            "first": ("org_admin", {"x": "workspace_admin"}),
            "second": (None, {"x": "builder"}),
            "third": (None, {"x": "viewer"}),
            "elsewhere": (None, {"y": "viewer"}),
        }
    )

    async with role_client(app_engine, org) as client:
        response = await client.get(
            f"/workspaces/{org.workspace('x')}/members", headers=org.headers("third")
        )

    assert response.status_code == 200
    members = response.json()["members"]
    assert [m["user_id"] for m in members] == [
        str(org.user("first")),
        str(org.user("second")),
        str(org.user("third")),
    ]
    assert members[0] == {
        "user_id": str(org.user("first")),
        "display_name": org.people["first"].display_name,
        "email": org.people["first"].email,
        "role": "workspace_admin",
        "org_role": "org_admin",
        "last_active_at": None,
    }
    assert [(m["role"], m["org_role"]) for m in members[1:]] == [
        ("builder", None),
        ("viewer", None),
    ]


async def test_last_active_is_the_latest_session_use_or_sign_event(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org(
        {"admin": ("org_admin", {"x": "workspace_admin"}), "other": (None, {"x": "viewer"})}
    )
    admin = org.user("admin")
    await in_tenant(
        app_engine,
        org.org_id,
        "INSERT INTO audit_events (org_id, actor, action, target_type, target_id, created_at)"
        " VALUES (:org, :actor, 'user.signed_in', 'user', :user, now() - interval '3 days')",
        {"actor": f"user:{admin}", "user": admin},
    )
    await in_tenant(
        app_engine,
        org.org_id,
        "INSERT INTO audit_events (org_id, actor, action, target_type, target_id, created_at)"
        " VALUES (:org, :actor, 'member.workspace_role_changed', 'user', :user, now())",
        {"actor": f"user:{admin}", "user": admin},
    )

    async with role_client(app_engine, org) as client:
        before = await client.get(
            f"/workspaces/{org.workspace('x')}/members", headers=org.headers("admin")
        )
        await in_tenant(
            app_engine,
            org.org_id,
            "INSERT INTO admin_sessions (org_id, user_id, token_hash, last_seen_at)"
            " VALUES (:org, :user, :hash, now() - interval '1 day')",
            {"user": admin, "hash": "a" * 64},
        )
        after = await client.get(
            f"/workspaces/{org.workspace('x')}/members", headers=org.headers("admin")
        )

    by_user = {m["user_id"]: m for m in before.json()["members"]}
    assert by_user[str(org.user("other"))]["last_active_at"] is None
    stale = by_user[str(admin)]["last_active_at"]
    fresh = {m["user_id"]: m for m in after.json()["members"]}[str(admin)]["last_active_at"]
    assert stale is not None
    assert fresh is not None
    assert (
        fresh > stale
    )  # the 1-day-old session beats the 3-day-old sign-in; role events do not count


async def test_manager_invites_a_new_person_and_a_token_is_stored_not_returned(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    email = f"New.Person.{org.suffix}@Example.invalid"

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("ws_admin"),
            json={"email": f" {email} ", "display_name": " New Person ", "role": "builder"},
        )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"user_id", "display_name", "email", "role", "org_role", "last_active_at"}
    assert (body["email"], body["display_name"], body["role"], body["org_role"]) == (
        email.lower(),
        "New Person",
        "builder",
        None,
    )
    assert body["last_active_at"] is None
    assert "token" not in response.text.lower()
    assert "password" not in response.text.lower()
    tokens = await _rows(
        app_engine,
        org,
        "SELECT used_at FROM set_password_tokens WHERE org_id = :org AND user_id = :user",
        user=uuid.UUID(body["user_id"]),
    )
    assert [row[0] for row in tokens] == [None]  # type: ignore[index]


async def test_invite_without_a_name_uses_the_local_part(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("owner"),
            json={"email": f"ann.lee.{org.suffix}@example.invalid", "role": "viewer"},
        )

    assert response.status_code == 201
    assert response.json()["display_name"] == f"ann.lee.{org.suffix}"


async def test_invite_adds_an_existing_user_of_the_organization_and_keeps_their_name(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    outsider = org.people["outsider"]

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("ws_admin"),
            json={"email": outsider.email.upper(), "display_name": "Ignored", "role": "reviewer"},
        )

    assert response.status_code == 201
    assert response.json()["user_id"] == str(outsider.user_id)
    assert response.json()["display_name"] == outsider.display_name
    assert response.json()["role"] == "reviewer"
    users = await _rows(
        app_engine,
        org,
        "SELECT count(*) FROM users WHERE org_id = :org AND email = :email",
        email=outsider.email,
    )
    assert users == [(1,)]


async def test_invite_of_a_current_member_is_409_already_member(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("ws_admin"),
            json={"email": org.people["viewer"].email, "role": "builder"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "already_member"}
    roles = await _rows(
        app_engine,
        org,
        "SELECT role FROM workspace_memberships WHERE org_id = :org AND user_id = :user"
        " AND workspace_id = :ws",
        user=org.user("viewer"),
        ws=org.workspace("x"),
    )
    assert roles == [("viewer",)]


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "role": "viewer"},
        {"email": "a@b", "role": "viewer"},
        {"email": "x" * 70 + "@example.invalid", "role": "viewer"},
        {"email": "ok@example.invalid", "role": "member"},
        {"email": "ok@example.invalid", "role": "org_owner"},
        {"email": "ok@example.invalid", "role": "boss"},
        {"email": "ok@example.invalid", "role": "Builder"},
        {"email": "ok@example.invalid"},
        {"role": "viewer"},
        {"email": "ok@example.invalid", "role": "viewer", "display_name": ""},
        {"email": "ok@example.invalid", "role": "viewer", "display_name": "x" * 201},
        {"email": "ok@example.invalid", "role": "viewer", "display_name": "   "},
        {"email": 7, "role": "viewer"},
    ],
)
async def test_invalid_invites_are_422_invalid_request_without_echo(
    app_engine: AsyncEngine, make_org: MakeOrg, body: dict[str, object]
) -> None:
    org = await make_org()
    before = await _rows(app_engine, org, "SELECT count(*) FROM users WHERE org_id = :org")

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members", headers=org.headers("owner"), json=body
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    assert await _rows(app_engine, org, "SELECT count(*) FROM users WHERE org_id = :org") == before


async def test_rejects_org_role_in_workspace_body(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    ws = org.workspace("x")
    viewer = org.user("viewer")

    async with role_client(app_engine, org) as client:
        invite = await client.post(
            f"/workspaces/{ws}/members",
            headers=org.headers("ws_admin"),
            json={
                "email": f"e.{org.suffix}@example.invalid",
                "role": "viewer",
                "org_role": "org_owner",
            },
        )
        invite_user_id = await client.post(
            f"/workspaces/{ws}/members",
            headers=org.headers("ws_admin"),
            json={
                "email": f"f.{org.suffix}@example.invalid",
                "role": "viewer",
                "user_id": str(viewer),
            },
        )
        change = await client.put(
            f"/workspaces/{ws}/members/{viewer}",
            headers=org.headers("ws_admin"),
            json={"role": "builder", "org_role": "org_owner"},
        )
        as_role = await client.put(
            f"/workspaces/{ws}/members/{viewer}",
            headers=org.headers("ws_admin"),
            json={"role": "org_owner"},
        )

    for response in (invite, invite_user_id, change, as_role):
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_request"}
    assert await _rows(
        app_engine,
        org,
        "SELECT org_role FROM memberships WHERE org_id = :org AND user_id = :user",
        user=viewer,
    ) == [(None,)]


async def test_change_role_returns_the_member_and_applies(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        response = await client.put(
            f"/workspaces/{org.workspace('x')}/members/{org.user('viewer')}",
            headers=org.headers("ws_admin"),
            json={"role": "knowledge_editor"},
        )
        same = await client.put(
            f"/workspaces/{org.workspace('x')}/members/{org.user('viewer')}",
            headers=org.headers("ws_admin"),
            json={"role": "knowledge_editor"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == "knowledge_editor"
    assert response.json()["user_id"] == str(org.user("viewer"))
    assert (same.status_code, same.json()) == (200, response.json())


async def test_target_not_in_this_workspace_404(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    ws = org.workspace("x")

    async with role_client(app_engine, org) as client:
        # reviewer is in x only; "elsewhere" below is a member of y only, targeted through x
        outsider = await client.put(
            f"/workspaces/{ws}/members/{org.user('outsider')}",
            headers=org.headers("ws_admin"),
            json={"role": "viewer"},
        )
        unknown = await client.put(
            f"/workspaces/{ws}/members/{uuid.uuid4()}",
            headers=org.headers("ws_admin"),
            json={"role": "viewer"},
        )
        delete_outsider = await client.delete(
            f"/workspaces/{ws}/members/{org.user('outsider')}", headers=org.headers("ws_admin")
        )

    for response in (outsider, unknown, delete_outsider):
        assert response.status_code == 404
        assert response.json() == {"detail": "not_found"}
    assert await _rows(
        app_engine,
        org,
        "SELECT count(*) FROM workspace_memberships WHERE org_id = :org AND user_id = :user",
        user=org.user("outsider"),
    ) == [(0,)]


async def test_member_of_another_workspace_cannot_be_targeted_through_this_one(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org(
        {"admin_x": (None, {"x": "workspace_admin"}), "only_y": (None, {"y": "viewer"})}
    )

    async with role_client(app_engine, org) as client:
        response = await client.put(
            f"/workspaces/{org.workspace('x')}/members/{org.user('only_y')}",
            headers=org.headers("admin_x"),
            json={"role": "workspace_admin"},
        )

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert await _rows(
        app_engine,
        org,
        "SELECT role FROM workspace_memberships WHERE org_id = :org AND user_id = :user",
        user=org.user("only_y"),
    ) == [("viewer",)]


async def test_revoke_removes_the_workspace_role_and_keeps_the_account(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    ws = org.workspace("x")

    async with role_client(app_engine, org) as client:
        response = await client.delete(
            f"/workspaces/{ws}/members/{org.user('viewer')}", headers=org.headers("owner")
        )
        gone = await client.get(f"/workspaces/{ws}", headers=org.headers("viewer"))
        other_workspace = await client.get(
            f"/workspaces/{org.workspace('y')}", headers=org.headers("viewer")
        )
        again = await client.delete(
            f"/workspaces/{ws}/members/{org.user('viewer')}", headers=org.headers("owner")
        )

    assert response.status_code == 204
    assert response.content == b""
    assert (gone.status_code, gone.json()) == (404, {"detail": "not_found"})
    assert other_workspace.status_code == 200  # the other Workspace role is untouched
    assert again.status_code == 404
    assert await _rows(
        app_engine,
        org,
        "SELECT count(*) FROM users WHERE org_id = :org AND id = :user",
        user=org.user("viewer"),
    ) == [(1,)]


async def test_viewer_can_list_but_not_change_anything(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    ws = org.workspace("x")
    target = org.user("builder")

    async with role_client(app_engine, org) as client:
        listing = await client.get(f"/workspaces/{ws}/members", headers=org.headers("viewer"))
        invite = await client.post(
            f"/workspaces/{ws}/members",
            headers=org.headers("viewer"),
            json={"email": f"v.{org.suffix}@example.invalid", "role": "viewer"},
        )
        change = await client.put(
            f"/workspaces/{ws}/members/{target}",
            headers=org.headers("viewer"),
            json={"role": "viewer"},
        )
        remove = await client.delete(
            f"/workspaces/{ws}/members/{target}", headers=org.headers("viewer")
        )
        bad_body = await client.put(
            f"/workspaces/{ws}/members/{target}",
            headers=org.headers("viewer"),
            json={"role": "boss"},
        )

    assert listing.status_code == 200
    for response in (invite, change, remove, bad_body):
        assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})


async def test_member_role_cannot_list_members(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        response = await client.get(
            f"/workspaces/{org.workspace('x')}/members", headers=org.headers("member")
        )

    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})


async def test_outsider_and_unknown_workspace_look_the_same(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        outsider = await client.get(
            f"/workspaces/{org.workspace('x')}/members", headers=org.headers("outsider")
        )
        unknown = await client.get(
            f"/workspaces/{uuid.uuid4()}/members", headers=org.headers("outsider")
        )

    assert (outsider.status_code, outsider.content) == (unknown.status_code, unknown.content)
    assert outsider.status_code == 404


async def test_invite_logs_no_email(
    app_engine: AsyncEngine, make_org: MakeOrg, caplog: pytest.LogCaptureFixture
) -> None:
    org = await make_org()
    email = f"private.person.{org.suffix}@example.invalid"
    caplog.set_level(logging.DEBUG)

    async with role_client(app_engine, org) as client:
        created = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("owner"),
            json={"email": email, "display_name": f"Private Name {org.suffix}", "role": "viewer"},
        )
        duplicate = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("owner"),
            json={"email": email, "role": "viewer"},
        )
        invalid = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("owner"),
            json={"email": f"bad {email}", "role": "viewer"},
        )

    assert [created.status_code, duplicate.status_code, invalid.status_code] == [201, 409, 422]
    assert email not in caplog.text
    assert f"Private Name {org.suffix}" not in caplog.text
    assert org.suffix not in invalid.text
    assert org.suffix not in duplicate.text


async def test_org_role_route_returns_the_new_role(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    target = org.user("builder")

    async with role_client(app_engine, org) as client:
        promoted = await client.put(
            f"/organization/members/{target}/org-role",
            headers=org.headers("owner"),
            json={"org_role": "org_admin"},
        )
        removed = await client.put(
            f"/organization/members/{target}/org-role",
            headers=org.headers("owner"),
            json={"org_role": None},
        )
        invalid = await client.put(
            f"/organization/members/{target}/org-role",
            headers=org.headers("owner"),
            json={"org_role": "workspace_admin"},
        )
        missing = await client.put(
            f"/organization/members/{target}/org-role", headers=org.headers("owner"), json={}
        )
        unknown = await client.put(
            f"/organization/members/{uuid.uuid4()}/org-role",
            headers=org.headers("owner"),
            json={"org_role": "org_admin"},
        )

    assert (promoted.status_code, promoted.json()) == (
        200,
        {"user_id": str(target), "org_role": "org_admin"},
    )
    assert (removed.status_code, removed.json()) == (
        200,
        {"user_id": str(target), "org_role": None},
    )
    assert (invalid.status_code, invalid.json()) == (422, {"detail": "invalid_request"})
    assert missing.status_code == 422
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "not_found"})


async def test_unauthenticated_calls_are_401(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    ws = org.workspace("x")
    user = org.user("viewer")

    async with role_client(app_engine, org) as client:
        responses = [
            await client.get(f"/workspaces/{ws}/members"),
            await client.post(f"/workspaces/{ws}/members", json={}),
            await client.put(f"/workspaces/{ws}/members/{user}", json={}),
            await client.delete(f"/workspaces/{ws}/members/{user}"),
            await client.put(f"/organization/members/{user}/org-role", json={}),
        ]

    assert [r.status_code for r in responses] == [401] * 5
    assert {r.json()["detail"] for r in responses} == {"unauthenticated"}
