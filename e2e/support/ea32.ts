// EA-32 (KB-01): helpers of the Collections and Folders specs. Black-box only: the admin origin (UI +
// /api proxy), the Platform Operator CLI, psql as the database superuser and the API logs. Builds on ./ea22.
// Everything a run creates carries the marker `qa-EA32-<run>` (collection names, Workspace names, user
// e-mails) so cleanupAll() and markerRows() can find it. Users and Workspaces are named so that the
// cleanup() of ea22.ts also removes them.
import path from "node:path";
import { expect, type Locator, type Page, type Response } from "@playwright/test";
import {
  ApiSession,
  DEMO_ORG,
  ROOT,
  RUN,
  UUID,
  cleanup,
  cli,
  compose,
  lines,
  newPassword,
  parseLink,
  rows,
  sql,
  testEmails,
  type ApiResult,
  type QaUser,
} from "./ea22";

export const MARK = `qa-EA32-${RUN}`;
export const SCREENSHOTS_32 = path.join(ROOT, ".work", "EA-32", "screenshots");

// ---------------------------------------------------------------------------------------------
// Copy of the contract (exact strings of the admin UI)
// ---------------------------------------------------------------------------------------------

export const COPY = {
  subtitle:
    "Collections hold your documents. Access is set per collection and enforced before anything reaches the model.",
  footnote:
    "Only Workspace Admins can change who can read a collection. Making a collection Public asks for confirmation and is recorded in the audit log.",
  headers: ["Collection", "Who can read", "Data handling", "Documents", "Status", "Used by"],
  legend: [
    ["Public", "Anyone, including anonymous visitors."],
    ["Authenticated", "Any signed-in user of your app."],
    [
      "Restricted",
      "Only people in one of the listed groups (from the widget token or Members & roles).",
    ],
  ],
  emptyTitle: "No collections yet",
  emptyBody: "Create a collection to start adding documents.",
  noMatch: "No collections match your search.",
  lockedNote: "Only Workspace Admins can change who can read a collection.",
  groupsHelper:
    "Separate groups with commas. People match when their widget token or Members & roles lists one of them.",
  localHelp:
    "Only a local model may answer from this collection; it cannot be attached to an assistant that uses a cloud model.",
  publicTitle: "Make this collection Public?",
  publicBody:
    "Anyone, including anonymous visitors, can get answers from its documents. This change is recorded in the audit log.",
  deleteLine:
    "Deletes the collection, its folders and everything indexed from it. This cannot be undone.",
  groupsRequired: "At least one group is required",
  forbidden: "You don't have permission to do this.",
  collectionTaken: "A collection with this name already exists.",
  folderTaken: "A folder with this name already exists here.",
  folderNotEmpty: "Remove its subfolders and documents first.",
  folderTooDeep: "Folders can be nested up to 3 levels.",
  invalidGroup: "Group names must be 1–64 characters, without commas; at most 20 groups.",
  generic: "Something went wrong. Try again.",
} as const;

export type AccessLevel = "public" | "authenticated" | "restricted";

/** The seed collections of People Ops, in list order (name, case-insensitive). */
export const SEED: {
  name: string;
  subtitle: string | null;
  access: AccessLevel;
  badge: string;
  local: boolean;
}[] = [
  { name: "Company & Careers", subtitle: null, access: "public", badge: "Public", local: false },
  {
    name: "Employee Handbook",
    subtitle: null,
    access: "authenticated",
    badge: "Authenticated",
    local: false,
  },
  {
    name: "Engineering Standards",
    subtitle: null,
    access: "authenticated",
    badge: "Authenticated",
    local: false,
  },
  {
    name: "IT & Security",
    subtitle: null,
    access: "authenticated",
    badge: "Authenticated",
    local: false,
  },
  {
    name: "Manager Handbook",
    subtitle: null,
    access: "restricted",
    badge: "Restricted · managers",
    local: true,
  },
  {
    name: "Project Falcon",
    subtitle: "Client: Japan · under NDA",
    access: "restricted",
    badge: "Restricted · project-falcon",
    local: true,
  },
];

