// EA-23 (FND-06): 3-tier RBAC in the API and the Members & roles screen. Black-box specs from
// .work/EA-23/plan.md §4 and §6 (test contract) only. Runs against a running, migrated and seeded stack:
//   npm run up -- --no-model && npm run seed && npm run e2e -- e2e/foundation/EA-23-*
// Everything the tests create is named `qa22.ea23-*` / `QA22 EA23 *`, so cleanup() of ea22.ts removes it.
// Sessions: users sign in through the API (shared 30/minute budget); browser pages reuse those cookies,
// except in AC4 where the user signs in through the UI as the AC says.
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  ADMIN,
  ApiSession,
  DEMO_ORG,
  RUN,
  ROOT,
  addMember,
  apiLogsSince,
  cleanup,
  createForeignOrg,
  createWorkspace,
  expectDetail,
  expectSameAnswer,
  newPassword,
  peopleOpsId,
  rows,
  signInUi,
  sql,
  watch,
  withPage,
  withoutExpected401,
  type ForeignOrg,
  type QaUser,
} from "../support/ea22";
import {
  ALL_AREAS,
  AREAS_BY_PERSONA,
  IDENTITY_PARAMS,
  MATRIX_COLUMNS,
  MATRIX_NOTE,
  MEMBER_KEYS,
  SCREENSHOTS_23,
  UI_MATRIX,
  body,
  chooseOption,
  countRoleEvents,
  createUser,
  optionLabels,
  orgRoleOf,
  permissionsFor,
  roleAudit,
  selectedLabel,
  signedInApi,
  visibleNav,
  withSession,
  wsRoleOf,
  type MemberItem,
  type SessionBody,
  type WorkspaceInfo,
} from "../support/ea23";

test.describe.configure({ mode: "serial", timeout: 240_000 });

const FORBIDDEN_TEXT =
  "Your role in this workspace does not include this page. Ask a workspace admin if you need it.";

let peopleOps = "";
let startedAt = "";
let wsX = "";
let wsY = "";
let foreign: ForeignOrg;
const users = new Map<string, QaUser>();
const sessions = new Map<string, ApiSession>();

function user(key: string): QaUser {
  const found = users.get(key);
  if (!found) throw new Error(`no test user ${key}`);
  return found;
}

/** A cached API session of a test user. */
async function api(key: string): Promise<ApiSession> {
  const cached = sessions.get(key);
  if (cached) return cached;
  const session = await signedInApi(user(key));
  sessions.set(key, session);
  return session;
}

/** The owner of the other Organization (sets the password from the CLI link on first use). */
async function foreignOwnerApi(): Promise<ApiSession> {
  const cached = sessions.get("foreignOwner");
  if (cached) return cached;
  const owner = new ApiSession();
  const password = newPassword();
  expect((await owner.setPassword(foreign.link.token, password)).status).toBe(204);
  expect((await owner.signIn(foreign.ownerEmail, password)).status).toBeLessThan(300);
  sessions.set("foreignOwner", owner);
  return owner;
}

function url(workspaceId: string, area = "dashboard"): string {
  return `${ADMIN}/w/${workspaceId}/${area}`;
}

const infoCache = new Map<string, WorkspaceInfo>();
/** `GET /api/workspaces/<People Ops>` as a persona (cached: AC2 and AC3 read the same answers). */
async function infoOf(key: string): Promise<WorkspaceInfo> {
  const cached = infoCache.get(key);
  if (cached) return cached;
  const result = await (await api(key)).workspace(peopleOps);
  expect(result.status, `${key}: ${result.text}`).toBe(200);
  const info = body<WorkspaceInfo>(result);
  infoCache.set(key, info);
  return info;
}

function memberRow(page: Page, userId: string): Locator {
  return page.locator(`[data-testid="member-row"][data-user-id="${userId}"]`);
}

function roleSelect(page: Page, name: string): Locator {
  return page.getByRole("combobox", { name: `Role for ${name}`, exact: true });
}

async function openMembers(page: Page, workspaceId: string): Promise<void> {
  await page.goto(`/w/${workspaceId}/members`);
  await expect(page.getByTestId("members-page")).toBeVisible();
  await expect(page.getByTestId("member-row").first()).toBeVisible();
}

test.beforeAll(async () => {
  test.setTimeout(420_000);
  startedAt = sql("select now()");
  cleanup(); // leftovers of a crashed earlier run
  fs.mkdirSync(SCREENSHOTS_23, { recursive: true });
  peopleOps = peopleOpsId();
  wsX = createWorkspace(`QA22 EA23 X ${RUN}`);
  wsY = createWorkspace(`QA22 EA23 Y ${RUN}`);
  foreign = createForeignOrg();

  const make = async (key: string, roles: string[], workspaceId?: string, name?: string) => {
    users.set(key, await createUser({ label: key, roles, workspaceId, name }));
  };
  // One user per Workspace role in People Ops, and the Organization-level personas.
  await make("wsAdmin", ["workspace_admin"], peopleOps);
  await make("developer", ["developer"], peopleOps);
  await make("builder", ["builder"], peopleOps);
  await make("ke", ["knowledge_editor"], peopleOps);
  await make("reviewer", ["reviewer"], peopleOps);
  await make("viewer", ["viewer"], peopleOps);
  await make("orgAdmin", ["org_admin"]); // no Workspace role anywhere, not a member of X or Y
  await make("orgAdminReviewer", ["org_admin", "reviewer"], peopleOps);
  await make("orgOwner", ["org_owner"]);
  await make("adminSelf", ["org_admin", "workspace_admin"], peopleOps); // like Linh Tran
  // Targets of role changes.
  await make("xAdmin", ["workspace_admin"], wsX);
  await make("yOnly", ["viewer"], wsY);
  await make("existing", ["viewer"], wsX);
  await make("roleTarget", ["viewer"], peopleOps);
  await make("uiTarget", ["viewer"], peopleOps, `Nguyễn Thị Hồng Ánh ${RUN}`);
  // AC4: U is a Viewer in X and in Y (X first, so X is the default Workspace).
  await make("u", ["viewer"], wsX, `Lê Văn Ánh ${RUN}`);
  addMember(wsY, user("u"), "viewer");
  // NFR: a Builder in X whose role is lowered while the session is open.
  await make("u2", ["builder"], wsX);
  // Round 2: self-lockout rule (A8): a Workspace Admin without Org role, and one with an Org role.
  await make("lockAdmin", ["workspace_admin"], wsX);
  await make("lockBoth", ["org_admin", "workspace_admin"], wsX);
});

test.afterAll(() => {
  cleanup();
  // Nothing created by this run may stay in the demo Organization (a leftover broke the seed test once).
  expect(
    rows(
      `select email from users where org_id = '${DEMO_ORG}' and created_at > '${startedAt}'::timestamptz`,
    ),
    "users left behind",
  ).toEqual([]);
  expect(
    rows(
      `select name from workspaces where org_id = '${DEMO_ORG}' and created_at > '${startedAt}'::timestamptz`,
    ),
    "workspaces left behind",
  ).toEqual([]);
  expect(rows(`select id from organizations where name like 'QA EA-22 %'`)).toEqual([]);
});

// ---------------------------------------------------------------------------------------------
// AC1 matrix and declarations
// ---------------------------------------------------------------------------------------------

test("AC1: every members and role route needs a session (401 unauthenticated), whatever the method", async () => {
  const anonymous = new ApiSession();
  await anonymous.ensureCsrf();
  const someone = randomUUID();
  const calls: [string, string, unknown?][] = [
    ["GET", `/api/workspaces/${peopleOps}`],
    ["GET", `/api/workspaces/${peopleOps}/members`],
    [
      "POST",
      `/api/workspaces/${peopleOps}/members`,
      { email: "a@example.invalid", role: "viewer" },
    ],
    ["PUT", `/api/workspaces/${peopleOps}/members/${someone}`, { role: "viewer" }],
    ["DELETE", `/api/workspaces/${peopleOps}/members/${someone}`],
    ["PUT", `/api/organization/members/${someone}/org-role`, { org_role: "org_admin" }],
  ];
  for (const [method, apiPath, json] of calls) {
    const result = await anonymous.send(method, apiPath, json === undefined ? {} : { json });
    expectDetail(result, 401, "unauthenticated");
  }
  // A forged identity header does not replace the session.
  const forged = await anonymous.send("GET", `/api/workspaces/${peopleOps}`, {
    headers: { "x-role": "org_owner", "x-permissions": "members.manage" },
  });
  expectDetail(forged, 401, "unauthenticated");
});

