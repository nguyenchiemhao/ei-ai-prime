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
MEMBER_WORKSPACE_ROLE_CHANGED = "member.workspace_role_changed"
MEMBER_ORG_ROLE_CHANGED = "member.org_role_changed"
MODEL_CATALOG_ENTRY_ADDED = "model.catalog_entry_added"
MODEL_CLOUD_CALL_BLOCKED = "model.cloud_call_blocked"

TargetType = Literal["organization", "workspace", "user", "model"]


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
    *,
    workspace_id: uuid.UUID | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    """Insert one event for ``actor`` (``PLATFORM_OPERATOR``, ``SYSTEM_ACTOR`` or ``user_actor``).

    ``workspace_id``, ``old_value`` and ``new_value`` are for role changes (a role code or ``None``
    for no role). Runs inside the caller's tenant transaction, so the event commits or rolls back
    with the action it records.
    """
    await conn.execute(
        text(
            "INSERT INTO audit_events"
            " (org_id, actor, action, target_type, target_id, workspace_id, old_value, new_value)"
            " VALUES (:org, :actor, :action, :target_type, :target_id, :workspace_id,"
            " :old_value, :new_value)"
        ),
        {
            "org": org_id,
            "actor": actor,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "workspace_id": workspace_id,
            "old_value": old_value,
            "new_value": new_value,
        },
    )


async def record_role_change(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    actor: str,
    user_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None,
    old: str | None,
    new: str | None,
) -> None:
    """Audit that the role of ``user_id`` changed from ``old`` to ``new`` (``None`` = no role):
    a Workspace role when ``workspace_id`` is given, else the Organization role. A change from a
    value to itself is a programming error: callers record only real changes."""
    if old == new:
        raise ValueError("a role change needs a different old and new role")
    await record_event(
        conn,
        org_id,
        actor,
        MEMBER_ORG_ROLE_CHANGED if workspace_id is None else MEMBER_WORKSPACE_ROLE_CHANGED,
        "user",
        user_id,
        workspace_id=workspace_id,
        old_value=old,
        new_value=new,
    )
