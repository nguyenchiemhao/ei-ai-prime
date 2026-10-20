"""One Workspace of the signed-in user (EA-22, contract "API")."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ei_ai.api.errors import ErrorCode
from ei_ai.workspaces.access import require_workspace_member
from ei_ai.workspaces.memberships import WorkspaceRef

router = APIRouter()


class WorkspaceInfo(BaseModel):
    id: uuid.UUID
    name: str
    role: str


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceInfo,
    responses={
        401: {"model": ErrorCode, "description": "No live session (unauthenticated)"},
        422: {"model": ErrorCode, "description": "Malformed Workspace id (invalid_request)"},
        404: {
            "model": ErrorCode,
            "description": "Unknown, not a member or another Organization (not_found)",
        },
    },
    summary="A Workspace the signed-in user belongs to",
)
async def get_workspace(
    workspace: Annotated[WorkspaceRef, Depends(require_workspace_member)],
) -> WorkspaceInfo:
    """Membership is checked by the dependency; the answer is the caller's own role."""
    return WorkspaceInfo(id=workspace.id, name=workspace.name, role=workspace.role)
