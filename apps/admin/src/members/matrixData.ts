import type { Permission } from "../api/permissions";
import { ASSIGNABLE_ROLES, type AssignableRole } from "../api/members";

/** One row of "What each role can do". `docs/architecture/rbac.md` holds the same grid. */
export interface MatrixRow {
  permission: Permission;
  /** i18n key of the row label. */
  labelKey: string;
  sensitive: boolean;
  /** Admin, Developer, Builder, Knowledge Editor, Reviewer, Viewer (`MATRIX_ROLES` order). */
  grants: readonly boolean[];
}

/** The columns of the matrix are the assignable roles, in the order of the role select. */
export const MATRIX_ROLES: readonly AssignableRole[] = ASSIGNABLE_ROLES;

const KEY = "admin.members.matrix.permission";

function row(
  permission: Permission,
  labelKey: string,
  sensitive: boolean,
  yes: readonly AssignableRole[],
): MatrixRow {
  return {
    permission,
    labelKey: `${KEY}.${labelKey}`,
    sensitive,
    grants: MATRIX_ROLES.map((role) => yes.includes(role)),
  };
}

/** The Members artboard matrix (EA-85) in artboard order; sensitive rows are highlighted. */
export const ROLE_MATRIX: readonly MatrixRow[] = [
  row("knowledge.manage", "knowledge", false, ["workspace_admin", "builder", "knowledge_editor"]),
  row("assistants.manage", "assistants", false, ["workspace_admin", "builder"]),
  row("playground.use", "playground", false, ["workspace_admin", "builder"]),
  row("assistants.publish", "publish", true, ["workspace_admin", "builder"]),
  row("connectors.manage", "connectors", true, ["workspace_admin", "developer"]),
  row("conversations.read", "conversations", true, ["reviewer"]),
  row("collections.access.manage", "collectionAccess", false, ["workspace_admin"]),
  row("dashboard.view", "dashboard", false, MATRIX_ROLES),
];