// ---------------------------------------------------------------------------------------------
// API shapes
// ---------------------------------------------------------------------------------------------

export type CollectionItem = {
  id: string;
  name: string;
  subtitle: string | null;
  access_level: AccessLevel;
  groups: string[];
  local_only: boolean;
  documents: { total: number; ready: number; processing: number; needs_attention: number };
  used_by: unknown[];
  created_at: string;
  updated_at: string;
};
export type FolderItem = { id: string; name: string; parent_id: string | null; depth: number };
export type CollectionDetail = CollectionItem & { folders: FolderItem[] };
export const ITEM_KEYS = [
  "access_level",
  "created_at",
  "documents",
  "groups",
  "id",
  "local_only",
  "name",
  "subtitle",
  "updated_at",
  "used_by",
];
export const FOLDER_KEYS = ["depth", "document_count", "id", "name", "parent_id"];

export function collectionsPath(workspaceId: string): string {
  return `/api/workspaces/${workspaceId}/collections`;
}

export function json<T>(result: ApiResult): T {
  return result.json as T;
}

/** Drops problems of the given HTTP statuses (deliberate 403/409/422 answers show up as console errors). */
export function withoutStatuses(problems: string[], statuses: number[]): string[] {
  if (statuses.length === 0) return problems;
  const codes = statuses.join("|");
  const pattern = new RegExp(`status of (${codes})|^http (${codes}): `);
  return problems.filter((problem) => !pattern.test(problem));
}

// ---------------------------------------------------------------------------------------------
// Users (named so that ea22 cleanup() removes them)
// ---------------------------------------------------------------------------------------------

