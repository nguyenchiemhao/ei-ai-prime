"""The service layer checks permissions itself (ticket technical note), refuses a caller who would
lock themselves out, and survives the races of an invitation. The functions are called directly,
without the route dependency, so a removed ``ensure`` cannot hide behind the route."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.members import service
from ei_ai.members.rows import find_member_row, find_user_id
from ei_ai.rbac.access import (
    OrgAccess,
    PermissionDenied,
    WorkspaceAccess,
    load_org_access,
    load_workspace_access,
)
from ei_ai.tenancy.context import TenantContext
from support.rbac.orgs import RoleOrg, role_client
from support.sign_in import in_tenant

from .conftest import MakeOrg

pytestmark = pytest.mark.integration


async def _run(
    engine: AsyncEngine,
    org: RoleOrg,
    actor: str,
    work: Callable[[Any, TenantContext, WorkspaceAccess, OrgAccess], Awaitable[object]],
) -> object:
    """Run ``work`` in the actor's tenant transaction with the actor's real access objects."""
    tenant = TenantContext(org_id=org.org_id, user_id=org.user(actor))
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        access = await load_workspace_access(conn, tenant, org.workspace("x"))
        assert access is not None, f"{actor} cannot see workspace x"
        return await work(conn, tenant, access, await load_org_access(conn, tenant))


async def _state(engine: AsyncEngine, org: RoleOrg) -> list[object]:
    """Everything a role change could touch: users, memberships, Workspace roles, audit rows."""
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT 'user', count(*)::text FROM users WHERE org_id = :org UNION ALL"
        " SELECT 'm:' || user_id::text, coalesce(org_role, '-') FROM memberships"
        " WHERE org_id = :org UNION ALL"
        " SELECT 'w:' || user_id::text || workspace_id::text, role FROM workspace_memberships"
        " WHERE org_id = :org UNION ALL"
        " SELECT 'audit', count(*)::text FROM audit_events WHERE org_id = :org ORDER BY 1, 2",
    )
    return [tuple(row) for row in rows]


def _calls(org: RoleOrg) -> dict[str, tuple[str, Any]]:
    """name -> (actor without the permission, the call)."""
    target = org.user("builder")

    async def list_members(conn: Any, tenant: Any, access: Any, _org: Any) -> object:
        return await service.list_members(conn, tenant, access)

    async def invite(conn: Any, tenant: Any, access: Any, _org: Any) -> object:
        return await service.invite_member(
            conn,
            tenant,
            access,
            email=f"x.{org.suffix}@example.invalid",
            display_name=None,
            role="viewer",
        )

    async def change(conn: Any, tenant: Any, access: Any, _org: Any) -> object:
        return await service.change_workspace_role(conn, tenant, access, target, "workspace_admin")

    async def remove(conn: Any, tenant: Any, access: Any, _org: Any) -> object:
        await service.remove_member(conn, tenant, access, target)
        return None

    async def org_role(conn: Any, tenant: Any, _access: Any, org_access: Any) -> object:
        return await service.change_org_role(conn, tenant, org_access, target, "org_owner")

    return {
        "list_members": ("member", list_members),  # a Member holds no members.view
        "invite_member": ("viewer", invite),
        "change_workspace_role": ("builder", change),
        "remove_member": ("viewer", remove),
        "change_org_role": ("org_admin", org_role),  # an Org Admin holds no org.roles.manage
    }


@pytest.mark.parametrize(
    "name",
    ["list_members", "invite_member", "change_workspace_role", "remove_member", "change_org_role"],
)
async def test_service_function_refuses_an_actor_without_the_permission(
    app_engine: AsyncEngine, make_org: MakeOrg, name: str
) -> None:
    org = await make_org()
    actor, call = _calls(org)[name]
    before = await _state(app_engine, org)

    with pytest.raises(PermissionDenied):
        await _run(app_engine, org, actor, call)

    assert await _state(app_engine, org) == before


async def test_the_same_calls_succeed_for_an_actor_who_holds_the_permission(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    """Guards the test above against refusing everything: an owner may make each call."""
    org = await make_org()
    for name, (_actor, call) in _calls(org).items():
        if name == "remove_member":
            continue  # the target is changed by the earlier calls; removal is tested elsewhere
        await _run(app_engine, org, "owner", call)


async def test_a_workspace_admin_without_an_org_role_cannot_take_their_own_management_right(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()
    me = org.user("ws_admin")
    before = await _state(app_engine, org)

    async def demote(conn: Any, tenant: Any, access: Any, _org: Any) -> object:
        return await service.change_workspace_role(conn, tenant, access, me, "viewer")

    async def remove(conn: Any, tenant: Any, access: Any, _org: Any) -> object:
        await service.remove_member(conn, tenant, access, me)
        return None

    async def keep(conn: Any, tenant: Any, access: Any, _org: Any) -> object:
        return await service.change_workspace_role(conn, tenant, access, me, "workspace_admin")

    with pytest.raises(PermissionDenied):
        await _run(app_engine, org, "ws_admin", demote)
    with pytest.raises(PermissionDenied):
        await _run(app_engine, org, "ws_admin", remove)
    assert await _state(app_engine, org) == before
    await _run(app_engine, org, "ws_admin", keep)  # staying Workspace Admin is a no-op


async def test_the_api_refuses_a_self_lockout_with_403_and_an_org_admin_may_step_down(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org(
        {
            "ws_admin": (None, {"x": "workspace_admin"}),
            "admin": ("org_admin", {"x": "workspace_admin"}),
        }
    )
    ws = org.workspace("x")

    async with role_client(app_engine, org) as client:
        locked_out = await client.put(
            f"/workspaces/{ws}/members/{org.user('ws_admin')}",
            headers=org.headers("ws_admin"),
            json={"role": "viewer"},
        )
        removed = await client.delete(
            f"/workspaces/{ws}/members/{org.user('ws_admin')}", headers=org.headers("ws_admin")
        )
        stepped_down = await client.put(
            f"/workspaces/{ws}/members/{org.user('admin')}",
            headers=org.headers("admin"),
            json={"role": "reviewer"},
        )

    assert (locked_out.status_code, locked_out.json()) == (403, {"detail": "forbidden"})
    assert (removed.status_code, removed.json()) == (403, {"detail": "forbidden"})
    assert stepped_down.status_code == 200  # an Org Admin keeps the management right


async def test_inviting_an_email_another_request_just_created_joins_that_user(
    app_engine: AsyncEngine, make_org: MakeOrg, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lookup misses (the other request had not committed), the insert hits the unique email;
    the invitation then joins the existing user instead of failing."""
    org = await make_org()
    outsider = org.people["outsider"]
    real = find_user_id
    misses = [True]

    async def lookup(conn: Any, org_id: uuid.UUID, email: str) -> uuid.UUID | None:
        if misses and email == outsider.email:
            misses.pop()
            return None
        return await real(conn, org_id, email)

    monkeypatch.setattr(service, "find_user_id", lookup)

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("owner"),
            json={"email": outsider.email, "role": "viewer"},
        )

    assert response.status_code == 201
    assert response.json()["user_id"] == str(outsider.user_id)
    users = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT count(*) FROM users WHERE org_id = :org AND email = :e",
        {"e": outsider.email},
    )
    assert users == [(1,)]


async def test_only_the_workspace_membership_conflict_is_reported_as_already_member(
    app_engine: AsyncEngine, make_org: MakeOrg, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await make_org()
    viewer = org.people["viewer"]
    real = find_member_row
    misses = [True]

    async def lookup(*args: Any) -> Any:
        if misses:
            misses.pop()
            return None  # the membership was created by a request that has just committed
        return await real(*args)

    monkeypatch.setattr(service, "find_member_row", lookup)

    async with role_client(app_engine, org) as client:
        response = await client.post(
            f"/workspaces/{org.workspace('x')}/members",
            headers=org.headers("owner"),
            json={"email": viewer.email, "role": "builder"},
        )

    assert (response.status_code, response.json()) == (409, {"detail": "already_member"})
