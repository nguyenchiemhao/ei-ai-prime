"""Members and roles: the service layer behind the Members & roles API (FND-06).

Every function takes the caller's access object and checks the permission itself (``ensure``),
so a caller that skipped the route dependency is still refused. Every table is filtered by the
caller's Organization (D46) and the actor of every audit event is the signed-in caller (D32).
Each role change and its audit event run in the caller's tenant transaction: they commit
together, or neither does. A call that changes nothing writes no event. Nothing here logs.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ei_ai.audit.events import USER_INVITED, record_event, record_role_change, user_actor
from ei_ai.db.constraints import violated_constraint
from ei_ai.members.emails import parse_email
from ei_ai.members.rows import (
    MemberRow,
    delete_workspace_member,
    find_member_row,
    find_user_id,
    insert_member,
    insert_workspace_member,
    list_member_rows,
    lock_owners_and_target,
    lock_workspace_role,
    update_org_role,
    update_workspace_role,
)
from ei_ai.rbac.access import OrgAccess, PermissionDenied, WorkspaceAccess, ensure
from ei_ai.rbac.permissions import Permission, permissions_for
from ei_ai.rbac.roles import ASSIGNABLE_WORKSPACE_ROLES, OrgRole
from ei_ai.tenancy.context import TenantContext

_ASSIGNABLE = frozenset(role.value for role in ASSIGNABLE_WORKSPACE_ROLES)
_USER_EMAIL_KEY = "users_org_id_email_key"
_WORKSPACE_MEMBER_KEY = "workspace_memberships_org_id_workspace_id_user_id_key"
_NAME_MAX = 200


class InvalidMemberInput(Exception):
    """The email, name or role is not acceptable (the API answers 422 ``invalid_request``)."""


class MemberNotFound(Exception):
    """The user is not a member here, or does not exist in this Organization (404)."""


class AlreadyMember(Exception):
    """The person already belongs to this Workspace (409 ``already_member``)."""


class LastOrgOwner(Exception):
    """The change would leave the Organization without an Org Owner (409 ``last_org_owner``)."""


def _check_role(role: str) -> None:
    if role not in _ASSIGNABLE:
        raise InvalidMemberInput


def _display_name(display_name: str | None, email: str) -> str:
    """The trimmed display name, or the local part of the email when none is given."""
    if display_name is None:
        return email.partition("@")[0]
    name = display_name.strip()
    if not 1 <= len(name) <= _NAME_MAX:
        raise InvalidMemberInput
    return name


def _refuse_self_lockout(
    tenant: TenantContext, access: WorkspaceAccess, user_id: uuid.UUID, new_role: str | None
) -> None:
    """Plan A8: a caller without an Organization role cannot take their own right to manage
    members away (the Workspace would be left to an Org Admin). Their other changes are fine."""
    if (
        user_id == tenant.user_id
        and access.org_role is None
        and Permission.MEMBERS_MANAGE not in permissions_for(None, new_role)
    ):
        raise PermissionDenied


async def list_members(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess
) -> list[MemberRow]:
    """The members of the caller's Workspace, in the order they joined."""
    ensure(access.permissions, Permission.MEMBERS_VIEW)
    return await list_member_rows(conn, tenant.org_id, access.workspace_id)


async def _member(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess, user_id: uuid.UUID
) -> MemberRow:
    row = await find_member_row(conn, tenant.org_id, access.workspace_id, user_id)
    if row is None:
        raise MemberNotFound
    return row


async def _create_user(
    conn: AsyncConnection,
    access: WorkspaceAccess,
    address: str,
    name: str,
    role: str,
    org_id: uuid.UUID,
) -> uuid.UUID | None:
    """The new user (with membership, Workspace role and token), or ``None`` when another request
    created the same email first. A savepoint keeps the outer transaction usable after that."""
    try:
        async with conn.begin_nested():
            user_id, _secret = await insert_member(
                conn, org_id, address, name, None, (access.workspace_id, role)
            )
    except IntegrityError as error:
        if violated_constraint(error) == _USER_EMAIL_KEY:
            return None
        raise
    return user_id


async def _join(
    conn: AsyncConnection, access: WorkspaceAccess, user_id: uuid.UUID, role: str, org_id: uuid.UUID
) -> None:
    """Give an existing user of the Organization a role here; ``AlreadyMember`` if they have one."""
    if await find_member_row(conn, org_id, access.workspace_id, user_id) is not None:
        raise AlreadyMember
    try:
        async with conn.begin_nested():
            await insert_workspace_member(conn, org_id, access.workspace_id, user_id, role)
    except IntegrityError as error:
        if violated_constraint(error) == _WORKSPACE_MEMBER_KEY:
            raise AlreadyMember from None
        raise


