"""EA-36: who is asking. Groups never come from the session until EA-89; only the simulator
(an operator tool) sets them."""

import inspect
import uuid

import pytest

from ei_ai.knowledge.errors import InvalidGroup
from ei_ai.knowledge.retrieval.principal import (
    MAX_PRINCIPAL_GROUPS,
    AnonymousPrincipal,
    AuthenticatedPrincipal,
    session_principal,
    simulated_principal,
)
from ei_ai.tenancy.context import TenantContext


def test_session_principal_takes_no_groups() -> None:
    assert set(inspect.signature(session_principal).parameters) == {"tenant"}
    tenant = TenantContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())

    principal = session_principal(tenant)

    assert principal == AuthenticatedPrincipal(user_id=tenant.user_id, groups=(), simulated=False)
    assert principal.groups == ()
    assert principal.simulated is False


def test_simulated_groups_are_normalised() -> None:
    principal = simulated_principal("authenticated", [" Managers", "managers", "HR"])

    assert principal == AuthenticatedPrincipal(
        user_id=None, groups=("hr", "managers"), simulated=True
    )


def test_simulated_anonymous_is_marked_simulated() -> None:
    assert simulated_principal("anonymous") == AnonymousPrincipal(simulated=True)


@pytest.mark.parametrize(
    "groups",
    [["a,b"], [""], [f"g{i}" for i in range(MAX_PRINCIPAL_GROUPS + 1)]],
    ids=["comma", "empty", "too-many"],
)
def test_invalid_or_too_many_groups_raise(groups: list[str]) -> None:
    with pytest.raises(InvalidGroup):
        simulated_principal("authenticated", groups)


def test_the_group_cap_is_100_and_100_is_allowed() -> None:
    assert MAX_PRINCIPAL_GROUPS == 100
    principal = simulated_principal("authenticated", [f"g{i}" for i in range(100)])
    assert isinstance(principal, AuthenticatedPrincipal)
    assert len(principal.groups) == 100


def test_anonymous_cannot_have_groups() -> None:
    with pytest.raises(ValueError):
        simulated_principal("anonymous", ["hr"])
