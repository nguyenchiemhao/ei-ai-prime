"""Members & roles API (EA-23, contract "API").

Identity and Organization come from the verified session only (D32); request bodies carry a
role code and, for an invitation, an email and an optional name, nothing else (extra fields are
refused). Errors are codes only and never echo the input. Nothing here logs: an email or a name
must not reach a log (D52).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from ei_ai.api.deps import TenantSession
from ei_ai.api.errors import ErrorCode
from ei_ai.members import service
from ei_ai.members.rows import MemberRow
from ei_ai.rbac.access import OrgAccess, WorkspaceAccess
from ei_ai.rbac.declarations import requires, requires_org
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import TenantContext, require_tenant

router = APIRouter()

NOT_FOUND = "not_found"
ALREADY_MEMBER = "already_member"
LAST_ORG_OWNER = "last_org_owner"
INVALID_REQUEST = "invalid_request"

AssignableRole = Literal[
    "workspace_admin", "developer", "builder", "knowledge_editor", "reviewer", "viewer"
]


class MemberItem(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str
    org_role: str | None
    last_active_at: datetime | None


class MemberList(BaseModel):
    members: list[MemberItem]


class InviteRequest(BaseModel):
    """Only these fields: an ``org_role``, a ``user_id`` or any other field is a 422."""

    model_config = ConfigDict(strict=True, extra="forbid")

    email: str
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: AssignableRole


class WorkspaceRoleRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    role: AssignableRole


class OrgRoleRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    org_role: Literal["org_owner", "org_admin"] | None


class OrgRoleChanged(BaseModel):
    user_id: uuid.UUID
    org_role: str | None


def _item(row: MemberRow) -> MemberItem:
    return MemberItem(
        user_id=row.user_id,
        display_name=row.display_name,
        email=row.email,
        role=row.role,
        org_role=row.org_role,
        last_active_at=row.last_active_at,
    )


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


_UNAUTHENTICATED = {"model": ErrorCode, "description": "No live session (unauthenticated)"}
_FORBIDDEN = {"model": ErrorCode, "description": "The role lacks the permission (forbidden)"}
_NOT_FOUND = {
    "model": ErrorCode,
    "description": "Unknown or invisible Workspace, or the user is not a member here (not_found)",
}
_INVALID = {"model": ErrorCode, "description": "Malformed request (invalid_request)"}

ViewAccess = Annotated[WorkspaceAccess, Depends(requires(Permission.MEMBERS_VIEW))]
ManageAccess = Annotated[WorkspaceAccess, Depends(requires(Permission.MEMBERS_MANAGE))]
Tenant = Annotated[TenantContext, Depends(require_tenant)]


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=MemberList,
    responses={401: _UNAUTHENTICATED, 403: _FORBIDDEN, 404: _NOT_FOUND, 422: _INVALID},
    summary="The members of a Workspace and their roles",
)
async def list_members(tenant: Tenant, access: ViewAccess, session: TenantSession) -> MemberList:
    rows = await service.list_members(await session.connection(), tenant, access)
    return MemberList(members=[_item(row) for row in rows])


@router.post(
    "/workspaces/{workspace_id}/members",
    status_code=201,
    response_model=MemberItem,
    responses={
        401: _UNAUTHENTICATED,
        403: _FORBIDDEN,
        404: _NOT_FOUND,
        409: {"model": ErrorCode, "description": "Already a member of this Workspace"},
        422: _INVALID,
    },
    summary="Invite a person to a Workspace with a role",
)
async def invite_member(
    body: InviteRequest, tenant: Tenant, access: ManageAccess, session: TenantSession
) -> MemberItem:
    """Creates the user (with an unused set-password token) when the email is new to the
    Organization; the token is not returned. The role change is audited."""
    try:
        row = await service.invite_member(
            await session.connection(),
            tenant,
            access,
            email=body.email,
            display_name=body.display_name,
            role=body.role,
        )
    except service.InvalidMemberInput:
        raise _error(422, INVALID_REQUEST) from None
    except service.AlreadyMember:
        raise _error(409, ALREADY_MEMBER) from None
    return _item(row)


@router.put(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=MemberItem,
    responses={
        401: _UNAUTHENTICATED,
        403: _FORBIDDEN,
        404: _NOT_FOUND,
        422: _INVALID,
    },
    summary="Change a member's Workspace role",
)
async def change_workspace_role(
    user_id: uuid.UUID,
    body: WorkspaceRoleRequest,
    tenant: Tenant,
    access: ManageAccess,
    session: TenantSession,
) -> MemberItem:
    try:
        row = await service.change_workspace_role(
            await session.connection(), tenant, access, user_id, body.role
        )
    except service.MemberNotFound:
        raise _error(404, NOT_FOUND) from None
    except service.InvalidMemberInput:
        raise _error(422, INVALID_REQUEST) from None
    return _item(row)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=204,
    response_class=Response,
    responses={401: _UNAUTHENTICATED, 403: _FORBIDDEN, 404: _NOT_FOUND, 422: _INVALID},
    summary="Revoke a member's Workspace role",
)
async def remove_member(
    user_id: uuid.UUID, tenant: Tenant, access: ManageAccess, session: TenantSession
) -> Response:
    try:
        await service.remove_member(await session.connection(), tenant, access, user_id)
    except service.MemberNotFound:
        raise _error(404, NOT_FOUND) from None
    return Response(status_code=204)


@router.put(
    "/organization/members/{user_id}/org-role",
    response_model=OrgRoleChanged,
    responses={
        401: _UNAUTHENTICATED,
        403: _FORBIDDEN,
        404: {"model": ErrorCode, "description": "Unknown user in this Organization (not_found)"},
        409: {"model": ErrorCode, "description": "The last Org Owner cannot be demoted"},
        422: _INVALID,
    },
    summary="Change a user's Organization role (Org Owner only)",
)
async def change_org_role(
    user_id: uuid.UUID,
    body: OrgRoleRequest,
    tenant: Tenant,
    access: Annotated[OrgAccess, Depends(requires_org(Permission.ORG_ROLES_MANAGE))],
    session: TenantSession,
) -> OrgRoleChanged:
    try:
        org_role = await service.change_org_role(
            await session.connection(), tenant, access, user_id, body.org_role
        )
    except service.MemberNotFound:
        raise _error(404, NOT_FOUND) from None
    except service.LastOrgOwner:
        raise _error(409, LAST_ORG_OWNER) from None
    except service.InvalidMemberInput:
        raise _error(422, INVALID_REQUEST) from None
    return OrgRoleChanged(user_id=user_id, org_role=org_role)