async def invite_member(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    *,
    email: str,
    display_name: str | None,
    role: str,
) -> MemberRow:
    """Add a person to the Workspace with ``role``. An existing user of the Organization joins
    (their name is kept); a new person gets a user, a membership and an unused set-password
    token, none of which is returned or printed."""
    ensure(access.permissions, Permission.MEMBERS_MANAGE)
    _check_role(role)
    address = parse_email(email)
    if address is None:
        raise InvalidMemberInput
    name = _display_name(display_name, address)
    org_id, actor = tenant.org_id, user_actor(tenant.user_id)
    user_id = await find_user_id(conn, org_id, address)
    if user_id is None:
        user_id = await _create_user(conn, access, address, name, role, org_id)
        if user_id is not None:
            await record_event(conn, org_id, actor, USER_INVITED, "user", user_id)
        else:
            # Another request created the same email a moment ago: join that user instead.
            user_id = await find_user_id(conn, org_id, address)
            assert user_id is not None, "the conflicting user is committed"
            await _join(conn, access, user_id, role, org_id)
    else:
        await _join(conn, access, user_id, role, org_id)
    await record_role_change(
        conn, org_id, actor, user_id, workspace_id=access.workspace_id, old=None, new=role
    )
    return await _member(conn, tenant, access, user_id)


async def change_workspace_role(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: WorkspaceAccess,
    user_id: uuid.UUID,
    role: str,
) -> MemberRow:
    """Set the Workspace role of a member. The same role is a no-op (no event)."""
    ensure(access.permissions, Permission.MEMBERS_MANAGE)
    _check_role(role)
    _refuse_self_lockout(tenant, access, user_id, role)
    org_id = tenant.org_id
    current = await lock_workspace_role(conn, org_id, access.workspace_id, user_id)
    if current is None:
        raise MemberNotFound
    if current != role:
        await update_workspace_role(conn, org_id, access.workspace_id, user_id, role)
        await record_role_change(
            conn,
            org_id,
            user_actor(tenant.user_id),
            user_id,
            workspace_id=access.workspace_id,
            old=current,
            new=role,
        )
    return await _member(conn, tenant, access, user_id)


async def remove_member(
    conn: AsyncConnection, tenant: TenantContext, access: WorkspaceAccess, user_id: uuid.UUID
) -> None:
    """Revoke a person's Workspace role. Their Organization role and account stay."""
    ensure(access.permissions, Permission.MEMBERS_MANAGE)
    _refuse_self_lockout(tenant, access, user_id, None)
    org_id = tenant.org_id
    current = await lock_workspace_role(conn, org_id, access.workspace_id, user_id)
    if current is None:
        raise MemberNotFound
    await delete_workspace_member(conn, org_id, access.workspace_id, user_id)
    await record_role_change(
        conn,
        org_id,
        user_actor(tenant.user_id),
        user_id,
        workspace_id=access.workspace_id,
        old=current,
        new=None,
    )


async def change_org_role(
    conn: AsyncConnection,
    tenant: TenantContext,
    access: OrgAccess,
    user_id: uuid.UUID,
    org_role: str | None,
) -> str | None:
    """Set the Organization role of a user (``None`` removes it). Only an Org Owner may; the
    last Org Owner cannot be demoted. Returns the role now held."""
    ensure(access.permissions, Permission.ORG_ROLES_MANAGE)
    if org_role is not None and org_role not in OrgRole:
        raise InvalidMemberInput
    org_id = tenant.org_id
    rows = await lock_owners_and_target(conn, org_id, user_id)
    target = next((row for row in rows if row.user_id == user_id), None)
    if target is None:
        raise MemberNotFound
    current = target.org_role
    if current == OrgRole.ORG_OWNER and org_role != OrgRole.ORG_OWNER:
        owners = sum(1 for row in rows if row.org_role == OrgRole.ORG_OWNER)
        if owners <= 1:
            raise LastOrgOwner
    if current != org_role:
        await update_org_role(conn, org_id, user_id, org_role)
        await record_role_change(
            conn,
            org_id,
            user_actor(tenant.user_id),
            user_id,
            workspace_id=None,
            old=current,
            new=org_role,
        )
    return org_role