test("AC1 TC-1-2: the documented matrix in docs/architecture/rbac.md has the 8 rows and cells of the Members artboard", () => {
  const file = path.join(ROOT, "docs", "architecture", "rbac.md");
  expect(fs.existsSync(file), "docs/architecture/rbac.md exists").toBe(true);
  const text = fs.readFileSync(file, "utf8");
  const start = text.indexOf("<!-- rbac-matrix:start -->");
  const end = text.indexOf("<!-- rbac-matrix:end -->");
  expect(start, "rbac-matrix:start marker").toBeGreaterThanOrEqual(0);
  expect(end, "rbac-matrix:end marker").toBeGreaterThan(start);
  const table = text
    .slice(start, end)
    .split(/\r?\n/)
    .filter((line) => line.trim().startsWith("|"))
    .map((line) =>
      line
        .trim()
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((cell) => cell.trim()),
    );
  expect(table[0]).toEqual(["Permission", "Code", ...MATRIX_COLUMNS]);
  const matrixRows = table.slice(2); // after the header and the |---| line
  expect(matrixRows.map((cells) => (cells[1] ?? "").replaceAll("`", ""))).toEqual(
    UI_MATRIX.map((row) => row.code),
  );
  for (const [index, expected] of UI_MATRIX.entries()) {
    const cells = matrixRows[index] ?? [];
    expect(cells.slice(2), expected.code).toEqual(expected.yes.map((yes) => (yes ? "Yes" : "—")));
  }
  expect(text).toContain("<!-- rbac-grants:start -->");
});

// ---------------------------------------------------------------------------------------------
// AC2 sensitive permissions, AC3 collection access
// ---------------------------------------------------------------------------------------------

const PERSONAS: [key: string, orgRole: string | null, role: string | null][] = [
  ["wsAdmin", null, "workspace_admin"],
  ["developer", null, "developer"],
  ["builder", null, "builder"],
  ["ke", null, "knowledge_editor"],
  ["reviewer", null, "reviewer"],
  ["viewer", null, "viewer"],
  ["orgAdmin", "org_admin", null],
  ["orgAdminReviewer", "org_admin", "reviewer"],
  ["orgOwner", "org_owner", null],
];

function holders(permission: string, infos: Map<string, WorkspaceInfo>): string[] {
  return PERSONAS.map(([key]) => key).filter((key) =>
    infos.get(key)?.permissions.includes(permission),
  );
}

async function allInfos(): Promise<Map<string, WorkspaceInfo>> {
  const infos = new Map<string, WorkspaceInfo>();
  for (const [key] of PERSONAS) infos.set(key, await infoOf(key));
  return infos;
}

test("AC2: only Reviewers read conversations (Org Admin and Org Owner never), only Developers and Admins hold connectors, only Builders and Admins publish", async () => {
  for (const [key, orgRole, role] of PERSONAS) {
    const info = await infoOf(key);
    expect(info, key).toMatchObject({ id: peopleOps, name: "People Ops", role, org_role: orgRole });
    expect(info.permissions, `${key}: permissions`).toEqual(permissionsFor(orgRole, role));
    expect(info.permissions, `${key}: sorted`).toEqual([...info.permissions].sort());
  }
  const infos = await allInfos();
  expect(holders("conversations.read", infos), "conversations.read").toEqual([
    "reviewer",
    "orgAdminReviewer",
  ]);
  expect(holders("connectors.manage", infos), "connectors.manage").toEqual([
    "wsAdmin",
    "developer",
    "orgAdmin",
    "orgAdminReviewer",
    "orgOwner",
  ]);
  expect(holders("assistants.publish", infos), "assistants.publish").toEqual([
    "wsAdmin",
    "builder",
    "orgAdmin",
    "orgAdminReviewer",
    "orgOwner",
  ]);
  // Org Admin with Reviewer holds everything: the workspace Admin set plus conversations.read.
  const all = infos.get("orgAdminReviewer")?.permissions ?? [];
  expect(all).toEqual(expect.arrayContaining(["conversations.read", "connectors.manage"]));
  // A Platform role never shows in a Workspace answer (no platform user exists here): no `platform.*`.
  for (const [key] of PERSONAS) {
    expect((await infoOf(key)).permissions.some((code) => code.startsWith("platform."))).toBe(
      false,
    );
  }
});

test("AC2 TC-2-2: the permissions are read from the session; a forged role header or query changes nothing", async () => {
  const viewer = await api("viewer");
  const plain = body<WorkspaceInfo>(await viewer.workspace(peopleOps));
  const forgedHeaders = await viewer.send("GET", `/api/workspaces/${peopleOps}`, {
    headers: {
      "x-role": "workspace_admin",
      "x-org-role": "org_owner",
      "x-permissions": "conversations.read,members.manage",
      "x-org-id": foreign.orgId,
    },
  });
  expect(forgedHeaders.status).toBe(200);
  expect(body<WorkspaceInfo>(forgedHeaders)).toEqual(plain);
  const forgedQuery = await viewer.send(
    "GET",
    `/api/workspaces/${peopleOps}?role=workspace_admin&org_role=org_owner&org_id=${foreign.orgId}&permissions=members.manage`,
  );
  expect(forgedQuery.status).toBe(200);
  expect(body<WorkspaceInfo>(forgedQuery)).toEqual(plain);
  // The same forged headers do not open a write route to a Viewer.
  const write = await viewer.send(
    "PUT",
    `/api/workspaces/${peopleOps}/members/${user("roleTarget").id}`,
    {
      json: { role: "builder" },
      headers: { "x-role": "workspace_admin", "x-permissions": "members.manage" },
    },
  );
  expectDetail(write, 403, "forbidden");
  expect(wsRoleOf(peopleOps, user("roleTarget").id)).toBe("viewer");
});

test("AC3: only a Workspace Admin (and Org Owner/Org Admin, who act as Admin) may change who can read a collection", async () => {
  const infos = await allInfos();
  expect(holders("collections.access.manage", infos)).toEqual([
    "wsAdmin",
    "orgAdmin",
    "orgAdminReviewer",
    "orgOwner",
  ]);
  for (const key of ["developer", "builder", "ke", "reviewer", "viewer"]) {
    expect(infos.get(key)?.permissions, key).not.toContain("collections.access.manage");
  }
  // The same four manage members: managing roles stays with the Admin set.
  expect(holders("members.manage", infos)).toEqual(holders("collections.access.manage", infos));
  // Everybody in the Workspace may view the member list (read-only roles included).
  for (const [key] of PERSONAS) expect(infos.get(key)?.permissions, key).toContain("members.view");
});

// ---------------------------------------------------------------------------------------------
// AC4 assigning roles
// ---------------------------------------------------------------------------------------------

test("AC4: an Org Admin assigns Builder in workspace X; the user sees Assistants in X but not in Y", async ({
  browser,
}) => {
  const u = user("u");
  const admin = await api("orgAdmin");

  // The Org Admin is a member of neither X nor Y, yet sees every Workspace of the Organization.
  const session = body<SessionBody>(await admin.session());
  expect(session.org_role).toBe("org_admin");
  const allIds = rows(`select id from workspaces where org_id = '${DEMO_ORG}'`).sort();
  expect(session.workspaces.map((workspace) => workspace.id).sort()).toEqual(allIds);
  expect(session.workspaces.every((workspace) => workspace.role === null)).toBe(true);
  expect(session.default_workspace_id).toBe(
    rows(
      `select id from workspaces where org_id = '${DEMO_ORG}' order by created_at, id limit 1`,
    )[0],
  );
  const xAsAdmin = body<WorkspaceInfo>(await admin.workspace(wsX));
  expect(xAsAdmin).toMatchObject({ id: wsX, role: null, org_role: "org_admin" });

  expect(wsRoleOf(wsX, u.id)).toBe("viewer");
  const put = await admin.send("PUT", `/api/workspaces/${wsX}/members/${u.id}`, {
    json: { role: "builder" },
  });
  expect(put.status, put.text).toBe(200);
  expect(body<MemberItem>(put)).toMatchObject({ user_id: u.id, role: "builder", org_role: null });
  expect(wsRoleOf(wsX, u.id)).toBe("builder");
  expect(wsRoleOf(wsY, u.id)).toBe("viewer");

  // U signs in through the UI after the change.
  await withPage(browser, undefined, async (page) => {
    const seen = watch(page);
    await signInUi(page, u.email, u.password);
    await expect(page).toHaveURL(url(wsX)); // earliest membership
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar.getByRole("link", { name: "Assistants", exact: true })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Knowledge", exact: true })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Conversations", exact: true })).toHaveCount(0);
    await sidebar.getByRole("link", { name: "Assistants", exact: true }).click();
    await expect(page).toHaveURL(url(wsX, "assistants"));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Assistants");
    await expect(page.getByTestId("user-menu")).toContainText("Builder");

    // Switch to Y: the area is kept in the URL, but Y only gives the Viewer role.
    await page.getByTestId("workspace-switcher").click();
    await page.getByRole("menuitemradio", { name: `QA22 EA23 Y ${RUN}` }).click();
    await expect(page).toHaveURL(url(wsY, "assistants"));
    const forbidden = page.getByTestId("area-forbidden");
    await expect(forbidden).toBeVisible();
    await expect(forbidden.getByRole("heading", { level: 1 })).toHaveText("No access");
    await expect(forbidden).toContainText(FORBIDDEN_TEXT);
    await expect(sidebar).toBeVisible(); // the forbidden page is inside the shell
    await expect(sidebar.getByRole("link", { name: "Assistants", exact: true })).toHaveCount(0);
    await expect(sidebar.getByRole("link", { name: "Knowledge", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("user-menu")).toContainText("Viewer");
    await expect(sidebar.getByRole("link", { name: "Dashboard", exact: true })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Members & roles", exact: true })).toBeVisible();

    // Opening the hidden area of Y by URL shows the same page; X still works.
    await page.goto(`/w/${wsY}/assistants`);
    await expect(page.getByTestId("area-forbidden")).toBeVisible();
    await page.goto(`/w/${wsX}/assistants`);
    await expect(page.getByTestId("area-page")).toHaveAttribute("data-area", "assistants");

    expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
    expect(withoutExpected401(seen.problems)).toEqual([]);
  });

  // The API agrees: Assistants permission in X, none in Y.
  const uApi = await api("u");
  const inX = body<WorkspaceInfo>(await uApi.workspace(wsX));
  const inY = body<WorkspaceInfo>(await uApi.workspace(wsY));
  expect(inX.permissions).toContain("assistants.manage");
  expect(inY.permissions).not.toContain("assistants.manage");
  expect(inY.role).toBe("viewer");
});

