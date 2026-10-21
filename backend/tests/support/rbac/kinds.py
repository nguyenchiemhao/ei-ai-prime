"""The ten kinds of caller of the generated role x endpoint test, and the Organization they live in.

``W`` is the Workspace under test. Seven kinds hold one Workspace role in ``W``; ``org_owner`` and
``org_admin`` hold an Organization role and no membership in ``W``; ``outsider`` holds nothing.
``target`` (a Viewer in ``W``) is the user that routes with a ``{user_id}`` act on.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.rbac.permissions import Permission, permissions_for
from ei_ai.rbac.roles import WorkspaceRole
from support.rbac.orgs import PersonSpec, RoleOrg, create_role_org

WORKSPACE = "w"


@dataclass(frozen=True)
class Kind:
    name: str
    org_role: str | None
    workspace_role: str | None

    def holds(self, permission: Permission) -> bool:
        """Whether the matrix grants ``permission`` to this kind (in ``W`` or Organization-wide)."""
        return permission in permissions_for(self.org_role, self.workspace_role)

    @property
    def sees_workspace(self) -> bool:
        return self.org_role is not None or self.workspace_role is not None


KINDS: tuple[Kind, ...] = (
    *(Kind(role.value, None, role.value) for role in WorkspaceRole),
    Kind("org_owner", "org_owner", None),
    Kind("org_admin", "org_admin", None),
    Kind("outsider", None, None),
)

TARGET = "target"


def people() -> dict[str, PersonSpec]:
    specs: dict[str, PersonSpec] = {
        kind.name: (kind.org_role, {WORKSPACE: kind.workspace_role} if kind.workspace_role else {})
        for kind in KINDS
    }
    specs[TARGET] = (None, {WORKSPACE: WorkspaceRole.VIEWER.value})
    return specs


async def create_kinds_org(engine: AsyncEngine) -> RoleOrg:
    """A fresh Organization with Workspace ``W``, one user per kind and the ``target``."""
    return await create_role_org(engine, people(), (WORKSPACE,))
