"""One Workspace of the signed-in user (EA-22, EA-23 contract "API")."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ei_ai.api.errors import ErrorCode
from ei_ai.rbac.access import WorkspaceAccess
from ei_ai.rbac.declarations import requires
from ei_ai.rbac.permissions import Permission

router = APIRouter()


class WorkspaceInfo(BaseModel):
    id: uuid.UUID
    name: str
    role: str | None
    org_role: str | None
    permissions: list[str]


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceInfo,
    responses={
        401: {"model": ErrorCode, "description": "No live session (unauthenticated)"},
        422: {"model": ErrorCode, "description": "Malformed Workspace id (invalid_request)"},
        404: {
            "model": ErrorCode,
            "description": "Unknown, not visible to the caller or another Organization (not_found)",
        },
    },
    summary="A Workspace the signed-in user can see, with their roles and permissions",
)
async def get_workspace(
    access: Annotated[WorkspaceAccess, Depends(requires(Permission.WORKSPACE_ACCESS))],
) -> WorkspaceInfo:
    """Visibility is checked by the dependency; the answer is the caller's own roles and the
    permissions they add up to (the admin UI re-reads it on every area or Workspace change)."""
    return WorkspaceInfo(
        id=access.workspace_id,
        name=access.name,
        role=access.role,
        org_role=access.org_role,
        permissions=sorted(permission.value for permission in access.permissions),
    )