test("AC4 TC-4-2: the members API: list shape and order, invite, validation, role change, remove", async () => {
  const admin = await api("orgAdmin");
  const membersPath = `/api/workspaces/${peopleOps}/members`;

  const list = await admin.send("GET", membersPath);
  expect(list.status).toBe(200);
  const members = body<{ members: MemberItem[] }>(list).members;
  expect(Object.keys(body<object>(list))).toEqual(["members"]);
  for (const member of members) {
    expect(Object.keys(member).sort(), member.user_id).toEqual(MEMBER_KEYS);
    expect(member.last_active_at === null || !Number.isNaN(Date.parse(member.last_active_at))).toBe(
      true,
    );
  }
  // Membership order: the users created in this run appear in the order they joined People Ops.
  const created = ["wsAdmin", "developer", "builder", "ke", "reviewer", "viewer"].map(
    (key) => user(key).id,
  );
  const ids = members.map((member) => member.user_id);
  expect(ids.filter((id) => created.includes(id))).toEqual(created);
  expect(members.find((member) => member.user_id === user("wsAdmin").id)).toMatchObject({
    role: "workspace_admin",
    org_role: null,
    email: user("wsAdmin").email,
  });
  expect(members.find((member) => member.user_id === user("adminSelf").id)?.org_role).toBe(
    "org_admin",
  );
  // Nobody outside People Ops is listed.
  expect(ids).not.toContain(user("yOnly").id);
  expect(ids).not.toContain(user("orgAdmin").id);

  // Validation: 422 invalid_request, and the answer never echoes the input.
  const inviteEmail = `qa22.ea23-bad.${RUN}@mekongdevworks.example`;
  const bad: [string, unknown][] = [
    ["bad email", { email: "not-an-email", role: "viewer" }],
    ["no email", { role: "viewer" }],
    ["Member role is not assignable here", { email: inviteEmail, role: "member" }],
    ["Org role in the Workspace body", { email: inviteEmail, role: "org_owner" }],
    ["unknown role", { email: inviteEmail, role: "superuser" }],
    ["display-cased role", { email: inviteEmail, role: "Builder" }],
    ["null role", { email: inviteEmail, role: null }],
    ["extra org_role", { email: inviteEmail, role: "viewer", org_role: "org_owner" }],
    ["extra user_id", { email: inviteEmail, role: "viewer", user_id: randomUUID() }],
    ["empty name", { email: inviteEmail, role: "viewer", display_name: "" }],
    ["201-character name", { email: inviteEmail, role: "viewer", display_name: "Ơ".repeat(201) }],
    ["number as email", { email: 5, role: "viewer" }],
  ];
  for (const [label, json] of bad) {
    const result = await admin.send("POST", membersPath, { json });
    expectDetail(result, 422, "invalid_request");
    expect(result.text, `${label}: input is not echoed`).not.toContain("superuser");
    expect(result.text, `${label}: input is not echoed`).not.toContain(inviteEmail);
  }
  expect(
    rows(`select id from users where org_id = '${DEMO_ORG}' and email = '${inviteEmail}'`),
  ).toEqual([]);

  // A valid invite: 201 member item, nothing about the set-password token, an unused token exists.
  const newEmail = `qa22.ea23-invitee.${RUN}@mekongdevworks.example`;
  const name = `Trần Thị Bích Ngọc ${RUN}`;
  const created201 = await admin.send("POST", membersPath, {
    json: { email: newEmail.toUpperCase(), display_name: name, role: "reviewer" },
  });
  expect(created201.status, created201.text).toBe(201);
  const invitee = body<MemberItem>(created201);
  expect(Object.keys(invitee).sort()).toEqual(MEMBER_KEYS);
  expect(invitee).toMatchObject({
    email: newEmail,
    display_name: name,
    role: "reviewer",
    org_role: null,
    last_active_at: null,
  });
  expect(created201.text).not.toMatch(/token|link|password|secret/i);
  expect(
    Number(
      sql(
        `select count(*) from set_password_tokens where org_id = '${DEMO_ORG}' and user_id = '${invitee.user_id}'`,
      ),
    ),
  ).toBeGreaterThanOrEqual(1);
  expect(wsRoleOf(peopleOps, invitee.user_id)).toBe("reviewer");
  // The e-mail address is unique per Organization, case-insensitively.
  expectDetail(
    await admin.send("POST", membersPath, { json: { email: newEmail, role: "viewer" } }),
    409,
    "already_member",
  );
  // An existing Organization user is added to this Workspace; the given name is ignored.
  const existing = user("existing");
  const added = await admin.send("POST", membersPath, {
    json: { email: existing.email, display_name: "Hacked Name", role: "viewer" },
  });
  expect(added.status, added.text).toBe(201);
  expect(body<MemberItem>(added)).toMatchObject({
    user_id: existing.id,
    display_name: existing.name,
  });
  expect(wsRoleOf(wsX, existing.id)).toBe("viewer"); // the X membership is untouched
  expect(wsRoleOf(peopleOps, existing.id)).toBe("viewer");

  // The invite does not leak the email or the name into the API logs (D52).
  const logs = apiLogsSince(300);
  expect(logs).not.toContain(newEmail);
  expect(logs).not.toContain(name);

  // Role change: validation, no-op, success.
  const target = user("roleTarget").id;
  const put = `${membersPath}/${target}`;
  for (const json of [
    { role: "member" },
    { role: "org_owner" },
    { role: "Builder" },
    { role: null },
    {},
    { role: "builder", org_role: "org_owner" },
  ]) {
    expectDetail(await admin.send("PUT", put, { json }), 422, "invalid_request");
  }
  expect(wsRoleOf(peopleOps, target)).toBe("viewer");
  const before = countRoleEvents();
  const same = await admin.send("PUT", put, { json: { role: "viewer" } });
  expect(same.status, same.text).toBe(200);
  expect(countRoleEvents(), "a no-op writes no event").toBe(before);
  const changed = await admin.send("PUT", put, { json: { role: "knowledge_editor" } });
  expect(changed.status, changed.text).toBe(200);
  expect(body<MemberItem>(changed)).toMatchObject({ user_id: target, role: "knowledge_editor" });
  expect(wsRoleOf(peopleOps, target)).toBe("knowledge_editor");
  expect((await admin.send("PUT", put, { json: { role: "viewer" } })).status).toBe(200);

  // Remove: 204, gone from the list, a second remove is 404, the audit row has no new role.
  const removed = await admin.send("DELETE", `${membersPath}/${invitee.user_id}`);
  expect(removed.status).toBe(204);
  expect(wsRoleOf(peopleOps, invitee.user_id)).toBeNull();
  const after = body<{ members: MemberItem[] }>(await admin.send("GET", membersPath)).members;
  expect(after.map((member) => member.user_id)).not.toContain(invitee.user_id);
  expectDetail(await admin.send("DELETE", `${membersPath}/${invitee.user_id}`), 404, "not_found");
  expect(roleAudit([invitee.user_id]).map((row) => [row.old_value, row.new_value])).toEqual([
    [null, "reviewer"],
    ["reviewer", null],
  ]);
  // Not a UUID in the path.
  expectDetail(
    await admin.send("GET", "/api/workspaces/not-a-uuid/members"),
    422,
    "invalid_request",
  );
});

