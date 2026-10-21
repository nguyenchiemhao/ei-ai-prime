// EA-94 (FND-14): helpers of the demo-seed specs. Black-box only: `npm run seed` (node scripts/dev.mjs
// seed), the Platform Operator CLI, psql as the database superuser, the admin origin (UI + /api proxy)
// and the container logs. Builds on ./ea22 and ./ea23. The expected data below is restated from
// .work/EA-94/contract.md (sections 2 to 4), never read from the manifest or the source.
// The shared password is never written here: seedPassword() reads it from the environment, .env or
// .env.example, exactly like `npm run seed` does.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect } from "@playwright/test";
import { ApiSession, ROOT, UUID, lines, rows, sql, type ApiResult } from "./ea22";

export const SCREENSHOTS_94 = path.join(ROOT, ".work", "EA-94", "screenshots");
export const MARK_94 = "qa-ea94-";
export const SEED_REFUSED = "refused: the demo seed runs only in local or test environments";
export const SEED_REFUSED_LINES = [SEED_REFUSED];
export const PASSWORD_MISSING = "configuration error: EI_AI_SEED_PASSWORD is required";
export const PASSWORD_TOO_LONG =
  "configuration error: EI_AI_SEED_PASSWORD must be at most 128 characters";

// ---------------------------------------------------------------------------------------------
// The shared test password (never hard-coded)
// ---------------------------------------------------------------------------------------------

