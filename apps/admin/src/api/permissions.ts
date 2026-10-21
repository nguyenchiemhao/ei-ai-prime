import type { WorkspaceInfo } from "./workspaces";

/** The permission codes the admin app checks (docs/architecture/rbac.md). The API is the control. */
export type Permission =
  | "workspace.access"
  | "dashboard.view"
  | "knowledge.manage"
  | "assistants.manage"
  | "playground.use"
  | "assistants.publish"
  | "connectors.manage"
  | "conversations.read"
  | "collections.access.manage"
  | "members.view"
  | "members.manage"
  | "org.settings.manage"
  | "org.roles.manage";

export function can(access: WorkspaceInfo, permission: Permission): boolean {
  return access.permissions.includes(permission);
}