/** Invites a user with one role, sets a password through the API. */
export async function createMember(options: {
  label: string;
  role: string;
  workspaceId?: string;
  name?: string;
}): Promise<QaUser> {
  const email = `qa22.${MARK}.${options.label}@mekongdevworks.example`.toLowerCase();
  const name = options.name ?? `QA32 ${options.label} ${RUN}`;
  const args = ["user", "invite", "--org", DEMO_ORG, "--email", email, "--role", options.role];
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

// ---------------------------------------------------------------------------------------------
// Tracked API writes: everything created is deleted again by cleanupAll()
// ---------------------------------------------------------------------------------------------

type Tracked = { workspaceId: string; api: ApiSession };
const trackedCollections = new Map<string, Tracked>();
const trackedFolders = new Set<string>();

/** Registers a collection created outside the helpers (for example through the UI). */
export function track(collectionId: string, workspaceId: string, api: ApiSession): void {
  trackedCollections.set(collectionId, { workspaceId, api });
}

/** POST a collection; a 201 is tracked for cleanup. */
export async function createCollection(
  api: ApiSession,
  workspaceId: string,
  body: Record<string, unknown>,
): Promise<ApiResult> {
  const result = await api.send("POST", collectionsPath(workspaceId), { json: body });
  if (result.status === 201) track(json<CollectionItem>(result).id, workspaceId, api);
  return result;
}

/** POST a collection and expect 201. */
export async function mustCreateCollection(
  api: ApiSession,
  workspaceId: string,
  body: Record<string, unknown>,
): Promise<CollectionItem> {
  const result = await createCollection(api, workspaceId, body);
  expect(result.status, result.text).toBe(201);
  return json<CollectionItem>(result);
}

/** POST a folder; a 201 is tracked for cleanup. */
export async function createFolder(
  api: ApiSession,
  workspaceId: string,
  collectionId: string,
  body: Record<string, unknown>,
): Promise<ApiResult> {
  const result = await api.send("POST", `${collectionsPath(workspaceId)}/${collectionId}/folders`, {
    json: body,
  });
  if (result.status === 201) trackedFolders.add(json<FolderItem>(result).id);
  return result;
}

export async function mustCreateFolder(
  api: ApiSession,
  workspaceId: string,
  collectionId: string,
  body: Record<string, unknown>,
): Promise<FolderItem> {
  const result = await createFolder(api, workspaceId, collectionId, body);
  expect(result.status, result.text).toBe(201);
  return json<FolderItem>(result);
}

function softSql(statement: string): void {
  compose([
    "exec",
    "-T",
    "db",
    "psql",
    "-U",
    "postgres",
    "-d",
    "ei_ai",
    "-X",
    "-At",
    "-q",
    "-c",
    statement,
  ]);
}

/**
 * Removes everything this run (or a crashed earlier one) created: collections through the API (as their
 * creators), then their audit rows and any leftover rows as the superuser, then users and Workspaces
 * (cleanup() of ea22.ts). The SQL parts are best effort; the hygiene check in afterAll proves the result.
 */
export async function cleanupAll(): Promise<void> {
  const collectionIds = [...trackedCollections.keys()];
  const folderIds = [...trackedFolders];
  for (const [id, tracked] of trackedCollections) {
    try {
      await tracked.api.send("DELETE", `${collectionsPath(tracked.workspaceId)}/${id}`);
    } catch {
      // the SQL fallback below removes what is left
    }
  }
  trackedCollections.clear();
  trackedFolders.clear();

  const quoted = [...collectionIds, ...folderIds].map((id) => `'${id}'`);
  const targets = quoted.length > 0 ? `target_id::text in (${quoted.join(", ")}) or ` : "";
  const qaOrgs = "select id from organizations where name like 'QA EA-22 %'";
  const qaWorkspaces = `select id from workspaces where name like 'QA22 %'`;
  softSql(
    `delete from audit_events where (action like 'collection.%' or action like 'folder.%') and (${targets}workspace_id in (${qaWorkspaces}) or org_id in (${qaOrgs}))`,
  );
  const leftovers = `select id from collections where name ilike '%${MARK.slice(0, 8)}%' or workspace_id in (${qaWorkspaces}) or org_id in (${qaOrgs})`;
  softSql(`delete from folders where collection_id in (${leftovers})`);
  softSql(`delete from collections where id in (${leftovers})`);
  cleanup();
}

// ---------------------------------------------------------------------------------------------
// Database checks as the superuser
// ---------------------------------------------------------------------------------------------

export type Counts = { collections: number; folders: number; audit: number };

/** Row counts of the tables this ticket touches (the hygiene check compares before and after). */
export function counts(): Counts {
  return {
    collections: Number(sql("select count(*) from collections")),
    folders: Number(sql("select count(*) from folders")),
    audit: Number(
      sql(
        "select count(*) from audit_events where action like 'collection.%' or action like 'folder.%'",
      ),
    ),
  };
}

/** Names and e-mails that still carry the marker of any EA-32 run (must be empty after cleanup). */
export function markerRows(): string[] {
  return rows(
    `select name from collections where name ilike '%qa-ea32-%'
     union all select name from workspaces where name ilike '%qa-ea32-%'
     union all select email from users where email ilike '%qa-ea32-%'`,
  );
}

/** Number of rows with these ids in `collections` or `folders`. */
export function rowCount(table: "collections" | "folders", ids: string[]): number {
  if (ids.length === 0) return 0;
  const list = ids.map((id) => `'${id}'`).join(", ");
  return Number(sql(`select count(*) from ${table} where id::text in (${list})`));
}

export type AuditRow = {
  actor: string;
  action: string;
  target_type: string;
  workspace_id: string | null;
  old_value: string | null;
  new_value: string | null;
};

/** Audit events about one collection or folder, oldest first. */
export function auditOf(targetId: string): AuditRow[] {
  const out = sql(
    `select coalesce(json_agg(t order by t.created_at), '[]'::json) from (
       select actor, action, target_type, workspace_id::text as workspace_id, old_value, new_value, created_at
       from audit_events where target_id::text = '${targetId}'
     ) t`,
  );
  return (JSON.parse(out) as (AuditRow & { created_at: string })[]).map((row) => ({
    actor: row.actor,
    action: row.action,
    target_type: row.target_type,
    workspace_id: row.workspace_id,
    old_value: row.old_value,
    new_value: row.new_value,
  }));
}

/** Every audit old/new value written for these targets, to prove they hold codes only (D52). */
export function auditValues(targetIds: string[]): string[] {
  if (targetIds.length === 0) return [];
  const list = targetIds.map((id) => `'${id}'`).join(", ");
  return rows(
    `select coalesce(old_value, '') || '|' || coalesce(new_value, '') from audit_events where target_id::text in (${list})`,
  );
}

// ---------------------------------------------------------------------------------------------
// Browser helpers
// ---------------------------------------------------------------------------------------------

/** Every non-GET request to the API that the page sends (to prove "no request is sent"). */
export function mutations(page: Page): { method: string; path: string }[] {
  const seen: { method: string; path: string }[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method()) && pathname.startsWith("/api/")) {
      seen.push({ method: request.method(), path: pathname });
    }
  });
  return seen;
}

