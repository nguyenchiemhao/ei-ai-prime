"""Writing audit events of the platform plane (actor, action, target; no free text, D52)."""

import uuid
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

PLATFORM_OPERATOR = "platform-operator"

ORGANIZATION_CREATED = "organization.created"
WORKSPACE_CREATED = "workspace.created"
USER_INVITED = "user.invited"
USER_SET_PASSWORD_LINK_ISSUED = "user.set_password_link_issued"

TargetType = Literal["organization", "workspace", "user"]


async def record_platform_event(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    action: str,
    target_type: TargetType,
    target_id: uuid.UUID,
) -> None:
    """Insert one event whose actor is always the Platform Operator.

    Runs inside the caller's tenant transaction, so the event commits or rolls back with the
    action it records. There is no actor parameter: callers cannot choose who acted.
    """
    await conn.execute(
        text(
            "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
            " VALUES (:org, :actor, :action, :target_type, :target_id)"
        ),
        {
            "org": org_id,
            "actor": PLATFORM_OPERATOR,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
        },
    )