test("AC4 TC-4-3: a Workspace Admin of X cannot reach Y; targets must belong to the Workspace in the path; other Organizations see nothing", async () => {
  const xAdmin = await api("xAdmin");
  const yUser = user("yOnly");
  // Y is invisible to the Admin of X: 404, identical to a random Workspace id (no oracle).
  const random = await xAdmin.send("GET", `/api/workspaces/${randomUUID()}/members`);
  expectDetail(random, 404, "not_found");
  const onY = await xAdmin.send("GET", `/api/workspaces/${wsY}/members`);
  expectSameAnswer(onY, random, "Admin of X on Workspace Y");
  const putY = await xAdmin.send("PUT", `/api/workspaces/${wsY}/members/${yUser.id}`, {
    json: { role: "workspace_admin" },
  });
  expectDetail(putY, 404, "not_found");
  expect(wsRoleOf(wsY, yUser.id)).toBe("viewer");
  // A member of Y targeted through X's path: 404 (not a member here), role untouched.
  const viaX = await xAdmin.send("PUT", `/api/workspaces/${wsX}/members/${yUser.id}`, {
    json: { role: "workspace_admin" },
  });
  expectDetail(viaX, 404, "not_found");
  expect(wsRoleOf(wsY, yUser.id)).toBe("viewer");
  expect(wsRoleOf(wsX, yUser.id)).toBeNull();
  expectDetail(
    await xAdmin.send("DELETE", `/api/workspaces/${wsX}/members/${yUser.id}`),
    404,
    "not_found",
  );
  expect(wsRoleOf(wsY, yUser.id)).toBe("viewer");

  // The owner of another Organization: People Ops, its members and its users do not exist for them.
  const owner = await foreignOwnerApi();
  const reference = await owner.send("GET", `/api/workspaces/${randomUUID()}/members`);
  expectDetail(reference, 404, "not_found");
  expectSameAnswer(
    await owner.send("GET", `/api/workspaces/${peopleOps}/members`),
    reference,
    "foreign list",
  );
  expectSameAnswer(
    await owner.workspace(peopleOps),
    await owner.workspace(randomUUID()),
    "foreign workspace",
  );
  const victim = user("roleTarget").id;
  expectDetail(
    await owner.send("PUT", `/api/workspaces/${peopleOps}/members/${victim}`, {
      json: { role: "builder" },
    }),
    404,
    "not_found",
  );
  expectDetail(
    await owner.send("POST", `/api/workspaces/${peopleOps}/members`, {
      json: { email: `qa22.ea23-x.${RUN}@mekongdevworks.example`, role: "viewer" },
    }),
    404,
    "not_found",
  );
  // Their own Workspace works, and a user of the other Organization is 404 there.
  expect((await owner.send("GET", `/api/workspaces/${foreign.workspaceId}/members`)).status).toBe(
    200,
  );
  expectDetail(
    await owner.send("PUT", `/api/workspaces/${foreign.workspaceId}/members/${victim}`, {
      json: { role: "builder" },
    }),
    404,
    "not_found",
  );
  expectDetail(
    await owner.send("PUT", `/api/organization/members/${victim}/org-role`, {
      json: { org_role: "org_owner" },
    }),
    404,
    "not_found",
  );
  expect(wsRoleOf(peopleOps, victim)).toBe("viewer");
  expect(orgRoleOf(victim)).toBeNull();
});

// ---------------------------------------------------------------------------------------------
// AC5 no self-escalation
// ---------------------------------------------------------------------------------------------

test("AC5: nobody can raise themselves to Org Owner or Workspace Admin: 403, nothing changes, nothing audited", async () => {
  const wsAdmin = user("wsAdmin");
  const orgAdmin = user("orgAdmin");
  const builder = user("builder");
  const events = countRoleEvents();

  // Workspace Admin (no Org role) -> Org Owner for self and for somebody else.
  const asWsAdmin = await api("wsAdmin");
  for (const target of [wsAdmin.id, user("roleTarget").id]) {
    const result = await asWsAdmin.send("PUT", `/api/organization/members/${target}/org-role`, {
      json: { org_role: "org_owner" },
    });
    expectDetail(result, 403, "forbidden");
  }
  expect(orgRoleOf(wsAdmin.id)).toBeNull();
  expect(orgRoleOf(user("roleTarget").id)).toBeNull();

  // Org Admin -> Org Owner (self): only Org Owners change Organization roles.
  const asOrgAdmin = await api("orgAdmin");
  expectDetail(
    await asOrgAdmin.send("PUT", `/api/organization/members/${orgAdmin.id}/org-role`, {
      json: { org_role: "org_owner" },
    }),
    403,
    "forbidden",
  );
  expectDetail(
    await asOrgAdmin.send("PUT", `/api/organization/members/${user("roleTarget").id}/org-role`, {
      json: { org_role: "org_admin" },
    }),
    403,
    "forbidden",
  );
  expect(orgRoleOf(orgAdmin.id)).toBe("org_admin");

  // Builder -> Workspace Admin (self), and a Builder editing a colleague.
  const asBuilder = await api("builder");
  expectDetail(
    await asBuilder.send("PUT", `/api/workspaces/${peopleOps}/members/${builder.id}`, {
      json: { role: "workspace_admin" },
    }),
    403,
    "forbidden",
  );
  expectDetail(
    await asBuilder.send("PUT", `/api/workspaces/${peopleOps}/members/${user("viewer").id}`, {
      json: { role: "builder" },
    }),
    403,
    "forbidden",
  );
  expectDetail(
    await asBuilder.send("POST", `/api/workspaces/${peopleOps}/members`, {
      json: { email: `qa22.ea23-b.${RUN}@mekongdevworks.example`, role: "viewer" },
    }),
    403,
    "forbidden",
  );
  expectDetail(
    await asBuilder.send("DELETE", `/api/workspaces/${peopleOps}/members/${user("viewer").id}`),
    403,
    "forbidden",
  );
  expect(wsRoleOf(peopleOps, builder.id)).toBe("builder");
  expect(wsRoleOf(peopleOps, user("viewer").id)).toBe("viewer");

  // Workspace Admin invites with an Org role in the body: 422, no user created, no Org role granted.
  const email = `qa22.ea23-escalate.${RUN}@mekongdevworks.example`;
  expectDetail(
    await asWsAdmin.send("POST", `/api/workspaces/${peopleOps}/members`, {
      json: { email, role: "viewer", org_role: "org_owner" },
    }),
    422,
    "invalid_request",
  );
  expectDetail(
    await asWsAdmin.send("POST", `/api/workspaces/${peopleOps}/members`, {
      json: { email, role: "org_owner" },
    }),
    422,
    "invalid_request",
  );
  expect(rows(`select id from users where org_id = '${DEMO_ORG}' and email = '${email}'`)).toEqual(
    [],
  );

  expect(countRoleEvents(), "refused calls write no audit event").toBe(events);
  expect(
    Number(
      sql(
        `select count(*) from audit_events where org_id = '${DEMO_ORG}' and action = 'member.org_role_changed' and target_id::text in ('${wsAdmin.id}', '${orgAdmin.id}')`,
      ),
    ),
    "no member.org_role_changed row for the refused targets except the CLI creation of the Org Admin",
  ).toBe(1);
});

test("AC5 TC-5-2: the last Org Owner of an Organization cannot be demoted (409 last_org_owner)", async () => {
  const owner = await foreignOwnerApi();
  const me = foreign.ownerId;
  expect(orgRoleOfIn(foreign.orgId, me)).toBe("org_owner");
  for (const org_role of [null, "org_admin"]) {
    expectDetail(
      await owner.send("PUT", `/api/organization/members/${me}/org-role`, { json: { org_role } }),
      409,
      "last_org_owner",
    );
  }
  expect(orgRoleOfIn(foreign.orgId, me)).toBe("org_owner");
  // Setting the role it already has is a no-op, not a refusal.
  const same = await owner.send("PUT", `/api/organization/members/${me}/org-role`, {
    json: { org_role: "org_owner" },
  });
  expect(same.status, same.text).toBe(200);
  expect(body<{ user_id: string; org_role: string }>(same)).toEqual({
    user_id: me,
    org_role: "org_owner",
  });
  // An invalid value is a 422, never a role.
  for (const org_role of ["member", "workspace_admin", "ORG_OWNER", 7]) {
    expectDetail(
      await owner.send("PUT", `/api/organization/members/${me}/org-role`, { json: { org_role } }),
      422,
      "invalid_request",
    );
  }
  expectDetail(
    await owner.send("PUT", `/api/organization/members/${randomUUID()}/org-role`, {
      json: { org_role: "org_admin" },
    }),
    404,
    "not_found",
  );
});

