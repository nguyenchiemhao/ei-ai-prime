"""The role codes of the three tiers (D48). They match the CHECK constraints of migration 0001."""

from enum import StrEnum


class PlatformRole(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    PLATFORM_SUPPORT = "platform_support"
    BILLING = "billing"


class OrgRole(StrEnum):
    ORG_OWNER = "org_owner"
    ORG_ADMIN = "org_admin"


class WorkspaceRole(StrEnum):
    WORKSPACE_ADMIN = "workspace_admin"
    DEVELOPER = "developer"
    BUILDER = "builder"
    KNOWLEDGE_EDITOR = "knowledge_editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    MEMBER = "member"


# The roles the Members & roles screen and API may assign. ``member`` exists in the database and
# is only shown (EA-89 adds it to the screen).
ASSIGNABLE_WORKSPACE_ROLES: tuple[WorkspaceRole, ...] = (
    WorkspaceRole.WORKSPACE_ADMIN,
    WorkspaceRole.DEVELOPER,
    WorkspaceRole.BUILDER,
    WorkspaceRole.KNOWLEDGE_EDITOR,
    WorkspaceRole.REVIEWER,
    WorkspaceRole.VIEWER,
)
