"""AC1-AC3: the reviewed permission matrix, its documentation and its fail-closed behaviour."""

import json
import os
import re
from pathlib import Path

import pytest

from ei_ai.provisioning.validation import ORG_ROLES, WORKSPACE_ROLES
from ei_ai.rbac.permissions import (
    ORG_GRANTS,
    PLATFORM_GRANTS,
    SENSITIVE,
    UI_MATRIX,
    UI_MATRIX_ROLES,
    WORKSPACE_GRANTS,
    Permission,
    permissions_for,
)
from ei_ai.rbac.roles import (
    ASSIGNABLE_WORKSPACE_ROLES,
    OrgRole,
    PlatformRole,
    WorkspaceRole,
)

REPO_ROOT = Path(os.environ.get("EI_AI_REPO_ROOT", Path(__file__).resolve().parents[3]))
RBAC_DOC = REPO_ROOT / "docs" / "architecture" / "rbac.md"
EN_MESSAGES = REPO_ROOT / "packages" / "i18n" / "messages" / "en.json"

P = Permission
W = WorkspaceRole
O = OrgRole  # noqa: E741

# The Members artboard (EA-85) as a literal grid: row -> Yes cells of Admin, Developer, Builder,
# Knowledge Editor, Reviewer, Viewer.
ARTBOARD = {
    P.KNOWLEDGE_MANAGE: (1, 0, 1, 1, 0, 0),
    P.ASSISTANTS_MANAGE: (1, 0, 1, 0, 0, 0),
    P.PLAYGROUND_USE: (1, 0, 1, 0, 0, 0),
    P.ASSISTANTS_PUBLISH: (1, 0, 1, 0, 0, 0),
    P.CONNECTORS_MANAGE: (1, 1, 0, 0, 0, 0),
    P.CONVERSATIONS_READ: (0, 0, 0, 0, 1, 0),
    P.COLLECTIONS_ACCESS_MANAGE: (1, 0, 0, 0, 0, 0),
    P.DASHBOARD_VIEW: (1, 1, 1, 1, 1, 1),
}


ALL_GRANTS: dict[str, frozenset[Permission]] = {
    **{role.value: granted for role, granted in WORKSPACE_GRANTS.items()},
    **{role.value: granted for role, granted in ORG_GRANTS.items()},
}


def _holders(permission: Permission) -> set[str]:
    return {code for code, granted in ALL_GRANTS.items() if permission in granted}


def test_role_codes_match_the_provisioning_validation_lists() -> None:
    assert tuple(role.value for role in OrgRole) == ORG_ROLES
    assert tuple(role.value for role in WorkspaceRole) == WORKSPACE_ROLES
    assert ASSIGNABLE_WORKSPACE_ROLES == tuple(WorkspaceRole)[:6]
    assert WorkspaceRole.MEMBER not in ASSIGNABLE_WORKSPACE_ROLES
    assert {role.value for role in PlatformRole} == {
        "platform_admin",
        "platform_support",
        "billing",
    }


def test_sensitive_permission_holders() -> None:
    assert SENSITIVE == {P.ASSISTANTS_PUBLISH, P.CONNECTORS_MANAGE, P.CONVERSATIONS_READ}
    assert _holders(P.CONVERSATIONS_READ) == {"reviewer"}
    assert _holders(P.CONNECTORS_MANAGE) == {
        "workspace_admin",
        "developer",
        "org_owner",
        "org_admin",
    }
    assert _holders(P.ASSISTANTS_PUBLISH) == {
        "workspace_admin",
        "builder",
        "org_owner",
        "org_admin",
    }
    assert _holders(P.COLLECTIONS_ACCESS_MANAGE) == {"workspace_admin", "org_owner", "org_admin"}


def test_org_roles_never_read_conversations() -> None:
    for role in OrgRole:
        assert P.CONVERSATIONS_READ not in permissions_for(role, None)
        assert P.CONVERSATIONS_READ not in permissions_for(role, WorkspaceRole.WORKSPACE_ADMIN)
    assert P.CONVERSATIONS_READ in permissions_for(OrgRole.ORG_ADMIN, WorkspaceRole.REVIEWER)