/** Starts waiting for the response of an API call; await it after the click. */
export function waitApi(page: Page, method: string, pattern: RegExp): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      response.request().method() === method && pattern.test(new URL(response.url()).pathname),
  );
}

export async function openKnowledge(page: Page, workspaceId: string): Promise<void> {
  await page.goto(`/w/${workspaceId}/knowledge`);
  await expect(page.getByTestId("knowledge-page")).toBeVisible();
}

export async function openDetail(
  page: Page,
  workspaceId: string,
  collectionId: string,
): Promise<void> {
  await page.goto(`/w/${workspaceId}/knowledge/${collectionId}`);
  await expect(page.getByTestId("collection-detail")).toBeVisible();
}

/** The list row whose name link has exactly this name. */
export function rowOf(page: Page, name: string): Locator {
  return page
    .getByTestId("collection-row")
    .filter({ has: page.getByRole("link", { name, exact: true }) });
}

export type FormValues = {
  name?: string;
  subtitle?: string;
  access?: "Public" | "Authenticated" | "Restricted";
  groups?: string;
  localOnly?: boolean;
};

/** Fills the fields given; leaves the others as they are. */
export async function fillCollectionForm(page: Page, values: FormValues): Promise<void> {
  const dialog = page.getByTestId("collection-dialog");
  if (values.name !== undefined) {
    await dialog.getByRole("textbox", { name: "Name", exact: true }).fill(values.name);
  }
  if (values.subtitle !== undefined) {
    await dialog
      .getByRole("textbox", { name: "Subtitle (optional)", exact: true })
      .fill(values.subtitle);
  }
  if (values.access !== undefined) {
    await dialog.getByRole("radio", { name: new RegExp(`^${values.access}`) }).check();
  }
  if (values.groups !== undefined) {
    await dialog.getByRole("textbox", { name: "Groups", exact: true }).fill(values.groups);
  }
  if (values.localOnly !== undefined) {
    await dialog.getByRole("checkbox", { name: /^Local model only/ }).setChecked(values.localOnly);
  }
}

export function radioOf(page: Page, level: "Public" | "Authenticated" | "Restricted"): Locator {
  return page
    .getByTestId("collection-dialog")
    .getByRole("radio", { name: new RegExp(`^${level}`) });
}

export async function openNewCollection(page: Page): Promise<Locator> {
  await page.getByTestId("new-collection").click();
  const dialog = page.getByTestId("collection-dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

export async function openSettings(page: Page): Promise<Locator> {
  await page.getByTestId("collection-settings").click();
  const dialog = page.getByTestId("collection-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Access & settings");
  return dialog;
}

/** A visible role=alert that contains `text`. */
export async function expectAlert(page: Page, text: string): Promise<void> {
  await expect(page.getByRole("alert").filter({ hasText: text }).first()).toBeVisible();
}

export function folderRow(page: Page, name: string): Locator {
  return page.getByTestId("folder-row").filter({ hasText: name });
}

/** The list rows in screen order as { name, text } (name = the first link's text). */
export async function listedNames(page: Page): Promise<string[]> {
  const links = page.getByTestId("collection-row").getByRole("link");
  const all = await links.allTextContents();
  return all.map((text) => text.trim());
}