function orgRoleOfIn(orgId: string, userId: string): string | null {
  const out = rows(
    `select coalesce(org_role, '') from memberships where org_id = '${orgId}' and user_id = '${userId}'`,
  )[0];
  return out === undefined || out === "" ? null : out;
}

// ---------------------------------------------------------------------------------------------
// AC6 audit
// ---------------------------------------------------------------------------------------------

test("AC6: every role change is audited (who, for whom, Workspace, old -> new), also an Admin assigning themselves Reviewer", async ({
  browser,
}) => {
  const target = user("uiTarget");
  const self = user("adminSelf");
  const admin = user("orgAdmin");
  const adminApi = await api("orgAdmin");
  const selfApi = await api("adminSelf");

  // 1. Org Admin changes a Viewer to Builder with the select of the table.
  await withSession(browser, adminApi, async (page) => {
    const seen = watch(page);
    await openMembers(page, peopleOps);
    await chooseOption(roleSelect(page, target.name), "Builder");
    await expect(page.getByTestId("members-status")).toHaveText("Role updated.");
    await expect.poll(() => selectedLabel(roleSelect(page, target.name))).toBe("Builder");
    expect(seen.problems).toEqual([]);
  });
  expect(wsRoleOf(peopleOps, target.id)).toBe("builder");

  // 2. A Workspace Admin who is also Org Admin assigns themselves Reviewer (their own row is editable).
  await withSession(browser, selfApi, async (page) => {
    await openMembers(page, peopleOps);
    await expect(page.getByTestId("user-menu")).toContainText("Workspace Admin");
    const own = roleSelect(page, self.name);
    await expect(own).toBeEnabled();
    await chooseOption(own, "Reviewer");
    await expect(page.getByTestId("members-status")).toHaveText("Role updated.");
    // The session is refreshed: the role line and the Sidebar follow at once (Reviewer areas appear).
    await expect(page.getByTestId("user-menu")).toContainText("Reviewer");
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar.getByRole("link", { name: "Conversations", exact: true })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Unanswered", exact: true })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Organization", exact: true })).toBeVisible();
  });
  expect(wsRoleOf(peopleOps, self.id)).toBe("reviewer");
  expect(orgRoleOf(self.id)).toBe("org_admin"); // the Org role is kept (footnote)
  const afterSelf = body<WorkspaceInfo>(await selfApi.workspace(peopleOps));
  expect(afterSelf.permissions).toEqual(permissionsFor("org_admin", "reviewer"));
  expect(afterSelf.permissions).toContain("conversations.read");
  expect(afterSelf.permissions).toContain("members.manage");

  // 3. Org Admin invites a new e-mail address.
  const invitedEmail = `qa22.ea23-audit.${RUN}@mekongdevworks.example`;
  const invited = await adminApi.send("POST", `/api/workspaces/${peopleOps}/members`, {
    json: { email: invitedEmail, role: "viewer" },
  });
  expect(invited.status, invited.text).toBe(201);
  const invitedId = body<MemberItem>(invited).user_id;

  // The audit rows, exactly as in the contract (events made by the CLI are filtered out here).
  expect(roleAudit([target.id, self.id, invitedId])).toEqual([
    {
      actor: `user:${admin.id}`,
      action: "member.workspace_role_changed",
      target_type: "user",
      target_id: target.id,
      workspace_id: peopleOps,
      old_value: "viewer",
      new_value: "builder",
    },
    {
      actor: `user:${self.id}`,
      action: "member.workspace_role_changed",
      target_type: "user",
      target_id: self.id,
      workspace_id: peopleOps,
      old_value: "workspace_admin",
      new_value: "reviewer",
    },
    {
      actor: `user:${admin.id}`,
      action: "member.workspace_role_changed",
      target_type: "user",
      target_id: invitedId,
      workspace_id: peopleOps,
      old_value: null,
      new_value: "viewer",
    },
  ]);
  expect(
    Number(
      sql(
        `select count(*) from audit_events where org_id = '${DEMO_ORG}' and action = 'user.invited' and target_id::text = '${invitedId}'`,
      ),
    ),
  ).toBe(1);
});

test("AC6 TC-6-2: an Org Owner's Organization-role change is audited with no Workspace; no-ops and refusals write no event", async () => {
  const owner = await api("orgOwner");
  const target = user("roleTarget").id;
  const before = countRoleEvents();
  const up = await owner.send("PUT", `/api/organization/members/${target}/org-role`, {
    json: { org_role: "org_admin" },
  });
  expect(up.status, up.text).toBe(200);
  expect(body<{ user_id: string; org_role: string }>(up)).toEqual({
    user_id: target,
    org_role: "org_admin",
  });
  expect(orgRoleOf(target)).toBe("org_admin");
  const same = await owner.send("PUT", `/api/organization/members/${target}/org-role`, {
    json: { org_role: "org_admin" },
  });
  expect(same.status).toBe(200);
  expect(countRoleEvents(), "one event for the change, none for the repeat").toBe(before + 1);
  // The new Org Admin acts at once, in every Workspace, without a Workspace membership of their own.
  const info = body<WorkspaceInfo>(await (await api("roleTarget")).workspace(wsY));
  expect(info.org_role).toBe("org_admin");
  expect(info.permissions).toContain("members.manage");

  const down = await owner.send("PUT", `/api/organization/members/${target}/org-role`, {
    json: { org_role: null },
  });
  expect(down.status, down.text).toBe(200);
  expect(body<{ org_role: string | null }>(down).org_role).toBeNull();
  expect(orgRoleOf(target)).toBeNull();
  expect(roleAudit([target]).filter((row) => row.action === "member.org_role_changed")).toEqual([
    {
      actor: `user:${user("orgOwner").id}`,
      action: "member.org_role_changed",
      target_type: "user",
      target_id: target,
      workspace_id: null,
      old_value: null,
      new_value: "org_admin",
    },
    {
      actor: `user:${user("orgOwner").id}`,
      action: "member.org_role_changed",
      target_type: "user",
      target_id: target,
      workspace_id: null,
      old_value: "org_admin",
      new_value: null,
    },
  ]);
  // Values are role codes, never names or e-mail addresses (D52).
  for (const row of roleAudit([target, user("uiTarget").id, user("adminSelf").id], "any")) {
    expect(row.old_value ?? "").toMatch(/^[a-z_]{0,40}$/);
    expect(row.new_value ?? "").toMatch(/^[a-z_]{0,40}$/);
  }
});

test("AC6 TC-6-3: roles given by the Platform Operator CLI are audited too (actor platform-operator, old none)", () => {
  const events = roleAudit(
    [user("wsAdmin").id, user("orgAdmin").id, user("orgAdminReviewer").id],
    "operator",
  );
  expect(events).toEqual(
    expect.arrayContaining([
      {
        actor: "platform-operator",
        action: "member.workspace_role_changed",
        target_type: "user",
        target_id: user("wsAdmin").id,
        workspace_id: peopleOps,
        old_value: null,
        new_value: "workspace_admin",
      },
      {
        actor: "platform-operator",
        action: "member.org_role_changed",
        target_type: "user",
        target_id: user("orgAdmin").id,
        workspace_id: null,
        old_value: null,
        new_value: "org_admin",
      },
      {
        actor: "platform-operator",
        action: "member.org_role_changed",
        target_type: "user",
        target_id: user("orgAdminReviewer").id,
        workspace_id: null,
        old_value: null,
        new_value: "org_admin",
      },
      {
        actor: "platform-operator",
        action: "member.workspace_role_changed",
        target_type: "user",
        target_id: user("orgAdminReviewer").id,
        workspace_id: peopleOps,
        old_value: null,
        new_value: "reviewer",
      },
    ]),
  );
  // Adding U to Workspace Y with `workspace add-member` was audited with Y as the Workspace.
  expect(roleAudit([user("u").id], "operator")).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ workspace_id: wsY, old_value: null, new_value: "viewer" }),
    ]),
  );
});

// ---------------------------------------------------------------------------------------------
// AC7 the Members screen
// ---------------------------------------------------------------------------------------------

