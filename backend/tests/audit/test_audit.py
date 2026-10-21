import uuid
from typing import Any

import pytest

from ei_ai.audit.events import (
    MEMBER_ORG_ROLE_CHANGED,
    MEMBER_WORKSPACE_ROLE_CHANGED,
    ORGANIZATION_CREATED,
    PLATFORM_OPERATOR,
    SYSTEM_ACTOR,
    USER_INVITED,
    USER_LOCKED_OUT,
    USER_PASSWORD_SET,
    USER_SET_PASSWORD_LINK_ISSUED,
    USER_SIGNED_IN,
    USER_SIGNED_OUT,
    WORKSPACE_CREATED,
    WORKSPACE_MEMBER_ADDED,
    record_event,
    record_role_change,
    user_actor,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.calls.append((str(statement), params))


def test_action_codes() -> None:
    assert PLATFORM_OPERATOR == "platform-operator"
    assert SYSTEM_ACTOR == "system"
    assert ORGANIZATION_CREATED == "organization.created"
    assert WORKSPACE_CREATED == "workspace.created"
    assert USER_INVITED == "user.invited"
    assert USER_SET_PASSWORD_LINK_ISSUED == "user.set_password_link_issued"
    assert USER_SIGNED_IN == "user.signed_in"
    assert USER_SIGNED_OUT == "user.signed_out"
    assert USER_LOCKED_OUT == "user.locked_out"
    assert USER_PASSWORD_SET == "user.password_set"
    assert WORKSPACE_MEMBER_ADDED == "workspace.member_added"
    assert MEMBER_WORKSPACE_ROLE_CHANGED == "member.workspace_role_changed"
    assert MEMBER_ORG_ROLE_CHANGED == "member.org_role_changed"


def test_user_actor_is_prefixed_user_id() -> None:
    user_id = uuid.uuid4()

    assert user_actor(user_id) == f"user:{user_id}"


async def test_record_event_writes_actor_and_action() -> None:
    conn = _FakeConnection()
    org_id, user_id, target_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    await record_event(
        conn,  # type: ignore[arg-type]
        org_id,
        user_actor(user_id),
        USER_SIGNED_IN,
        "user",
        target_id,
    )

    [(sql, params)] = conn.calls
    assert sql.startswith("INSERT INTO audit_events")
    assert params == {
        "org": org_id,
        "actor": f"user:{user_id}",
        "action": "user.signed_in",
        "target_type": "user",
        "target_id": target_id,
        "workspace_id": None,
        "old_value": None,
        "new_value": None,
    }


async def test_record_role_change_for_a_workspace_role() -> None:
    conn = _FakeConnection()
    org_id, actor_id, user_id, workspace_id = (uuid.uuid4() for _ in range(4))

    await record_role_change(
        conn,  # type: ignore[arg-type]
        org_id,
        user_actor(actor_id),
        user_id,
        workspace_id=workspace_id,
        old="viewer",
        new="builder",
    )

    [(sql, params)] = conn.calls
    assert sql.startswith("INSERT INTO audit_events")
    assert params == {
        "org": org_id,
        "actor": f"user:{actor_id}",
        "action": "member.workspace_role_changed",
        "target_type": "user",
        "target_id": user_id,
        "workspace_id": workspace_id,
        "old_value": "viewer",
        "new_value": "builder",
    }


async def test_record_role_change_for_an_org_role_has_no_workspace() -> None:
    conn = _FakeConnection()

    await record_role_change(
        conn,  # type: ignore[arg-type]
        uuid.uuid4(),
        PLATFORM_OPERATOR,
        uuid.uuid4(),
        workspace_id=None,
        old=None,
        new="org_admin",
    )

    [(_, params)] = conn.calls
    assert params["action"] == "member.org_role_changed"
    assert (params["workspace_id"], params["old_value"], params["new_value"]) == (
        None,
        None,
        "org_admin",
    )


@pytest.mark.parametrize("role", ["viewer", None])
async def test_record_role_change_refuses_a_no_op(role: str | None) -> None:
    conn = _FakeConnection()

    with pytest.raises(ValueError, match="different"):
        await record_role_change(
            conn,  # type: ignore[arg-type]
            uuid.uuid4(),
            PLATFORM_OPERATOR,
            uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            old=role,
            new=role,
        )

    assert conn.calls == []
