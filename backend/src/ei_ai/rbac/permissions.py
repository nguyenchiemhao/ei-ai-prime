"""The reviewed permission matrix (D48): which role holds which permission.

Every API route declares exactly one permission (``ei_ai.rbac.declarations``) and CI fails when a
route does not, or when a declaration differs from the reviewed route table. Changing a grant
below is a security change: update ``docs/architecture/rbac.md`` (a test compares both) and the
Members & roles matrix of the admin app.

Two rules shape the matrix:

* An Org Owner or Org Admin holds the Workspace Admin permissions in every Workspace of the
  Organization, and never ``conversations.read`` (Admins who need it assign themselves Reviewer).
* The effective permissions of a user in a Workspace are the union of the grants of the user's
  Organization role and of the user's Workspace role. An unknown role code grants nothing.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ei_ai.rbac.roles import ASSIGNABLE_WORKSPACE_ROLES, OrgRole, PlatformRole, WorkspaceRole


class Permission(StrEnum):
    # Workspace scope
    WORKSPACE_ACCESS = "workspace.access"
    DASHBOARD_VIEW = "dashboard.view"
    KNOWLEDGE_MANAGE = "knowledge.manage"
    ASSISTANTS_MANAGE = "assistants.manage"
    PLAYGROUND_USE = "playground.use"
    ASSISTANTS_PUBLISH = "assistants.publish"
    CONNECTORS_MANAGE = "connectors.manage"
    CONVERSATIONS_READ = "conversations.read"
    COLLECTIONS_ACCESS_MANAGE = "collections.access.manage"
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"
    # Organization scope
    ORG_SETTINGS_MANAGE = "org.settings.manage"
    ORG_ROLES_MANAGE = "org.roles.manage"
    # Platform scope
    PLATFORM_ORGANIZATIONS_LIST = "platform.organizations.list"

    @property
    def scope(self) -> Literal["workspace", "org", "platform"]:
        return _SCOPES[self]


P = Permission

_SCOPES: dict[Permission, Literal["workspace", "org", "platform"]] = {
    **dict.fromkeys(
        (
            P.WORKSPACE_ACCESS,
            P.DASHBOARD_VIEW,
            P.KNOWLEDGE_MANAGE,
            P.ASSISTANTS_MANAGE,
            P.PLAYGROUND_USE,
            P.ASSISTANTS_PUBLISH,
            P.CONNECTORS_MANAGE,
            P.CONVERSATIONS_READ,
            P.COLLECTIONS_ACCESS_MANAGE,
            P.MEMBERS_VIEW,
            P.MEMBERS_MANAGE,
        ),
        "workspace",
    ),
    **dict.fromkeys((P.ORG_SETTINGS_MANAGE, P.ORG_ROLES_MANAGE), "org"),
    P.PLATFORM_ORGANIZATIONS_LIST: "platform",
}

# The three sensitive permissions (D48): kept in separate roles on purpose.
SENSITIVE: frozenset[Permission] = frozenset(
    {P.ASSISTANTS_PUBLISH, P.CONNECTORS_MANAGE, P.CONVERSATIONS_READ}
)

_WORKSPACE_ADMIN = frozenset(
    {
        P.WORKSPACE_ACCESS,
        P.DASHBOARD_VIEW,
        P.KNOWLEDGE_MANAGE,
        P.ASSISTANTS_MANAGE,
        P.PLAYGROUND_USE,
        P.ASSISTANTS_PUBLISH,
        P.CONNECTORS_MANAGE,
        P.COLLECTIONS_ACCESS_MANAGE,
        P.MEMBERS_VIEW,
        P.MEMBERS_MANAGE,
    }
)

WORKSPACE_GRANTS: dict[WorkspaceRole, frozenset[Permission]] = {
    WorkspaceRole.WORKSPACE_ADMIN: _WORKSPACE_ADMIN,
    WorkspaceRole.DEVELOPER: frozenset(
        {P.WORKSPACE_ACCESS, P.DASHBOARD_VIEW, P.CONNECTORS_MANAGE, P.MEMBERS_VIEW}
    ),
    WorkspaceRole.BUILDER: frozenset(
        {
            P.WORKSPACE_ACCESS,
            P.DASHBOARD_VIEW,
            P.KNOWLEDGE_MANAGE,
            P.ASSISTANTS_MANAGE,
            P.PLAYGROUND_USE,
            P.ASSISTANTS_PUBLISH,
            P.MEMBERS_VIEW,
        }
    ),
    WorkspaceRole.KNOWLEDGE_EDITOR: frozenset(
        {P.WORKSPACE_ACCESS, P.DASHBOARD_VIEW, P.KNOWLEDGE_MANAGE, P.MEMBERS_VIEW}
    ),
    WorkspaceRole.REVIEWER: frozenset(
        {P.WORKSPACE_ACCESS, P.DASHBOARD_VIEW, P.CONVERSATIONS_READ, P.MEMBERS_VIEW}
    ),
    WorkspaceRole.VIEWER: frozenset({P.WORKSPACE_ACCESS, P.DASHBOARD_VIEW, P.MEMBERS_VIEW}),
    WorkspaceRole.MEMBER: frozenset({P.WORKSPACE_ACCESS}),
}

ORG_GRANTS: dict[OrgRole, frozenset[Permission]] = {
    OrgRole.ORG_OWNER: _WORKSPACE_ADMIN | {P.ORG_SETTINGS_MANAGE, P.ORG_ROLES_MANAGE},
    OrgRole.ORG_ADMIN: _WORKSPACE_ADMIN | {P.ORG_SETTINGS_MANAGE},
}

# Platform roles act on the platform plane, never inside an Organization (D6). Platform Support
# and Billing hold nothing yet.
PLATFORM_GRANTS: dict[PlatformRole, frozenset[Permission]] = {
    PlatformRole.PLATFORM_ADMIN: frozenset({P.PLATFORM_ORGANIZATIONS_LIST}),
    PlatformRole.PLATFORM_SUPPORT: frozenset(),
    PlatformRole.BILLING: frozenset(),
}


_ORG_BY_CODE: dict[str, frozenset[Permission]] = {r.value: g for r, g in ORG_GRANTS.items()}
_WORKSPACE_BY_CODE: dict[str, frozenset[Permission]] = {
    r.value: g for r, g in WORKSPACE_GRANTS.items()
}


def permissions_for(org_role: str | None, workspace_role: str | None) -> frozenset[Permission]:
    """The permissions of a user with these role codes in one Workspace: the union of both grants.
    A code that is not a known role (or ``None``) grants nothing."""
    return _ORG_BY_CODE.get(org_role or "", frozenset()) | _WORKSPACE_BY_CODE.get(
        workspace_role or "", frozenset()
    )


@dataclass(frozen=True)
class MatrixRow:
    """One row of the Members & roles matrix: the i18n key of its label and its permission."""

    label_key: str
    permission: Permission


# The rows of "What each role can do", in the order of the Members artboard (EA-85).
UI_MATRIX: tuple[MatrixRow, ...] = (
    MatrixRow("admin.members.matrix.permission.knowledge", P.KNOWLEDGE_MANAGE),
    MatrixRow("admin.members.matrix.permission.assistants", P.ASSISTANTS_MANAGE),
    MatrixRow("admin.members.matrix.permission.playground", P.PLAYGROUND_USE),
    MatrixRow("admin.members.matrix.permission.publish", P.ASSISTANTS_PUBLISH),
    MatrixRow("admin.members.matrix.permission.connectors", P.CONNECTORS_MANAGE),
    MatrixRow("admin.members.matrix.permission.conversations", P.CONVERSATIONS_READ),
    MatrixRow("admin.members.matrix.permission.collectionAccess", P.COLLECTIONS_ACCESS_MANAGE),
    MatrixRow("admin.members.matrix.permission.dashboard", P.DASHBOARD_VIEW),
)

# The role columns of that matrix, in order ("Admin" is the Workspace Admin role).
UI_MATRIX_ROLES: tuple[WorkspaceRole, ...] = ASSIGNABLE_WORKSPACE_ROLES