test("AC7: the Members screen has the header, table, role matrix, highlight and footnote of the Members artboard", async ({
  browser,
}) => {
  const admin = await api("orgAdmin");
  await withSession(browser, admin, async (page) => {
    const seen = watch(page);
    await openMembers(page, peopleOps);
    const main = page.getByTestId("members-page");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText("Members & roles");
    await expect(main).toContainText(
      "People Ops workspace. A person can hold a different role in each workspace.",
    );
    await expect(page.getByText(/Viewing as/i)).toHaveCount(0);
    await expect(page.getByTestId("invite-member")).toBeVisible();
    await expect(page.getByRole("button", { name: "Invite member", exact: true })).toBeVisible();

    // Table
    const table = page.getByTestId("members-table");
    await expect(table).toHaveAccessibleName("Members");
    const headers = (await table.getByRole("columnheader").allTextContents()).map((text) =>
      text.trim(),
    );
    expect(headers).toEqual(["Member", "Role in People Ops", "Last active"]);
    const rowsLocator = page.getByTestId("member-row");
    const seeded = ["Linh Tran", "Minh Pham", "Thao Nguyen", "Quang Le", "Hà Vũ", "Son Hoang"];
    for (const [index, name] of seeded.entries()) {
      await expect(rowsLocator.nth(index), name).toContainText(name);
    }
    const linh = rowsLocator.nth(0);
    await expect(linh).toContainText("linh.tran@");
    await expect(linh.getByTestId("member-org-role")).toHaveText("Org Admin");
    for (const index of [1, 2, 3, 4, 5]) {
      await expect(rowsLocator.nth(index).getByTestId("member-org-role")).toHaveCount(0);
    }
    // Every row has a user id, an editable role (the caller is an Org Admin) and a last-active text.
    const count = await rowsLocator.count();
    for (let index = 0; index < count; index++) {
      const row = rowsLocator.nth(index);
      await expect(row).toHaveAttribute("data-user-id", /^[0-9a-f-]{36}$/);
      await expect(row.getByTestId("member-last-active")).toHaveText(
        /^(Today|Yesterday|\d+ days ago|Never)$/,
      );
    }
    // Named selects with the six assignable roles, Vietnamese diacritics in the name.
    const ha = roleSelect(page, "Hà Vũ");
    await expect(ha).toBeVisible();
    const options = await optionLabels(ha);
    expect(options).toEqual([
      "Workspace Admin",
      "Developer",
      "Builder",
      "Knowledge Editor",
      "Reviewer",
      "Viewer",
    ]);
    await expect.poll(() => selectedLabel(roleSelect(page, "Linh Tran"))).toBe("Workspace Admin");
    // Users created by this run: the Org Admin who is also Reviewer shows the Org role line.
    const orgReviewer = memberRow(page, user("orgAdminReviewer").id);
    await expect(orgReviewer.getByTestId("member-org-role")).toHaveText("Org Admin");
    await expect(memberRow(page, user("viewer").id).getByTestId("member-org-role")).toHaveCount(0);

    // Role matrix
    await expect(
      main.getByRole("heading", { level: 2, name: "What each role can do" }),
    ).toBeVisible();
    const matrix = page.getByTestId("role-matrix");
    await expect(matrix).toHaveAccessibleName("What each role can do");
    const matrixHeaders = (await matrix.getByRole("columnheader").allTextContents()).map((text) =>
      text.trim(),
    );
    expect(matrixHeaders).toEqual(["Permission", ...MATRIX_COLUMNS]);
    const matrixRows = matrix.getByTestId("matrix-row");
    await expect(matrixRows).toHaveCount(UI_MATRIX.length);
    for (const [index, expected] of UI_MATRIX.entries()) {
      const row = matrixRows.nth(index);
      await expect(row, expected.label).toHaveAttribute("data-permission", expected.code);
      const all = row.locator("th, td");
      await expect(all, expected.label).toHaveCount(7);
      await expect(all.first()).toHaveText(expected.label);
      const sensitive = await row.getAttribute("data-sensitive");
      expect(sensitive === "true", `${expected.label}: data-sensitive=${sensitive}`).toBe(
        expected.sensitive,
      );
      for (const [column, yes] of expected.yes.entries()) {
        const cell = all.nth(column + 1);
        if (yes) {
          await expect(cell, `${expected.label} / ${MATRIX_COLUMNS[column]}`).toHaveText("Yes");
        } else {
          await expect(cell, `${expected.label} / ${MATRIX_COLUMNS[column]}`).toHaveAccessibleName(
            "No",
          );
          await expect(cell).toContainText("—");
          const hidden = await cell.evaluate((element) =>
            [...element.querySelectorAll("[aria-hidden='true']")].some((node) =>
              (node.textContent ?? "").includes("—"),
            ),
          );
          expect(hidden, "the dash is aria-hidden").toBe(true);
        }
      }
      // Highlight and bold label.
      const style = await row.evaluate((element) => {
        const first = element.querySelector("td, th") as HTMLElement;
        const weights = [first, ...first.querySelectorAll("*")].map((node) =>
          Number.parseInt(getComputedStyle(node as HTMLElement).fontWeight, 10),
        );
        return {
          row: getComputedStyle(element).backgroundColor,
          cell: getComputedStyle(first).backgroundColor,
          weight: Math.max(...weights),
        };
      });
      if (expected.sensitive) {
        expect(
          [style.row, style.cell].includes("rgb(255, 248, 240)"),
          `${expected.label}: highlighted (row ${style.row}, cell ${style.cell})`,
        ).toBe(true);
        expect(style.weight, `${expected.label}: bold label`).toBeGreaterThanOrEqual(600);
      } else {
        expect([style.row, style.cell]).not.toContain("rgb(255, 248, 240)");
        expect(style.weight, `${expected.label}: regular label`).toBeLessThan(600);
      }
    }
    await expect(page.getByTestId("role-matrix-note")).toHaveText(MATRIX_NOTE);
    // No Chat row, no Member column (EA-89).
    await expect(matrix.getByText(/Chat/)).toHaveCount(0);
    await expect(matrix.getByRole("columnheader", { name: "Member", exact: true })).toHaveCount(0);
    await expect(
      table.getByRole("columnheader", { name: /Knowledge groups|External user ID/ }),
    ).toHaveCount(0);

    await page.screenshot({
      path: path.join(SCREENSHOTS_23, "ac7-members-org-admin.png"),
      fullPage: true,
    });
    expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
    expect(seen.problems).toEqual([]);
  });
});

