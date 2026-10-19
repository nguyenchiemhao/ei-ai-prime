import inspect
import uuid
from typing import Any

from ei_ai.audit.events import (
    ORGANIZATION_CREATED,
    PLATFORM_OPERATOR,
    USER_INVITED,
    USER_SET_PASSWORD_LINK_ISSUED,
    WORKSPACE_CREATED,
    record_platform_event,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.calls.append((str(statement), params))


def test_action_codes() -> None:
    assert PLATFORM_OPERATOR == "platform-operator"
    assert ORGANIZATION_CREATED == "organization.created"
    assert WORKSPACE_CREATED == "workspace.created"
    assert USER_INVITED == "user.invited"
    assert USER_SET_PASSWORD_LINK_ISSUED == "user.set_password_link_issued"


async def test_actor_is_fixed_platform_operator() -> None:
    conn = _FakeConnection()
    org_id, target_id = uuid.uuid4(), uuid.uuid4()

    await record_platform_event(conn, org_id, USER_INVITED, "user", target_id)  # type: ignore[arg-type]

    [(sql, params)] = conn.calls
    assert sql.startswith("INSERT INTO audit_events")
    assert params == {
        "org": org_id,
        "actor": "platform-operator",
        "action": "user.invited",
        "target_type": "user",
        "target_id": target_id,
    }


def test_callers_cannot_choose_the_actor() -> None:
    parameters = inspect.signature(record_platform_event).parameters

    assert list(parameters) == ["conn", "org_id", "action", "target_type", "target_id"]