/** Value of EI_AI_SEED_PASSWORD in a dotenv-style file; undefined when the line or value is missing. */
export function dotenvValue(file: string, name = "EI_AI_SEED_PASSWORD"): string | undefined {
  if (!fs.existsSync(file)) return undefined;
  let found: string | undefined;
  for (const line of fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n").split("\n")) {
    const match = new RegExp(`^${name}=(.*)$`).exec(line);
    if (!match) continue;
    let value = (match[1] ?? "").trim();
    const quoted = /^(["'])(.*)\1/.exec(value);
    if (quoted) value = quoted[2] ?? "";
    else value = value.replace(/\s+#.*$/, "");
    found = value;
  }
  return found === "" ? undefined : found;
}

/** The password the stack was seeded with: shell, then .env, then the default of .env.example. */
export function seedPassword(): string {
  const fromShell = process.env.EI_AI_SEED_PASSWORD;
  if (fromShell) return fromShell;
  const fromEnv = dotenvValue(path.join(ROOT, ".env"));
  if (fromEnv) return fromEnv;
  const fromExample = dotenvValue(path.join(ROOT, ".env.example"));
  if (!fromExample) throw new Error("EI_AI_SEED_PASSWORD is not set in .env or .env.example");
  return fromExample;
}

// ---------------------------------------------------------------------------------------------
// Expected data (contract section 2)
// ---------------------------------------------------------------------------------------------

export type OrgKey = "mekong" | "songhan";
export const ORGS: Record<OrgKey, { id: string; name: string; workspaces: string[] }> = {
  mekong: {
    id: "0192a000-0000-7000-8000-00000000ea21",
    name: "Mekong Devworks",
    workspaces: ["People Ops", "Engineering"],
  },
  songhan: {
    id: "0192a000-0000-7000-8000-00000000ea94",
    name: "Sông Hàn Retail",
    workspaces: ["Customer Care"],
  },
};
export const ORG_IDS = [ORGS.mekong.id, ORGS.songhan.id];

export type Account = {
  name: string;
  email: string;
  org: OrgKey;
  orgRole: "org_owner" | "org_admin" | null;
  /** Workspace name to Workspace role code (only the Workspaces where the person has a role). */
  roles: Record<string, string>;
  /** Workspace the sign-in lands on. */
  lands: string;
  /** True when the account is given the shared password. */
  shared: boolean;
};

const MEKONG = "@mekongdevworks.example";
export const SYSADMIN_EMAIL = `sysadmin${MEKONG}`;

export const ACCOUNTS: Account[] = [
  {
    name: "Linh Tran",
    email: `linh.tran${MEKONG}`,
    org: "mekong",
    orgRole: "org_admin",
    roles: { "People Ops": "workspace_admin" },
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Minh Pham",
    email: `minh.pham${MEKONG}`,
    org: "mekong",
    orgRole: null,
    roles: { "People Ops": "builder" },
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Thao Nguyen",
    email: `thao.nguyen${MEKONG}`,
    org: "mekong",
    orgRole: null,
    roles: { "People Ops": "knowledge_editor" },
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Quang Le",
    email: `quang.le${MEKONG}`,
    org: "mekong",
    orgRole: null,
    roles: { "People Ops": "developer", Engineering: "workspace_admin" },
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Hà Vũ",
    email: `ha.vu${MEKONG}`,
    org: "mekong",
    orgRole: null,
    roles: { "People Ops": "reviewer" },
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Son Hoang",
    email: `son.hoang${MEKONG}`,
    org: "mekong",
    orgRole: null,
    roles: { "People Ops": "viewer" },
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Duy Lâm",
    email: `duy.lam${MEKONG}`,
    org: "mekong",
    orgRole: "org_owner",
    roles: {},
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Vy Huỳnh",
    email: `vy.huynh${MEKONG}`,
    org: "mekong",
    orgRole: null,
    roles: { Engineering: "developer" },
    lands: "Engineering",
    shared: true,
  },
  {
    name: "Phúc Lương",
    email: `phuc.luong${MEKONG}`,
    org: "mekong",
    orgRole: null,
    roles: { Engineering: "knowledge_editor" },
    lands: "Engineering",
    shared: true,
  },
  {
    name: "Trung Võ",
    email: SYSADMIN_EMAIL,
    org: "mekong",
    orgRole: "org_owner",
    roles: { "People Ops": "workspace_admin", Engineering: "workspace_admin" },
    lands: "People Ops",
    shared: true,
  },
  {
    name: "Ngân Trịnh",
    email: "ngan.trinh@songhanretail.example",
    org: "songhan",
    orgRole: "org_admin",
    roles: { "Customer Care": "workspace_admin" },
    lands: "Customer Care",
    shared: true,
  },
];

/** The sysadmin's second membership: Sông Hàn Retail, membership only, no credential. */
export const SONGHAN_SYSADMIN: Account = {
  name: "Trung Võ",
  email: SYSADMIN_EMAIL,
  org: "songhan",
  orgRole: "org_owner",
  roles: { "Customer Care": "workspace_admin" },
  lands: "Customer Care",
  shared: false,
};

/** Accounts of one Organization with a stored membership (sign-in or not). */
export function membersOf(org: OrgKey): Account[] {
  return [...ACCOUNTS, SONGHAN_SYSADMIN].filter((account) => account.org === org);
}

export type CollectionSpec = {
  workspace: string;
  name: string;
  subtitle: string | null;
  access: "public" | "authenticated" | "restricted";
  groups: string[];
  localOnly: boolean;
  /** Folder paths, levels joined by "/"; a parent always precedes its children. */
  folders: string[];
};

export const COLLECTIONS: CollectionSpec[] = [
  {
    workspace: "People Ops",
    name: "Company & Careers",
    subtitle: null,
    access: "public",
    groups: [],
    localOnly: false,
    folders: ["About Mekong Devworks", "Hiring process", "Candidate FAQ"],
  },
  {
    workspace: "People Ops",
    name: "Employee Handbook",
    subtitle: null,
    access: "authenticated",
    groups: [],
    localOnly: false,
    folders: [
      "Policies",
      "Policies/Leave & time off",
      "Policies/Working hours & overtime",
      "Policies/Remote work & business travel",
      "Benefits",
      "Benefits/Allowances",
      "Benefits/Insurance & health care",
      "Onboarding & offboarding",
      "Onboarding & offboarding/First week",
      "Onboarding & offboarding/Leaving the company",
      "Templates",
      "Templates/HR forms",
      "Templates/Contracts",
      "Templates/Contracts/Labor contracts",
    ],
  },
  {
    workspace: "People Ops",
    name: "Engineering Standards",
    subtitle: null,
    access: "authenticated",
    groups: [],
    localOnly: false,
    folders: ["Coding conventions", "Code review", "Definition of Done"],
  },
  {
    workspace: "People Ops",
    name: "IT & Security",
    subtitle: null,
    access: "authenticated",
    groups: [],
    localOnly: false,
    folders: ["Accounts & access", "Devices & equipment", "Security policies"],
  },
  {
    workspace: "People Ops",
    name: "Manager Handbook",
    subtitle: null,
    access: "restricted",
    groups: ["managers"],
    localOnly: true,
    folders: ["Performance reviews", "Hiring & approvals"],
  },
  {
    workspace: "People Ops",
    name: "Project Falcon",
    subtitle: "Client: Japan · under NDA",
    access: "restricted",
    groups: ["project-falcon"],
    localOnly: true,
    folders: ["Requirements", "Meeting notes", "Delivery"],
  },
  {
    workspace: "Engineering",
    name: "Architecture Decisions",
    subtitle: null,
    access: "authenticated",
    groups: [],
    localOnly: false,
    folders: ["Accepted", "Superseded"],
  },
  {
    workspace: "Engineering",
    name: "Runbooks",
    subtitle: null,
    access: "restricted",
    groups: ["on-call"],
    localOnly: true,
    folders: ["Incidents", "Incidents/Postmortems", "Deployments"],
  },
  {
    workspace: "Customer Care",
    name: "Store Policies",
    subtitle: null,
    access: "authenticated",
    groups: [],
    localOnly: false,
    folders: ["Returns & exchanges", "Delivery & installation", "Warranty"],
  },
];

export function collectionsOf(org: OrgKey): CollectionSpec[] {
  return COLLECTIONS.filter((spec) => ORGS[org].workspaces.includes(spec.workspace));
}

export const EXPECTED_ROWS: Record<OrgKey, Record<string, number>> = {
  mekong: {
    organizations: 1,
    workspaces: 2,
    users: 10,
    memberships: 10,
    workspace_memberships: 11,
    user_credentials: 10,
    set_password_tokens: 0,
    collections: 8,
    folders: 33,
    model_catalog: 3,
    audit_events: 78,
  },
  songhan: {
    organizations: 1,
    workspaces: 1,
    users: 2,
    memberships: 2,
    workspace_memberships: 2,
    user_credentials: 1,
    set_password_tokens: 0,
    collections: 1,
    folders: 3,
    model_catalog: 3,
    audit_events: 13,
  },
};

export const EXPECTED_AUDIT: Record<OrgKey, Record<string, number>> = {
  mekong: {
    "organization.created": 1,
    "workspace.created": 2,
    "user.invited": 10,
    "member.org_role_changed": 3,
    "member.workspace_role_changed": 11,
    "user.password_set": 10,
    "collection.created": 8,
    "folder.created": 33,
  },
  songhan: {
    "organization.created": 1,
    "workspace.created": 1,
    "user.invited": 2,
    "member.org_role_changed": 2,
    "member.workspace_role_changed": 2,
    "user.password_set": 1,
    "collection.created": 1,
    "folder.created": 3,
  },
};
export const SEED_ACTIONS = Object.keys(EXPECTED_AUDIT.mekong);

// ---------------------------------------------------------------------------------------------
// Expected seed output (contract section 3); "<uuid>" stands for any UUID
// ---------------------------------------------------------------------------------------------

export const FRESH_OUTPUT = [
  "Demo seed: Mekong Devworks",
  "  Organization: Mekong Devworks (<uuid>): created",
  "  Workspace: People Ops (<uuid>): created",
  "  Workspace: Engineering (<uuid>): created",
  "  Members: 10",
  "    - Linh Tran: org_admin, People Ops=workspace_admin: created",
  "    - Minh Pham: People Ops=builder: created",
  "    - Thao Nguyen: People Ops=knowledge_editor: created",
  "    - Quang Le: People Ops=developer, Engineering=workspace_admin: created",
  "    - Hà Vũ: People Ops=reviewer: created",
  "    - Son Hoang: People Ops=viewer: created",
  "    - Duy Lâm: org_owner: created",
  "    - Vy Huỳnh: Engineering=developer: created",
  "    - Phúc Lương: Engineering=knowledge_editor: created",
  "    - Trung Võ: org_owner, People Ops=workspace_admin, Engineering=workspace_admin: created",
  "  Collections: 8 (created: 8)",
  "  Folders: 33 (created: 33)",
  "  Shared test password applied to 10 of 10 accounts",
  "  Audit events written: 78",
  "Demo seed: Sông Hàn Retail",
  "  Organization: Sông Hàn Retail (<uuid>): created",
  "  Workspace: Customer Care (<uuid>): created",
  "  Members: 2",
  "    - Ngân Trịnh: org_admin, Customer Care=workspace_admin: created",
  "    - Trung Võ: org_owner, Customer Care=workspace_admin: created",
  "  Collections: 1 (created: 1)",
  "  Folders: 3 (created: 3)",
  "  Shared test password applied to 1 of 1 accounts",
  "  Audit events written: 13",
];

/** What a run that creates nothing prints, derived from the fresh output (contract section 3). */
export function repeatOutput(): string[] {
  return FRESH_OUTPUT.map((line) =>
    line
      .replace(/: created$/, ": already present")
      .replace(/\(created: \d+\)/, "(created: 0)")
      .replace(/applied to \d+ of/, "applied to 0 of")
      .replace(/Audit events written: \d+/, "Audit events written: 0"),
  );
}

/** Output lines with every UUID replaced by "<uuid>". */
export function normalizeOutput(text: string): string[] {
  return lines(text).map((line) => line.replace(new RegExp(UUID, "g"), "<uuid>"));
}

// ---------------------------------------------------------------------------------------------
// Processes
// ---------------------------------------------------------------------------------------------

export type Run = { status: number | null; stdout: string; stderr: string; ms: number };

/** Every stdout/stderr this spec captured from a seed command (swept for the password in AC6). */
export const capturedOutputs: { label: string; text: string }[] = [];

function spawn(file: string, args: string[], input?: string): Run {
  const started = Date.now();
  const result = spawnSync(file, args, {
    cwd: ROOT,
    encoding: "utf8",
    input,
    maxBuffer: 64 * 1024 * 1024,
  });
  return {
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    ms: Date.now() - started,
  };
}

function remember(label: string, run: Run): Run {
  capturedOutputs.push({ label: `${label} stdout`, text: run.stdout });
  capturedOutputs.push({ label: `${label} stderr`, text: run.stderr });
  return run;
}

/** `npm run seed` without npm (the script the package.json entry runs). */
export function seed(label = "npm run seed"): Run {
  return remember(label, spawn(process.execPath, ["scripts/dev.mjs", "seed"]));
}

/** `docker compose exec -T -e K=V ... api ei-ai seed demo`; an empty string sets the variable empty. */
export function seedDirect(env: Record<string, string>, label: string): Run {
  const envArgs = Object.entries(env).flatMap(([key, value]) => ["-e", `${key}=${value}`]);
  return remember(
    label,
    spawn("docker", ["compose", "exec", "-T", ...envArgs, "api", "ei-ai", "seed", "demo"]),
  );
}

export function compose(args: string[]): Run {
  return spawn("docker", ["compose", ...args]);
}

/** Container log text of a Compose service. */
export function serviceLogs(service: string): string {
  return compose(["logs", "--no-color", service]).stdout;
}

// ---------------------------------------------------------------------------------------------
// Database (superuser, read-only except purge and restore)
// ---------------------------------------------------------------------------------------------

const PURGE_ORDER = [
  "admin_sessions",
  "user_credentials",
  "set_password_tokens",
  "audit_events",
  "folders",
  "collections",
  "model_catalog",
  "workspace_memberships",
  "memberships",
  "users",
  "workspaces",
];
export const COUNT_TABLES = [
  "organizations",
  "workspaces",
  "users",
  "memberships",
  "workspace_memberships",
  "user_credentials",
  "set_password_tokens",
  "collections",
  "folders",
  "model_catalog",
  "audit_events",
];

/** Deletes both demo Organizations and everything under them, children first (RLS is never altered). */
export function purgeDemoOrgs(): void {
  const statements = ORG_IDS.flatMap((id) => [
    ...PURGE_ORDER.map((table) => `delete from ${table} where org_id = '${id}';`),
    `delete from organizations where id = '${id}';`,
  ]);
  sql(`begin; ${statements.join(" ")} commit;`);
}

/** Row counts per table of one Organization (the table list of contract section 4). */
export function orgCounts(orgId: string): Record<string, number> {
  const parts = COUNT_TABLES.map((table) => {
    const filter = table === "organizations" ? `id = '${orgId}'` : `org_id = '${orgId}'`;
    return `select '${table}', count(*) from ${table} where ${filter}`;
  });
  const result: Record<string, number> = {};
  for (const row of rows(parts.join(" union all "))) {
    const [table, count] = row.split("|");
    result[table as string] = Number(count);
  }
  return result;
}

/** Row counts per table outside both demo Organizations (must never change during this spec). */
export function otherCounts(): Record<string, number> {
  const list = ORG_IDS.map((id) => `'${id}'`).join(", ");
  const parts = COUNT_TABLES.map((table) => {
    const filter = table === "organizations" ? `id not in (${list})` : `org_id not in (${list})`;
    return `select '${table}', count(*) from ${table} where ${filter}`;
  });
  const result: Record<string, number> = {};
  for (const row of rows(parts.join(" union all "))) {
    const [table, count] = row.split("|");
    result[table as string] = Number(count);
  }
  return result;
}

/** Audit event count per action of one Organization. */
export function auditByAction(orgId: string): Record<string, number> {
  const result: Record<string, number> = {};
  for (const row of rows(
    `select action || '|' || count(*) from audit_events where org_id = '${orgId}' group by action`,
  )) {
    const [action, count] = row.split("|");
    result[action as string] = Number(count);
  }
  return result;
}

/** Workspace name to id of one Organization. */
export function workspaceIds(orgId: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const row of rows(`select name || '|' || id from workspaces where org_id = '${orgId}'`)) {
    const [name, id] = row.split("|");
    result[name as string] = id as string;
  }
  return result;
}

export function userId(orgId: string, email: string): string {
  const id = rows(`select id from users where org_id = '${orgId}' and email = '${email}'`)[0];
  expect(id, `precondition: user ${email} exists`).toBeTruthy();
  return id as string;
}

/** Full user_credentials row as JSON text (saved before a mutation, restored by restoreCredential). */
export function saveCredential(orgId: string, uid: string): string | null {
  const out = rows(
    `select row_to_json(c)::text from user_credentials c where org_id = '${orgId}' and user_id = '${uid}'`,
  )[0];
  return out ?? null;
}

/** Puts a saved credential row back exactly (or removes the credential when none was saved). */
export function restoreCredential(orgId: string, uid: string, saved: string | null): void {
  const remove = `delete from user_credentials where org_id = '${orgId}' and user_id = '${uid}';`;
  const insert =
    saved === null
      ? ""
      : `insert into user_credentials select * from json_populate_record(null::user_credentials, '${saved.replace(/'/g, "''")}'::json);`;
  sql(`begin; ${remove} ${insert} commit;`);
}

export function passwordHashOf(orgId: string, uid: string): string | null {
  const out = rows(
    `select password_hash from user_credentials where org_id = '${orgId}' and user_id = '${uid}'`,
  )[0];
  return out ?? null;
}

/** Audit event ids about one target (the keep-list for deleteAuditExcept). */
export function auditIdsOf(orgId: string, targetId: string): string[] {
  return rows(
    `select id::text from audit_events where org_id = '${orgId}' and target_id::text = '${targetId}'`,
  );
}

/** Removes audit rows about one target that were created after the keep-list was taken. */
export function deleteAuditExcept(orgId: string, targetId: string, keep: string[]): void {
  const list = keep.length > 0 ? keep.map((id) => `'${id}'`).join(", ") : "''";
  sql(
    `delete from audit_events where org_id = '${orgId}' and target_id::text = '${targetId}' and id::text not in (${list})`,
  );
}

/** Sessions created by this spec's sign-ins and audit rows of non-seed actions in the demo orgs. */
export function removeRunTraces(): void {
  const list = ORG_IDS.map((id) => `'${id}'`).join(", ");
  const actions = SEED_ACTIONS.map((action) => `'${action}'`).join(", ");
  sql(
    `begin; delete from admin_sessions where org_id in (${list});
     delete from audit_events where org_id in (${list}) and action not in (${actions}, 'workspace.member_added');
     commit;`,
  );
}

/** Whole-row text of tables that must never hold the password (everything except the hash table). */
export function rowsContaining(value: string): string[] {
  const escaped = value.replace(/'/g, "''");
  const tables = COUNT_TABLES.filter((table) => table !== "user_credentials");
  const parts = tables.map(
    (table) =>
      `select '${table}' from ${table} t where position('${escaped}' in row_to_json(t)::text) > 0`,
  );
  return rows(parts.join(" union all "));
}

// ---------------------------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------------------------

const sessions = new Map<string, ApiSession>();

/** A signed-in API session per account, signed in once and reused (sign-ins are rate limited). */
export async function sessionFor(email: string, password = seedPassword()): Promise<ApiSession> {
  const cached = sessions.get(email);
  if (cached) return cached;
  const api = new ApiSession();
  const result = await api.signIn(email, password);
  expect(result.status, `sign-in of ${email}: ${result.text}`).toBe(200);
  sessions.set(email, api);
  return api;
}

export function rememberSession(email: string, api: ApiSession): void {
  sessions.set(email, api);
}

export function forgetSession(email: string): void {
  sessions.delete(email);
}

export function json<T>(result: ApiResult): T {
  return result.json as T;
}

export function collectionsPath(workspaceId: string): string {
  return `/api/workspaces/${workspaceId}/collections`;
}

export type FolderItem = { id: string; name: string; parent_id: string | null; depth: number };
export type CollectionItem = {
  id: string;
  name: string;
  subtitle: string | null;
  access_level: string;
  groups: string[];
  local_only: boolean;
};
export type CollectionDetail = CollectionItem & { folders: FolderItem[] };

/** Folder paths ("A/B/C") of a collection detail, built from parent_id, sorted. */
export function folderPaths(detail: CollectionDetail): string[] {
  const byId = new Map(detail.folders.map((folder) => [folder.id, folder]));
  const pathOf = (folder: FolderItem): string =>
    folder.parent_id === null
      ? folder.name
      : `${pathOf(byId.get(folder.parent_id) as FolderItem)}/${folder.name}`;
  return sorted(detail.folders.map(pathOf));
}

/** Compares two strings the way a person reads a sorted list (no locale surprises). */
export function sorted(values: string[]): string[] {
  return [...values].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

export function readmePath(): string {
  return path.join(ROOT, "docs", "dev", "seed-data.md");
}
