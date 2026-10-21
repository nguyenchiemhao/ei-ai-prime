"""AC6: every role change is audited (who, for whom, where, old to new), in the same transaction."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit import events
from support.rbac.orgs import RoleOrg, role_client
from support.sign_in import in_tenant

from .conftest import MakeOrg

pytestmark = pytest.mark.integration

ROLE_EVENTS = "('member.workspace_role_changed', 'member.org_role_changed')"


async def _events(engine: AsyncEngine, org: RoleOrg) -> list[tuple[object, ...]]:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT actor, action, target_type, target_id, workspace_id, old_value, new_value"
        " FROM audit_events WHERE org_id = :org AND action IN " + ROLE_EVENTS + " ORDER BY id",
    )
    return [tuple(row) for row in rows]


async def test_workspace_role_change_is_audited_with_who_whom_where_and_old_new(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    ws = org.workspace("x")

    async with role_client(app_engine, org) as client:
        response = await client.put(
            f"/workspaces/{ws}/members/{org.user('viewer')}",
            headers=org.headers("org_admin"),
            json={"role": "builder"},
        )

    assert response.status_code == 200
    assert await _events(app_engine, org) == [
        (
            f"user:{org.user('org_admin')}",
            "member.workspace_role_changed",
            "user",
            org.user("viewer"),
            ws,
            "viewer",
            "builder",
        )
    ]


async def test_an_admin_assigning_themselves_reviewer_is_audited(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org({"admin": ("org_admin", {"x": "workspace_admin"})})
    admin = org.user("admin")

    async with role_client(app_engine, org) as client:
        response = await client.put(
            f"/workspaces/{org.workspace('x')}/members/{admin}",
            headers=org.headers("admin"),
            json={"role": "reviewer"},
        )
        permissions = (
            await client.get(f"/workspaces/{org.workspace('x')}", headers=org.headers("admin"))
        ).json()["permissions"]

    assert response.status_code == 200
    assert await _events(app_engine, org) == [
        (
            f"user:{admin}",
            "member.workspace_role_changed",
            "user",
            admin,
            org.workspace("x"),
            "workspace_admin",
            "reviewer",
        )
    ]
    # The Org Admin keeps the Admin rights and now reads conversations (the matrix footnote).
    assert "conversations.read" in permissions
    assert "members.manage" in permissions


async def test_invite_audits_the_invitation_and_the_role(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    actor = f"user:{org.user('ws_admin')}"

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("ws_admin"),
            json={"email": f"new.{org.suffix}@example.invalid", "role": "developer"},
        )
        existing = await client.post(
            f"/workspaces/{org.workspace('y')}/members",
            headers=org.headers("owner"),
            json={"email": org.people["outsider"].email, "role": "viewer"},
        )

    new_user = uuid.UUID(response.json()["user_id"])
    assert response.status_code == existing.status_code == 201
    assert await _events(app_engine, org) == [
        (
            actor,
            "member.workspace_role_changed",
            "user",
            new_user,
            org.workspace("x"),
            None,
            "developer",
        ),
        (
            f"user:{org.user('owner')}",
            "member.workspace_role_changed",
            "user",
            org.user("outsider"),
            org.workspace("y"),
            None,
            "viewer",
        ),
    ]
    invited = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT actor, target_id FROM audit_events WHERE org_id = :org AND action = 'user.invited'",
    )
    assert [tuple(row) for row in invited] == [(actor, new_user)]


async def test_revoke_and_org_role_change_are_audited(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        await client.delete(
            f"/workspaces/{org.workspace('x')}/members/{org.user('builder')}",
            headers=org.headers("ws_admin"),
        )
        await client.put(
            f"/organization/members/{org.user('viewer')}/org-role",
            headers=org.headers("owner"),
            json={"org_role": "org_admin"},
        )

    assert await _events(app_engine, org) == [
        (
            f"user:{org.user('ws_admin')}",
            "member.workspace_role_changed",
            "user",
            org.user("builder"),
            org.workspace("x"),
            "builder",
            None,
        ),
        (
            f"user:{org.user('owner')}",
            "member.org_role_changed",
            "user",
            org.user("viewer"),
            None,
            None,
            "org_admin",
        ),
    ]


async def test_no_op_and_refused_calls_write_no_event(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    ws = org.workspace("x")

    async with role_client(app_engine, org) as client:
        same_workspace_role = await client.put(
            f"/workspaces/{ws}/members/{org.user('viewer')}",
            headers=org.headers("ws_admin"),
            json={"role": "viewer"},
        )
        same_org_role = await client.put(
            f"/organization/members/{org.user('org_admin')}/org-role",
            headers=org.headers("owner"),
            json={"org_role": "org_admin"},
        )
        refused = await client.put(
            f"/workspaces/{ws}/members/{org.user('viewer')}",
            headers=org.headers("builder"),
            json={"role": "builder"},
        )
        missing = await client.put(
            f"/workspaces/{ws}/members/{uuid.uuid4()}",
            headers=org.headers("owner"),
            json={"role": "builder"},
        )
        invalid = await client.put(
            f"/workspaces/{ws}/members/{org.user('viewer')}",
            headers=org.headers("owner"),
            json={"role": "member"},
        )
        duplicate = await client.post(
            f"/workspaces/{ws}/members",
            headers=org.headers("owner"),
            json={"email": org.people["viewer"].email, "role": "viewer"},
        )

    assert [
        r.status_code
        for r in (same_workspace_role, same_org_role, refused, missing, invalid, duplicate)
    ] == [200, 200, 403, 404, 422, 409]
    assert await _events(app_engine, org) == []


async def test_a_failing_audit_insert_keeps_the_old_role(
    app_engine: AsyncEngine, make_org: MakeOrg, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await make_org()
    ws = org.workspace("x")
    viewer = org.user("viewer")

    async def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the audit insert failed")

    monkeypatch.setattr(events, "record_event", failing)

    async with role_client(app_engine, org) as client:
        with pytest.raises(RuntimeError):
            await client.put(
                f"/workspaces/{ws}/members/{viewer}",
                headers=org.headers("owner"),
                json={"role": "workspace_admin"},
            )
        with pytest.raises(RuntimeError):
            await client.put(
                f"/organization/members/{viewer}/org-role",
                headers=org.headers("owner"),
                json={"org_role": "org_owner"},
            )
        with pytest.raises(RuntimeError):
            await client.delete(f"/workspaces/{ws}/members/{viewer}", headers=org.headers("owner"))

    rows = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT wm.role, m.org_role FROM memberships m JOIN workspace_memberships wm"
        " ON wm.org_id = m.org_id AND wm.user_id = m.user_id"
        " WHERE m.org_id = :org AND m.user_id = :user AND wm.workspace_id = :ws",
        {"user": viewer, "ws": ws},
    )
    assert [tuple(row) for row in rows] == [("viewer", None)]
