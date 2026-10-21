"""Test-only routes that carry the sensitive permissions (R1).

The endpoints behind the three sensitive permissions and the collection access rule do not exist
yet (their tickets are blocked by FND-06). These probes declare the same permissions through the
same dependency, so the generated role x endpoint test proves who may reach them today, and the
same dependency protects the real routes when they land. Never included in the production app.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from ei_ai.rbac.access import WorkspaceAccess
from ei_ai.rbac.declarations import requires
from ei_ai.rbac.permissions import Permission

PREFIX = "/rbac-probe/workspaces/{workspace_id}"

router = APIRouter(prefix=PREFIX)

ReadConversations = Annotated[WorkspaceAccess, Depends(requires(Permission.CONVERSATIONS_READ))]
ManageConnectors = Annotated[WorkspaceAccess, Depends(requires(Permission.CONNECTORS_MANAGE))]
Publish = Annotated[WorkspaceAccess, Depends(requires(Permission.ASSISTANTS_PUBLISH))]
CollectionAccess = Annotated[
    WorkspaceAccess, Depends(requires(Permission.COLLECTIONS_ACCESS_MANAGE))
]


@router.get("/conversations", status_code=204, response_class=Response)
async def read_conversations(access: ReadConversations) -> Response:
    return Response(status_code=204)


@router.get("/connector-secrets", status_code=204, response_class=Response)
async def read_connector_secrets(access: ManageConnectors) -> Response:
    return Response(status_code=204)


@router.put("/connector-secrets", status_code=204, response_class=Response)
async def write_connector_secrets(access: ManageConnectors) -> Response:
    return Response(status_code=204)


@router.put("/signing-keys", status_code=204, response_class=Response)
async def write_signing_keys(access: ManageConnectors) -> Response:
    return Response(status_code=204)


@router.post("/publish", status_code=204, response_class=Response)
async def publish_assistant(access: Publish) -> Response:
    return Response(status_code=204)


@router.put("/collection-access", status_code=204, response_class=Response)
async def change_collection_access(access: CollectionAccess) -> Response:
    return Response(status_code=204)