test("AC7 TC-7-2: a Viewer can only view: no Invite button, no selects, roles as text, the matrix is visible, writes are refused", async ({
  browser,
}) => {
  const viewer = user("viewer");
  const viewerApi = await api("viewer");
  await withSession(browser, viewerApi, async (page) => {
    const seen = watch(page);
    await openMembers(page, peopleOps);
    await expect(page.getByTestId("invite-member")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Invite member" })).toHaveCount(0);
    await expect(page.getByTestId("members-table").getByRole("combobox")).toHaveCount(0);
    const count = await page.getByTestId("member-row").count();
    expect(count).toBeGreaterThan(5);
    await expect(page.getByTestId("member-role")).toHaveCount(count);
    await expect(memberRow(page, viewer.id).getByTestId("member-role")).toHaveText("Viewer");
    await expect(page.getByTestId("member-row").first().getByTestId("member-role")).toHaveText(
      "Workspace Admin",
    );
    await expect(page.getByTestId("role-matrix")).toBeVisible();
    await expect(page.getByTestId("matrix-row")).toHaveCount(UI_MATRIX.length);
    await expect(page.getByTestId("role-matrix-note")).toHaveText(MATRIX_NOTE);
    await expect(page.getByTestId("user-menu")).toContainText("Viewer");
    await page.screenshot({
      path: path.join(SCREENSHOTS_23, "ac7-members-viewer.png"),
      fullPage: true,
    });
    expect(seen.problems).toEqual([]);
  });
  // The API says the same, whatever the client does.
  const target = user("roleTarget").id;
  expectDetail(
    await viewerApi.send("PUT", `/api/workspaces/${peopleOps}/members/${target}`, {
      json: { role: "builder" },
    }),
    403,
    "forbidden",
  );
  expectDetail(
    await viewerApi.send("PUT", `/api/workspaces/${peopleOps}/members/${viewer.id}`, {
      json: { role: "workspace_admin" },
    }),
    403,
    "forbidden",
  );
  expectDetail(
    await viewerApi.send("POST", `/api/workspaces/${peopleOps}/members`, {
      json: { email: `qa22.ea23-v.${RUN}@mekongdevworks.example`, role: "viewer" },
    }),
    403,
    "forbidden",
  );
  expectDetail(
    await viewerApi.send("DELETE", `/api/workspaces/${peopleOps}/members/${target}`),
    403,
    "forbidden",
  );
  expect((await viewerApi.send("GET", `/api/workspaces/${peopleOps}/members`)).status).toBe(200);
  expect(wsRoleOf(peopleOps, target)).toBe("viewer");
  expect(wsRoleOf(peopleOps, viewer.id)).toBe("viewer");
});

test("AC7 TC-7-3: invite from the dialog: invalid e-mail, success with a new row, duplicate, Cancel and Escape", async ({
  browser,
}) => {
  const admin = await api("orgAdmin");
  const email = `qa22.ea23-ui-invite.${RUN}@mekongdevworks.example`;
  const name = `Đặng Thị Mỹ Linh ${RUN}`;
  await withSession(browser, admin, async (page) => {
    const seen = watch(page);
    await openMembers(page, peopleOps);
    const open = page.getByTestId("invite-member");
    await open.click();
    const dialog = page.getByRole("dialog", { name: "Invite member" });
    await expect(dialog).toBeVisible();
    const emailBox = dialog.getByRole("textbox", { name: "Email", exact: true });
    const nameBox = dialog.getByRole("textbox", { name: "Name (optional)", exact: true });
    const role = dialog.getByRole("combobox", { name: "Role", exact: true });
    await expect.poll(() => selectedLabel(role)).toBe("Viewer"); // the least privilege is the default
    expect(await optionLabels(role)).toEqual([
      "Workspace Admin",
      "Developer",
      "Builder",
      "Knowledge Editor",
      "Reviewer",
      "Viewer",
    ]);
    await expect(dialog.getByRole("button", { name: "Send invite", exact: true })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();

    // Invalid address: a field error, the dialog stays open, no user is created.
    await emailBox.fill("not-an-email");
    await dialog.getByRole("button", { name: "Send invite" }).click();
    await expect(dialog.getByRole("alert")).toHaveText("Enter a valid email address.");
    await expect(dialog).toBeVisible();
    expect(
      rows(`select id from users where org_id = '${DEMO_ORG}' and email = 'not-an-email'`),
    ).toEqual([]);

    // Valid: status message, dialog closed, the new member appears with "Never" and the chosen role.
    await emailBox.fill(email);
    await nameBox.fill(name);
    await chooseOption(role, "Reviewer");
    await dialog.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByTestId("members-status")).toHaveText(`Invitation created for ${email}.`);
    await expect(dialog).toHaveCount(0);
    const created = rows(
      `select id from users where org_id = '${DEMO_ORG}' and email = '${email}'`,
    )[0];
    expect(created, "the invited user exists").toBeTruthy();
    const row = memberRow(page, created as string);
    await expect(row).toContainText(name);
    await expect(row).toContainText(email);
    await expect(row.getByTestId("member-last-active")).toHaveText("Never");
    await expect.poll(() => selectedLabel(roleSelect(page, name))).toBe("Reviewer");
    expect(wsRoleOf(peopleOps, created as string)).toBe("reviewer");
    // No token, link or password is shown to the admin.
    await expect(page.locator("body")).not.toContainText(/set-password|token=|temporary password/i);

    // The same address again (different letter case): 409 message inside the dialog.
    await open.click();
    await dialog.getByRole("textbox", { name: "Email", exact: true }).fill(email.toUpperCase());
    await dialog.getByRole("button", { name: "Send invite" }).click();
    await expect(dialog.getByRole("alert")).toHaveText(
      "This person is already a member of this workspace.",
    );
    // Cancel closes and returns the focus to the button that opened the dialog.
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(open).toBeFocused();
    // Escape does the same; reopening starts empty.
    await open.click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("textbox", { name: "Email", exact: true })).toHaveValue("");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(open).toBeFocused();
    expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
    // The two refusals above are the only 4xx answers.
    expect(
      seen.problems.filter((problem) => !/^http (409|422):|status of (409|422)/.test(problem)),
    ).toEqual([]);
  });
  const logs = apiLogsSince(300);
  expect(logs).not.toContain(email);
  expect(logs).not.toContain(name);
});

test("AC7 TC-7-4: the Sidebar shows only what each role can use; empty groups are absent; hidden areas show No access", async ({
  browser,
}) => {
  for (const [key, areas] of Object.entries(AREAS_BY_PERSONA)) {
    await withSession(browser, await api(key), async (page) => {
      const seen = watch(page);
      await page.goto(`/w/${peopleOps}/dashboard`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
      const sidebar = page.getByTestId("sidebar");
      const visible = visibleNav(areas);
      for (const { group, items } of visibleNav(ALL_AREAS)) {
        const shown = visible.some((entry) => entry.group === group);
        await expect(
          sidebar.getByText(group, { exact: true }),
          `${key}: heading ${group}`,
        ).toHaveCount(shown ? 1 : 0);
        for (const [label, slug] of items) {
          const link = sidebar.getByRole("link", { name: label, exact: true });
          if (areas.includes(slug)) {
            await expect(link, `${key}: ${label}`).toHaveAttribute(
              "href",
              `/w/${peopleOps}/${slug}`,
            );
          } else {
            await expect(link, `${key}: ${label} is hidden`).toHaveCount(0);
          }
        }
      }
      // A hidden area, opened by URL, is the forbidden page inside the shell (the 11 slugs cover all).
      const hiddenArea = ALL_AREAS.find((slug) => !areas.includes(slug));
      if (hiddenArea) {
        await page.goto(`/w/${peopleOps}/${hiddenArea}`);
        const forbidden = page.getByTestId("area-forbidden");
        await expect(forbidden, `${key}: ${hiddenArea}`).toBeVisible();
        await expect(forbidden.getByRole("heading", { level: 1 })).toHaveText("No access");
        await expect(forbidden).toContainText(FORBIDDEN_TEXT);
        await expect(sidebar).toBeVisible();
      }
      expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
      expect(seen.problems, key).toEqual([]);
    });
  }
  // Org Admin with Reviewer sees all 11 areas.
  expect(AREAS_BY_PERSONA.orgAdminReviewer?.length).toBe(ALL_AREAS.length);
});

test("AC7 TC-7-5: the user menu names the Workspace role, else the Org role; a Workspace Admin without an Org role cannot edit their own row", async ({
  browser,
}) => {
  const labels: [string, string][] = [
    ["wsAdmin", "Workspace Admin"],
    ["developer", "Developer"],
    ["ke", "Knowledge Editor"],
    ["reviewer", "Reviewer"],
    ["orgAdmin", "Org Admin"],
    ["orgOwner", "Org Owner"],
  ];
  for (const [key, label] of labels) {
    await withSession(browser, await api(key), async (page) => {
      await page.goto(`/w/${peopleOps}/dashboard`);
      await expect(page.getByTestId("user-menu"), key).toContainText(label);
    });
  }
  const wsAdmin = user("wsAdmin");
  await withSession(browser, await api("wsAdmin"), async (page) => {
    await openMembers(page, peopleOps);
    await expect(page.getByTestId("invite-member")).toBeVisible();
    // Own row: text, so they cannot lock themselves out; other rows: selects.
    const own = memberRow(page, wsAdmin.id);
    await expect(own.getByRole("combobox")).toHaveCount(0);
    await expect(own.getByTestId("member-role")).toHaveText("Workspace Admin");
    await expect(roleSelect(page, user("viewer").name)).toBeVisible();
  });
  // An Org Admin sees their own (Workspace) row as editable.
  await withSession(browser, await api("orgAdminReviewer"), async (page) => {
    await openMembers(page, peopleOps);
    await expect(roleSelect(page, user("orgAdminReviewer").name)).toBeEnabled();
  });
});

test("AC7 TC-7-6: a refused or failed role change is reverted in the select and announced in an alert", async ({
  browser,
}) => {
  const viewerRow = user("viewer");
  const admin = await api("orgAdmin");
  await withSession(browser, admin, async (page) => {
    await openMembers(page, peopleOps);
    const select = roleSelect(page, viewerRow.name);
    await expect.poll(() => selectedLabel(select)).toBe("Viewer");

    await page.route("**/api/workspaces/*/members/*", async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      return route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "forbidden" }),
      });
    });
    await chooseOption(select, "Reviewer");
    await expect(page.getByTestId("members-error")).toHaveText(
      "You don't have permission to do this.",
    );
    await expect.poll(() => selectedLabel(select)).toBe("Viewer");

    await page.unroute("**/api/workspaces/*/members/*");
    await page.route("**/api/workspaces/*/members/*", async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      return route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "server_error" }),
      });
    });
    await chooseOption(select, "Builder");
    await expect(page.getByTestId("members-error")).toHaveText("Something went wrong. Try again.");
    await expect.poll(() => selectedLabel(select)).toBe("Viewer");
  });
  expect(wsRoleOf(peopleOps, viewerRow.id)).toBe("viewer");
});

// ---------------------------------------------------------------------------------------------
// NFR role changes take effect for open sessions
// ---------------------------------------------------------------------------------------------

