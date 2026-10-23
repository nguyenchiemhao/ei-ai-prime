"""Who is asking (D32). The only source of a user is the verified tenant context.

Group membership is not stored yet (EA-89), so ``session_principal`` has no groups. Only the
operator simulator sets groups, and it marks the principal ``simulated``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ei_ai.knowledge.errors import InvalidGroup
from ei_ai.knowledge.groups import normalise_group
from ei_ai.tenancy.context import TenantContext

MAX_PRINCIPAL_GROUPS = 100


@dataclass(frozen=True)
class AnonymousPrincipal:
    simulated: bool = False


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: UUID | None
    groups: tuple[str, ...] = ()
    simulated: bool = False


RetrievalPrincipal = AnonymousPrincipal | AuthenticatedPrincipal


def session_principal(tenant: TenantContext) -> AuthenticatedPrincipal:
    """The signed-in user of a verified request; no groups until EA-89."""
    return AuthenticatedPrincipal(user_id=tenant.user_id, groups=(), simulated=False)


def simulated_principal(
    kind: Literal["anonymous", "authenticated"], groups: Sequence[str] = ()
) -> RetrievalPrincipal:
    """A principal made up by an operator tool. Groups are normalised, de-duplicated, sorted;
    ``InvalidGroup`` for a bad group or more than 100; an anonymous principal has none."""
    unique = sorted({normalise_group(group) for group in groups})
    if len(unique) > MAX_PRINCIPAL_GROUPS:
        raise InvalidGroup
    if kind == "anonymous":
        if unique:
            raise ValueError("an anonymous principal has no groups")
        return AnonymousPrincipal(simulated=True)
    return AuthenticatedPrincipal(user_id=None, groups=tuple(unique), simulated=True)
