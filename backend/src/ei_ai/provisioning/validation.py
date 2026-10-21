"""Input validation of the provisioning commands: pure functions, no database access.

Every failure raises ``ProvisioningError`` with a message that is safe to print as is.
"""

import uuid
from collections.abc import Sequence

from ei_ai.members.emails import parse_email

# Must match the CHECK constraints of migration 0001.
ORG_ROLES = ("org_owner", "org_admin")
WORKSPACE_ROLES = (
    "workspace_admin",
    "developer",
    "builder",
    "knowledge_editor",
    "reviewer",
    "viewer",
    "member",
)

_NAME_MAX = 200


class ProvisioningError(Exception):
    """A user-safe validation, conflict or not-found error of a provisioning command."""


def _trimmed(raw: str, message: str) -> str:
    """The stripped value; raises with ``message`` unless it has 1-200 characters."""
    value = raw.strip()
    if not 1 <= len(value) <= _NAME_MAX:
        raise ProvisioningError(message)
    return value


def normalise_org_name(raw: str) -> str:
    """Trimmed Organization name (E1 when out of range)."""
    return _trimmed(raw, "Organization name must be 1-200 characters")


def normalise_workspace_name(raw: str) -> str:
    """Trimmed Workspace name (E5 when out of range)."""
    return _trimmed(raw, "Workspace name must be 1-200 characters")


def normalise_display_name(raw: str) -> str:
    """Trimmed display name (E4 when out of range)."""
    return _trimmed(raw, "display name must be 1-200 characters")


def normalise_email(raw: str) -> str:
    """The trimmed, lowercased email; raises when it is not a plain address."""
    value = parse_email(raw)
    if value is None:
        raise ProvisioningError("invalid email address")
    return value


def parse_uuid(raw: str, message: str) -> uuid.UUID:
    """The UUID in ``raw``; raises ``ProvisioningError(message)`` when it is not one."""
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        raise ProvisioningError(message) from None


def split_roles(roles: Sequence[str]) -> tuple[str | None, str | None]:
    """(Organization role, Workspace role) of the role codes; at most one of each kind."""
    for role in roles:
        if role not in ORG_ROLES and role not in WORKSPACE_ROLES:
            valid = ", ".join((*ORG_ROLES, *WORKSPACE_ROLES))
            raise ProvisioningError(f'unknown role "{role}"; valid roles: {valid}')
    org_roles = [role for role in roles if role in ORG_ROLES]
    workspace_roles = [role for role in roles if role in WORKSPACE_ROLES]
    if len(org_roles) > 1 or len(workspace_roles) > 1:
        raise ProvisioningError("give at most one Organization role and one Workspace role")
    return (org_roles[0] if org_roles else None, workspace_roles[0] if workspace_roles else None)
