"""Writing audit events (actor, action, target; no free text, D52)."""

import uuid
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

PLATFORM_OPERATOR = "platform-operator"
SYSTEM_ACTOR = "system"

ORGANIZATION_CREATED = "organization.created"
WORKSPACE_CREATED = "workspace.created"
USER_INVITED = "user.invited"
USER_SET_PASSWORD_LINK_ISSUED = "user.set_password_link_issued"
USER_SIGNED_IN = "user.signed_in"
USER_SIGNED_OUT = "user.signed_out"
USER_LOCKED_OUT = "user.locked_out"
USER_PASSWORD_SET = "user.password_set"
WORKSPACE_MEMBER_ADDED = "workspace.member_added"

TargetType = Literal["organization", "workspace", "user"]


def user_actor(user_id: uuid.UUID) -> str:
    """The actor string of an action taken by a signed-in or signing-in user."""
    return f"user:{user_id}"


async def record_event(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    actor: str,
    action: str,
    target_type: TargetType,
    target_id: uuid.UUID,
) -> None:
    """Insert one event for ``actor`` (``PLATFORM_OPERATOR``, ``SYSTEM_ACTOR`` or ``user_actor``).

    Runs inside the caller's tenant transaction, so the event commits or rolls back with the
    action it records.
    """
    await conn.execute(
        text(
            "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
            " VALUES (:org, :actor, :action, :target_type, :target_id)"
        ),
        {
            "org": org_id,
            "actor": actor,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
        },
    )