test("AC5 TC-5-3 (A8): nobody removes their own last management right in a Workspace: 403; with an Org role it is allowed", async () => {
  const lock = user("lockAdmin");
  const asLock = await api("lockAdmin");
  const events = countRoleEvents();
  const own = `/api/workspaces/${wsX}/members/${lock.id}`;
  // A Workspace Admin without Org role: lowering or removing themselves would end their management.
  for (const role of ["reviewer", "viewer", "builder"]) {
    const result = await asLock.send("PUT", own, { json: { role } });
    expect(result.status, `PUT own role ${role}: ${result.text}`).toBe(403);
  }
  expect((await asLock.send("DELETE", own)).status).toBe(403);
  expect(wsRoleOf(wsX, lock.id)).toBe("workspace_admin");
  expect(countRoleEvents(), "refused changes write no event").toBe(events);
  // Setting the same role is not a lock-out.
  expect((await asLock.send("PUT", own, { json: { role: "workspace_admin" } })).status).toBe(200);
  // Another manager may change them (lateral management); they can be restored.
  const other = await api("xAdmin");
  const lowered = await other.send("PUT", own, { json: { role: "builder" } });
  expect(lowered.status, lowered.text).toBe(200);
  expect(wsRoleOf(wsX, lock.id)).toBe("builder");
  expect((await other.send("PUT", own, { json: { role: "workspace_admin" } })).status).toBe(200);

  // An Org Admin who is also Workspace Admin keeps their rights through the Org role: allowed (footnote).
  const both = user("lockBoth");
  const asBoth = await api("lockBoth");
  const lowerSelf = await asBoth.send("PUT", `/api/workspaces/${wsX}/members/${both.id}`, {
    json: { role: "reviewer" },
  });
  expect(lowerSelf.status, lowerSelf.text).toBe(200);
  expect(wsRoleOf(wsX, both.id)).toBe("reviewer");
  const removeSelf = await asBoth.send("DELETE", `/api/workspaces/${wsX}/members/${both.id}`);
  expect(removeSelf.status, removeSelf.text).toBe(204);
  expect(wsRoleOf(wsX, both.id)).toBeNull();
  // Still an Org Admin: sees and manages the Workspace without a membership.
  const afterRemoval = body<WorkspaceInfo>(await asBoth.workspace(wsX));
  expect(afterRemoval).toMatchObject({ role: null, org_role: "org_admin" });
  expect(afterRemoval.permissions).toContain("members.manage");
});

test("AC7 TC-7-7 (Q1-1): a 201-character name is refused with its own message, not the e-mail message", async ({
  browser,
}) => {
  const admin = await api("orgAdmin");
  const email = `qa22.ea23-name201.${RUN}@mekongdevworks.example`;
  await withSession(browser, admin, async (page) => {
    await openMembers(page, peopleOps);
    await page.getByTestId("invite-member").click();
    const dialog = page.getByRole("dialog", { name: "Invite member" });
    await dialog.getByRole("textbox", { name: "Email", exact: true }).fill(email);
    const nameBox = dialog.getByRole("textbox", { name: "Name (optional)", exact: true });
    await nameBox.fill("Ơ".repeat(201));
    await dialog.getByRole("button", { name: "Send invite" }).click();
    const alert = dialog.getByRole("alert");
    await page.waitForTimeout(1000);
    if (await alert.isVisible().catch(() => false)) {
      const text = ((await alert.textContent()) ?? "").trim();
      expect(text).not.toBe("Enter a valid email address.");
      expect(text.length).toBeGreaterThan(0);
      await expect(dialog).toBeVisible(); // nothing was created
      expect(
        rows(`select id from users where org_id = '${DEMO_ORG}' and email = '${email}'`),
      ).toEqual([]);
      await page.screenshot({ path: path.join(SCREENSHOTS_23, "r2-name-201.png") });
    } else {
      // The field is capped at 200 characters: the invite went through with a 200-character name.
      await expect(page.getByTestId("members-status")).toHaveText(
        `Invitation created for ${email}.`,
      );
      const stored = rows(
        `select length(display_name) from users where org_id = '${DEMO_ORG}' and email = '${email}'`,
      )[0];
      expect(Number(stored)).toBeLessThanOrEqual(200);
    }
    // 200 characters are fine.
    await page.reload();
    await page.getByTestId("invite-member").click();
    const dialog2 = page.getByRole("dialog", { name: "Invite member" });
    const email200 = `qa22.ea23-name200.${RUN}@mekongdevworks.example`;
    await dialog2.getByRole("textbox", { name: "Email", exact: true }).fill(email200);
    await dialog2
      .getByRole("textbox", { name: "Name (optional)", exact: true })
      .fill("Ơ".repeat(200));
    await dialog2.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByTestId("members-status")).toHaveText(
      `Invitation created for ${email200}.`,
    );
  });
});

test("AC7 TC-7-8 (Q1-2): a 401 on a role change or an invite sends the user to the sign-in page", async ({
  browser,
}) => {
  const admin = await api("orgAdmin");
  const target = user("roleTarget");
  const email = `qa22.ea23-401.${RUN}@mekongdevworks.example`;
  for (const action of ["role", "invite"] as const) {
    await withSession(browser, admin, async (page, context) => {
      await openMembers(page, peopleOps);
      await context.clearCookies(); // the session is gone, as after expiry or a sign-out elsewhere
      if (action === "role") {
        await chooseOption(roleSelect(page, target.name), "Builder");
      } else {
        await page.getByTestId("invite-member").click();
        const dialog = page.getByRole("dialog", { name: "Invite member" });
        await dialog.getByRole("textbox", { name: "Email", exact: true }).fill(email);
        await dialog.getByRole("button", { name: "Send invite" }).click();
      }
      await expect(page, action).toHaveURL(`${ADMIN}/sign-in`);
    });
  }
  expect(wsRoleOf(peopleOps, target.id)).toBe("viewer");
  expect(rows(`select id from users where org_id = '${DEMO_ORG}' and email = '${email}'`)).toEqual(
    [],
  );
});

test("AC7 TC-7-9: while a role change is pending only that row is busy; the others stay usable", async ({
  browser,
}) => {
  const admin = await api("orgAdmin");
  const a = user("uiTarget");
  const b = user("viewer");
  await withSession(browser, admin, async (page) => {
    await openMembers(page, peopleOps);
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/workspaces/*/members/*", async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      await gate;
      return route.continue();
    });
    const rowA = roleSelect(page, a.name);
    const rowB = roleSelect(page, b.name);
    await chooseOption(rowA, "Reviewer");
    const busy = await rowA.evaluate(
      (element) =>
        (element as HTMLSelectElement).disabled || element.getAttribute("aria-busy") === "true",
    );
    expect(busy, "the changed row shows a pending state (disabled or aria-busy)").toBe(true);
    await expect(rowB).toBeEnabled();
    await page.screenshot({ path: path.join(SCREENSHOTS_23, "r2-row-pending.png") });
    release();
    await expect(page.getByTestId("members-status")).toHaveText("Role updated.");
    await expect(rowA).toBeEnabled();
    await expect.poll(() => selectedLabel(rowA)).toBe("Reviewer");
    expect(wsRoleOf(peopleOps, a.id)).toBe("reviewer");
    await page.unroute("**/api/workspaces/*/members/*");
  });
});

test("NFR: a role lowered by an admin applies to the open session on its next request and on the next screen", async ({
  browser,
}) => {
  const u2 = user("u2");
  const u2Api = await api("u2");
  const admin = await api("orgAdmin");
  await withSession(browser, u2Api, async (page) => {
    await page.goto(`/w/${wsX}/dashboard`);
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar.getByRole("link", { name: "Assistants", exact: true })).toBeVisible();
    expect(body<WorkspaceInfo>(await u2Api.workspace(wsX)).permissions).toContain(
      "assistants.manage",
    );

    const changedAt = Date.now();
    const put = await admin.send("PUT", `/api/workspaces/${wsX}/members/${u2.id}`, {
      json: { role: "viewer" },
    });
    expect(put.status, put.text).toBe(200);

    // The same cookie, the next request: the new permissions (well within 60 seconds).
    const info = body<WorkspaceInfo>(await u2Api.workspace(wsX));
    expect(Date.now() - changedAt).toBeLessThan(60_000);
    expect(info.role).toBe("viewer");
    expect(info.permissions).not.toContain("assistants.manage");
    expect(info.permissions).not.toContain("assistants.publish");
    // The old role is refused on a write route too (stale-role attack).
    expectDetail(
      await u2Api.send("PUT", `/api/workspaces/${wsX}/members/${user("existing").id}`, {
        json: { role: "builder" },
      }),
      403,
      "forbidden",
    );

    // The open page: the next area change re-checks the role and the Sidebar loses Assistants.
    await sidebar.getByRole("link", { name: "Members & roles", exact: true }).click();
    await expect(page).toHaveURL(url(wsX, "members"));
    await expect(page.getByTestId("members-page")).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Assistants", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("invite-member")).toHaveCount(0);
    await expect(page.getByTestId("user-menu")).toContainText("Viewer");
    // The hidden area by URL is refused with the forbidden page.
    await page.goto(`/w/${wsX}/assistants`);
    await expect(page.getByTestId("area-forbidden")).toBeVisible();
  });
});