def test_only_the_org_owner_changes_org_roles() -> None:
    assert _holders(P.ORG_ROLES_MANAGE) == {"org_owner"}
    assert _holders(P.ORG_SETTINGS_MANAGE) == {"org_owner", "org_admin"}


def test_org_roles_act_as_workspace_admin_in_every_workspace() -> None:
    admin = WORKSPACE_GRANTS[WorkspaceRole.WORKSPACE_ADMIN]
    for role in OrgRole:
        assert admin <= ORG_GRANTS[role]
        assert permissions_for(role, None) >= admin


def test_ui_matrix_matches_artboard() -> None:
    assert UI_MATRIX_ROLES == ASSIGNABLE_WORKSPACE_ROLES
    assert [row.permission for row in UI_MATRIX] == list(ARTBOARD)
    for row in UI_MATRIX:
        cells = tuple(int(row.permission in WORKSPACE_GRANTS[role]) for role in UI_MATRIX_ROLES)
        assert cells == ARTBOARD[row.permission], row.permission


def test_platform_roles_hold_no_tenant_permission() -> None:
    for role, granted in PLATFORM_GRANTS.items():
        assert all(permission.scope == "platform" for permission in granted), role
        assert permissions_for(role.value, role.value) == frozenset()
    assert PLATFORM_GRANTS[PlatformRole.PLATFORM_ADMIN] == {P.PLATFORM_ORGANIZATIONS_LIST}
    assert not any(
        permission.scope == "platform"
        for granted in (*WORKSPACE_GRANTS.values(), *ORG_GRANTS.values())
        for permission in granted
    )


@pytest.mark.parametrize("code", ["", "Builder", "admin", "root", "owner", "platform_admin", "x y"])
def test_unknown_role_has_no_permission(code: str) -> None:
    assert permissions_for(code, None) == frozenset()
    assert permissions_for(None, code) == frozenset()
    assert permissions_for(code, code) == frozenset()
    assert permissions_for(None, None) == frozenset()


def test_org_owner_plus_reviewer_holds_every_tenant_permission() -> None:
    every_tenant = {p for p in Permission if p.scope != "platform"}

    assert permissions_for(OrgRole.ORG_OWNER, WorkspaceRole.REVIEWER) == every_tenant


def test_every_permission_has_a_scope() -> None:
    assert {p.scope for p in Permission} == {"workspace", "org", "platform"}


def _table(block: str) -> list[list[str]]:
    text = RBAC_DOC.read_text(encoding="utf-8")
    body = re.search(rf"<!-- {block}:start -->\n(.*?)<!-- {block}:end -->", text, re.DOTALL)
    assert body, f"{RBAC_DOC.name} has no {block} block"
    rows = [
        [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        for line in body.group(1).strip().splitlines()
    ]
    return [row for index, row in enumerate(rows) if index != 1]  # drop the |---| line


def _cell(granted: bool) -> str:
    return "Yes" if granted else "—"


def test_docs_tables_match_code() -> None:
    labels = json.loads(EN_MESSAGES.read_text(encoding="utf-8"))

    def label(key: str) -> str:
        node: object = labels
        for part in key.split("."):
            assert isinstance(node, dict)
            node = node[part]
        assert isinstance(node, str)
        return node

    matrix = _table("rbac-matrix")
    assert matrix[0] == [
        "Permission", "Code", "Admin", "Developer", "Builder",
        "Knowledge Editor", "Reviewer", "Viewer",
    ]  # fmt: skip
    assert matrix[1:] == [
        [label(row.label_key), row.permission.value]
        + [_cell(row.permission in WORKSPACE_GRANTS[role]) for role in UI_MATRIX_ROLES]
        for row in UI_MATRIX
    ]

    grants = _table("rbac-grants")
    role_order = [*WorkspaceRole, *OrgRole]
    assert grants[0] == ["Permission", "Scope", *(role.value for role in role_order)]
    assert grants[1:] == [
        [permission.value, permission.scope]
        + [_cell(permission in ALL_GRANTS[role.value]) for role in role_order]
        for permission in Permission
    ]
