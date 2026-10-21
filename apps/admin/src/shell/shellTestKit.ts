import { json, SESSION, WS } from "../test/renderApp";

export const WS_B = "22222222-2222-4222-8222-222222222222";

// The grants of docs/architecture/rbac.md, as the API reports them in `permissions` (test data).
const WORKSPACE_ADMIN = [
  "assistants.manage",
  "assistants.publish",
  "collections.access.manage",
  "connectors.manage",
  "dashboard.view",
  "knowledge.manage",
  "members.manage",
  "members.view",
  "playground.use",
  "workspace.access",
];
const ROLE_PERMISSIONS: Record<string, string[]> = {
  workspace_admin: WORKSPACE_ADMIN,
  developer: ["connectors.manage", "dashboard.view", "members.view", "workspace.access"],
  builder: [
    "assistants.manage",
    "assistants.publish",
    "dashboard.view",
    "knowledge.manage",
    "members.view",
    "playground.use",
    "workspace.access",
  ],
  knowledge_editor: ["dashboard.view", "knowledge.manage", "members.view", "workspace.access"],
  reviewer: ["conversations.read", "dashboard.view", "members.view", "workspace.access"],
  viewer: ["dashboard.view", "members.view", "workspace.access"],
  member: ["workspace.access"],
};
const ORG_PERMISSIONS: Record<string, string[]> = {
  org_owner: [...WORKSPACE_ADMIN, "org.roles.manage", "org.settings.manage"],
  org_admin: [...WORKSPACE_ADMIN, "org.settings.manage"],
};

/** What `GET /workspaces/{id}` answers for a caller with these roles. */
export function workspaceInfo(
  workspace: { id: string; name: string },
  role: string | null,
  orgRole: string | null = null,
) {
  const permissions = new Set([
    ...(role ? (ROLE_PERMISSIONS[role] ?? []) : []),
    ...(orgRole ? (ORG_PERMISSIONS[orgRole] ?? []) : []),
  ]);
  return {
    id: workspace.id,
    name: workspace.name,
    role,
    org_role: orgRole,
    permissions: [...permissions].sort(),
  };
}

export const MULTI_SESSION = {
  ...SESSION,
  user: { id: "u1", display_name: "Minh Pham", email: "minh@x.test" },
  organization: { id: "o1", name: "Mekong Devworks" },
  org_role: null as string | null,
  workspaces: [
    { id: WS_B, name: "Finance", role: "viewer" as string | null },
    { id: WS, name: "People Ops", role: "builder" as string | null },
  ],
  default_workspace_id: WS,
};

/** Handlers for a signed-in user whose Workspace API answers for the memberships of `session`. */
export function signedInApi(session: typeof MULTI_SESSION = MULTI_SESSION) {
  const handlers: Record<string, () => Response> = {
    "GET /auth/session": () => json(200, session),
  };
  for (const workspace of session.workspaces) {
    handlers[`GET /workspaces/${workspace.id}`] = () =>
      json(200, workspaceInfo(workspace, workspace.role, session.org_role));
  }
  return handlers;
}
