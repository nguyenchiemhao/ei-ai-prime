// EA-23 (FND-06): helpers of the RBAC and Members & roles specs. Black-box only: the Platform Operator
// CLI, psql as the database superuser, the admin origin (UI + /api proxy). Builds on ./ea22.
// Test users are named `qa22.ea23-<label>.<run>@mekongdevworks.example` and Workspaces `QA22 ...`, so
// the cleanup() of ea22.ts removes them (users, memberships, tokens, audit rows, Workspaces).
import path from "node:path";
import {
  expect,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";
import {
  ADMIN,
  ApiSession,
  DEMO_ORG,
  DESKTOP,
  NAV_GROUPS,
  ROOT,
  RUN,
  UUID,
  cli,
  lines,
  newPassword,
  parseLink,
  rows,
  sql,
  testEmails,
  type ApiResult,
  type QaUser,
} from "./ea22";

export const SCREENSHOTS_23 = path.join(ROOT, ".work", "EA-23", "screenshots");
export const IDENTITY_PARAMS = /[?&](user_?id|org_?id|groups?|tenant|role|permissions?)=/i;

// ---------------------------------------------------------------------------------------------
// The reviewed matrix (plan §5 T1), restated here from the requirements, not from the code.
// ---------------------------------------------------------------------------------------------

const WORKSPACE_ADMIN_SET = [
  "workspace.access",
  "dashboard.view",
  "knowledge.manage",
  "assistants.manage",
  "playground.use",
  "assistants.publish",
  "connectors.manage",
  "collections.access.manage",
  "members.view",
  "members.manage",
];

const GRANTS: Record<string, string[]> = {
  workspace_admin: WORKSPACE_ADMIN_SET,
  developer: ["workspace.access", "dashboard.view", "connectors.manage", "members.view"],
  builder: [
    "workspace.access",
    "dashboard.view",
    "knowledge.manage",
    "assistants.manage",
    "playground.use",
    "assistants.publish",
    "members.view",
  ],
  knowledge_editor: ["workspace.access", "dashboard.view", "knowledge.manage", "members.view"],
  reviewer: ["workspace.access", "dashboard.view", "conversations.read", "members.view"],
  viewer: ["workspace.access", "dashboard.view", "members.view"],
  member: ["workspace.access"],
};

const ORG_GRANTS: Record<string, string[]> = {
  org_owner: [...WORKSPACE_ADMIN_SET, "org.settings.manage", "org.roles.manage"],
  org_admin: [...WORKSPACE_ADMIN_SET, "org.settings.manage"],
};

/** Expected `permissions` of `GET /workspaces/{id}`: Org-role grants united with the Workspace-role grants. */
export function permissionsFor(orgRole: string | null, workspaceRole: string | null): string[] {
  const all = new Set<string>([
    ...(orgRole ? (ORG_GRANTS[orgRole] ?? []) : []),
    ...(workspaceRole ? (GRANTS[workspaceRole] ?? []) : []),
  ]);
  return [...all].sort();
}

/** The UI matrix grid of the contract: label, permission code, sensitive, [Admin, Developer, Builder, KE, Reviewer, Viewer]. */
export const UI_MATRIX: { label: string; code: string; sensitive: boolean; yes: boolean[] }[] = [
  {
    label: "Documents, scripts, glossary",
    code: "knowledge.manage",
    sensitive: false,
    yes: [true, false, true, true, false, false],
  },
  {
    label: "Assistants, skills, channels",
    code: "assistants.manage",
    sensitive: false,
    yes: [true, false, true, false, false, false],
  },
  {
    label: "Playground (test drafts, see traces)",
    code: "playground.use",
    sensitive: false,
    yes: [true, false, true, false, false, false],
  },
  {
    label: "Publish an assistant",
    code: "assistants.publish",
    sensitive: true,
    yes: [true, false, true, false, false, false],
  },
  {
    label: "Connectors, secrets, signing keys",
    code: "connectors.manage",
    sensitive: true,
    yes: [true, true, false, false, false, false],
  },
  {
    label: "Read conversations",
    code: "conversations.read",
    sensitive: true,
    yes: [false, false, false, false, true, false],
  },
  {
    label: "Change who can read a collection",
    code: "collections.access.manage",
    sensitive: false,
    yes: [true, false, false, false, false, false],
  },
  {
    label: "Dashboard",
    code: "dashboard.view",
    sensitive: false,
    yes: [true, true, true, true, true, true],
  },
];
export const MATRIX_COLUMNS = [
  "Admin",
  "Developer",
  "Builder",
  "Knowledge Editor",
  "Reviewer",
  "Viewer",
];
export const MATRIX_NOTE =
  "Highlighted rows are sensitive and kept in separate roles. Admins who need to read conversations assign themselves Reviewer; that change is recorded in the audit log.";

// ---------------------------------------------------------------------------------------------
// Sidebar: which areas each People Ops persona sees (contract §6)
// ---------------------------------------------------------------------------------------------

const BUILDER_AREAS = [
  "dashboard",
  "assistants",
  "knowledge",
  "answer-scripts",
  "glossary",
  "skills",
  "channels",
  "members",
];

export const AREAS_BY_PERSONA: Record<string, string[]> = {
  wsAdmin: BUILDER_AREAS,
  builder: BUILDER_AREAS,
  developer: ["dashboard", "skills", "channels", "members"],
  ke: ["dashboard", "knowledge", "answer-scripts", "glossary", "members"],
  reviewer: ["dashboard", "conversations", "unanswered", "members"],
  viewer: ["dashboard", "members"],
  orgAdmin: [...BUILDER_AREAS, "organization"],
  orgOwner: [...BUILDER_AREAS, "organization"],
  orgAdminReviewer: [...BUILDER_AREAS, "conversations", "unanswered", "organization"],
};

export const ALL_AREAS = NAV_GROUPS.flatMap((group) => group.items.map(([, slug]) => slug));

/** NAV_GROUPS restricted to the areas in `slugs`; groups left empty are dropped. */
export function visibleNav(slugs: string[]): { group: string; items: [string, string][] }[] {
  return NAV_GROUPS.map(({ group, items }) => ({
    group,
    items: items.filter(([, slug]) => slugs.includes(slug)),
  })).filter(({ items }) => items.length > 0);
}

// ---------------------------------------------------------------------------------------------
// Users with several roles; sessions
// ---------------------------------------------------------------------------------------------

/** Invites a user with any mix of roles (`--role` repeated), sets a password through the API. */
export async function createUser(options: {
  label: string;
  roles: string[];
  workspaceId?: string;
  name?: string;
}): Promise<QaUser> {
  const email = `qa22.ea23-${options.label.toLowerCase()}.${RUN}@mekongdevworks.example`;
  const name = options.name ?? `QA23 ${options.label} ${RUN}`;
  const args = ["user", "invite", "--org", DEMO_ORG, "--email", email];
  for (const role of options.roles) args.push("--role", role);
  if (options.workspaceId) args.push("--workspace", options.workspaceId);
  args.push("--name", name);
  const run = cli(args);
  expect(run.status, run.stderr).toBe(0);
  const out = lines(run.stdout);
  expect(out).toHaveLength(2);
  const match = new RegExp(`^User invited: (${UUID}) \\(.+\\) roles: .+$`).exec(out[0] ?? "");
  expect(match, out[0]).not.toBeNull();
  testEmails.add(email);
  const link = parseLink(out[1]);
  const password = newPassword();
  const result = await new ApiSession().setPassword(link.token, password);
  expect(result.status, result.text).toBe(204);
  return { id: match?.[1] as string, email, name, password, link };
}

/** Signs in through the API (books the shared sign-in budget). */
export async function signedInApi(user: QaUser): Promise<ApiSession> {
  const api = new ApiSession();
  const result = await api.signIn(user.email, user.password);
  expect(result.status, `sign-in of ${user.email}: ${result.text}`).toBeLessThan(300);
  return api;
}

/** A browser context that carries the cookies of an API session (no extra sign-in). */
export async function withSession<T>(
  browser: Browser,
  api: ApiSession,
  fn: (page: Page, context: BrowserContext) => Promise<T>,
): Promise<T> {
  const context = await browser.newContext({ viewport: DESKTOP });
  await context.addCookies([...api.jar].map(([name, value]) => ({ name, value, url: ADMIN })));
  try {
    return await fn(await context.newPage(), context);
  } finally {
    await context.close();
  }
}

export function body<T>(result: ApiResult): T {
  return result.json as T;
}

// ---------------------------------------------------------------------------------------------
// API shapes of the contract
// ---------------------------------------------------------------------------------------------

export type WorkspaceInfo = {
  id: string;
  name: string;
  role: string | null;
  org_role: string | null;
  permissions: string[];
};
export type MemberItem = {
  user_id: string;
  display_name: string;
  email: string;
  role: string;
  org_role: string | null;
  last_active_at: string | null;
};
export const MEMBER_KEYS = [
  "display_name",
  "email",
  "last_active_at",
  "org_role",
  "role",
  "user_id",
];
export type SessionBody = {
  user: { id: string; display_name: string; email: string };
  organization: { id: string; name: string };
  org_role: string | null;
  workspaces: { id: string; name: string; role: string | null }[];
  default_workspace_id: string | null;
};

// ---------------------------------------------------------------------------------------------
// Database checks as the superuser
// ---------------------------------------------------------------------------------------------

export function wsRoleOf(workspaceId: string, userId: string): string | null {
  const out = rows(
    `select role from workspace_memberships where org_id = '${DEMO_ORG}' and workspace_id = '${workspaceId}' and user_id = '${userId}'`,
  )[0];
  return out === undefined || out === "" ? null : out;
}

export function orgRoleOf(userId: string): string | null {
  const out = rows(
    `select coalesce(org_role, '') from memberships where org_id = '${DEMO_ORG}' and user_id = '${userId}'`,
  )[0];
  return out === undefined || out === "" ? null : out;
}

export type AuditRow = {
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  workspace_id: string | null;
  old_value: string | null;
  new_value: string | null;
};

/**
 * Role-change events about `targetIds`, oldest first. `by`: "users" = made through the API/UI
 * (actor `user:<id>`), "operator" = made by the CLI (`platform-operator`), "any" = both.
 */
export function roleAudit(
  targetIds: string[],
  by: "users" | "operator" | "any" = "users",
): AuditRow[] {
  if (targetIds.length === 0) return [];
  const ids = targetIds.map((id) => `'${id}'`).join(", ");
  const actor =
    by === "users"
      ? "and actor like 'user:%'"
      : by === "operator"
        ? "and actor = 'platform-operator'"
        : "";
  const out = sql(
    `select coalesce(json_agg(t order by t.created_at), '[]'::json) from (
       select actor, action, target_type, target_id::text as target_id, workspace_id::text as workspace_id,
              old_value, new_value, created_at
       from audit_events
       where org_id = '${DEMO_ORG}' and action in ('member.workspace_role_changed', 'member.org_role_changed')
         and target_id::text in (${ids}) ${actor}
     ) t`,
  );
  return (JSON.parse(out) as (AuditRow & { created_at: string })[]).map(
    ({ actor, action, target_type, target_id, workspace_id, old_value, new_value }) => ({
      actor,
      action,
      target_type,
      target_id,
      workspace_id,
      old_value,
      new_value,
    }),
  );
}

export function countRoleEvents(): number {
  return Number(
    sql(
      `select count(*) from audit_events where org_id = '${DEMO_ORG}' and action in ('member.workspace_role_changed', 'member.org_role_changed')`,
    ),
  );
}

// ---------------------------------------------------------------------------------------------
// The role control is a "combobox" by role and name: a native <select> or a custom listbox.
// ---------------------------------------------------------------------------------------------

async function isNativeSelect(control: Locator): Promise<boolean> {
  return control.evaluate((element) => element.tagName === "SELECT");
}

/** Picks the option with this visible label. */
export async function chooseOption(control: Locator, label: string): Promise<void> {
  if (await isNativeSelect(control)) {
    await control.selectOption({ label });
    return;
  }
  await control.click();
  await control.page().getByRole("option", { name: label, exact: true }).click();
}

/** The visible labels of the options, in order. */
export async function optionLabels(control: Locator): Promise<string[]> {
  if (await isNativeSelect(control)) {
    return (await control.locator("option").allTextContents()).map((text) => text.trim());
  }
  await control.click();
  const options = control.page().getByRole("option");
  const labels = (await options.allTextContents()).map((text) => text.trim());
  await control.page().keyboard.press("Escape");
  return labels;
}

/** The label of the selected option. */
export async function selectedLabel(control: Locator): Promise<string> {
  if (await isNativeSelect(control)) {
    return (await control.locator("option:checked").first().textContent())?.trim() ?? "";
  }
  return ((await control.textContent()) ?? "").trim();
}
