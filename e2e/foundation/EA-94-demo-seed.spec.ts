// EA-94 (FND-14): realistic local demo seed with one shared test password and a test-accounts README.
// Black-box specs written from .work/EA-94/contract.md and ticket.md only. Runs against a running,
// migrated stack:
//   npm run up -- --no-model && npm run e2e -- e2e/foundation/EA-94-demo-seed.spec.ts
// The suite purges both demo Organizations (children first, as the EA-21 spec does) and runs
// `npm run seed` for the fresh-database scenario, so it ends with a freshly seeded demo. Every account
// it creates itself is named `qa22.qa-ea94-<label>.<run>@mekongdevworks.example` and removed again; a
// scenario that changes or deletes a seeded credential restores the saved row exactly. The shared
// password is read from EI_AI_SEED_PASSWORD (shell, .env, .env.example), never hard-coded here.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import {
  ApiSession,
  ROOT,
  RUN,
  UUID,
  apiLogs,
  cleanup,
  cli,
  expectDetail,
  inviteUser,
  issueLink,
  lines,
  newPassword,
  parseLink,
  peopleOpsId,
  rows,
  signInUi,
  sql,
  watch,
  withPage,
  withoutExpected401,
} from "../support/ea22";
import { IDENTITY_PARAMS, body, permissionsFor, withSession } from "../support/ea23";
import type { SessionBody, WorkspaceInfo } from "../support/ea23";
import {
  ACCOUNTS,
  COLLECTIONS,
  EXPECTED_AUDIT,
  EXPECTED_ROWS,
  FRESH_OUTPUT,
  MARK_94,
  ORGS,
  ORG_IDS,
  PASSWORD_MISSING,
  PASSWORD_TOO_LONG,
  SCREENSHOTS_94,
  SEED_ACTIONS,
  SEED_REFUSED_LINES,
  SONGHAN_SYSADMIN,
  SYSADMIN_EMAIL,
  auditByAction,
  auditIdsOf,
  capturedOutputs,
  collectionsOf,
  collectionsPath,
  deleteAuditExcept,
  dotenvValue,
  folderPaths,
  forgetSession,
  json,
  membersOf,
  normalizeOutput,
  orgCounts,
  otherCounts,
  passwordHashOf,
  purgeDemoOrgs,
  readmePath,
  rememberSession,
  removeRunTraces,
  repeatOutput,
  restoreCredential,
  rowsContaining,
  saveCredential,
  seed,
  seedDirect,
  seedPassword,
  serviceLogs,
  sessionFor,
  sorted,
  userId,
  workspaceIds,
  type Account,
  type CollectionDetail,
  type CollectionItem,
  type OrgKey,
  type Run,
} from "../support/ea94";

test.describe.configure({ mode: "serial", timeout: 240_000 });

const PASSWORD = seedPassword();
const PW_SQL = PASSWORD.replace(/'/g, "''");
const MEKONG = ORGS.mekong;
const SONGHAN = ORGS.songhan;
const ORG_LIST = ORG_IDS.map((id) => `'${id}'`).join(", ");

let wsIds: Record<OrgKey, Record<string, string>>;
let fresh: Run;
let freshCounts: Record<OrgKey, Record<string, number>>;
let freshAudit: Record<OrgKey, Record<string, number>>;
let freshTokens: number;
let outsideBefore: Record<string, number>;

/** Sign-in accounts only (shared password given). */
const SIGN_IN = ACCOUNTS.filter((account) => account.shared);

function idOfWorkspace(org: OrgKey, name: string): string {
  const id = wsIds[org]?.[name];
  expect(id, `Workspace ${name} of ${ORGS[org].name} exists`).toBeTruthy();
  return id as string;
}

function landingId(account: Account): string {
  return idOfWorkspace(account.org, account.lands);
}

function markerRows(): string[] {
  return rows(
    `select email from users where email ilike '%${MARK_94}%' or display_name ilike '%${MARK_94}%'
     union all select name from workspaces where name ilike '%${MARK_94}%'
     union all select name from organizations where name ilike '%${MARK_94}%'`,
  );
}

/** Both demo Organizations as they must look after a clean seed: counts and the audit actions. */
function expectSeededState(): void {
  for (const org of ["mekong", "songhan"] as const) {
    expect(orgCounts(ORGS[org].id), `${ORGS[org].name} row counts`).toEqual(EXPECTED_ROWS[org]);
    expect(auditByAction(ORGS[org].id), `${ORGS[org].name} audit actions`).toEqual(
      EXPECTED_AUDIT[org],
    );
  }
}

/** Counts of both demo Organizations plus everything else (an unchanged database is "nothing written"). */
function snapshot(): {
  mekong: Record<string, number>;
  songhan: Record<string, number>;
  other: Record<string, number>;
} {
  return {
    mekong: orgCounts(MEKONG.id),
    songhan: orgCounts(SONGHAN.id),
    other: otherCounts(),
  };
}

function expectNoWrite(before: ReturnType<typeof snapshot>): void {
  expect(snapshot()).toEqual(before);
}

test.beforeAll(async () => {
  test.setTimeout(420_000);
  fs.mkdirSync(SCREENSHOTS_94, { recursive: true });
  cleanup(); // leftovers of a crashed earlier run (qa22.* users)
  const warmUp = seed("warm-up seed");
  expect(warmUp.status, warmUp.stderr).toBe(0);
  outsideBefore = otherCounts();

  // Fresh-database precondition of every AC: both demo Organizations purged, then `npm run seed`.
  purgeDemoOrgs();
  expect(orgCounts(MEKONG.id).organizations).toBe(0);
  expect(orgCounts(SONGHAN.id).organizations).toBe(0);
  fresh = seed("fresh seed");
  freshCounts = { mekong: orgCounts(MEKONG.id), songhan: orgCounts(SONGHAN.id) };
  freshAudit = { mekong: auditByAction(MEKONG.id), songhan: auditByAction(SONGHAN.id) };
  freshTokens = Number(
    sql(`select count(*) from set_password_tokens where org_id in (${ORG_LIST})`),
  );
  wsIds = { mekong: workspaceIds(MEKONG.id), songhan: workspaceIds(SONGHAN.id) };
});

test.afterAll(async () => {
  // Hygiene: remove what this spec created, then prove the database is the seeded demo again.
  cleanup();
  removeRunTraces();
  expect(markerRows(), "rows that still carry the qa-ea94 marker").toEqual([]);
  expectSeededState();
  expect(otherCounts(), "rows outside the demo Organizations are untouched").toEqual(outsideBefore);
});

// ---------------------------------------------------------------------------------------------
// AC1 One password
// ---------------------------------------------------------------------------------------------

test("AC1: every seeded account signs in with the shared password, lands on its default Workspace and gets no set-password link", async () => {
  expect(fresh.status, fresh.stderr).toBe(0);
  expect(freshTokens, "set_password_tokens of both demo Organizations after the fresh seed").toBe(
    0,
  );
  expect(SIGN_IN).toHaveLength(11);

  for (const account of SIGN_IN) {
    const api = new ApiSession();
    const result = await api.signIn(account.email, PASSWORD);
    expect(result.status, `${account.email}: ${result.text}`).toBe(200);
    expect(result.json, account.email).toEqual({ default_workspace_id: landingId(account) });
    expect(api.sessionCookie, `${account.email}: session cookie`).toBeTruthy();

    const session = body<SessionBody>(await api.session());
    expect(session.user.email, account.email).toBe(account.email);
    expect(session.user.display_name, account.email).toBe(account.name);
    expect(session.organization, account.email).toEqual({
      id: ORGS[account.org].id,
      name: ORGS[account.org].name,
    });
    expect(session.default_workspace_id, account.email).toBe(landingId(account));
    expect(session.org_role, account.email).toBe(account.orgRole);
    rememberSession(account.email, api); // reused by the later cases (sign-ins are rate limited)
  }

  // No account needs a set-password link: no token row exists and the seed printed none.
  expect(
    Number(sql(`select count(*) from set_password_tokens where org_id in (${ORG_LIST})`)),
  ).toBe(0);
  for (const text of [fresh.stdout, fresh.stderr]) {
    expect(text).not.toContain("#token=");
    expect(text).not.toContain("set-password");
  }
});

test("AC1 TC-1-2: a wrong password and an unknown account are refused with the same answer", async () => {
  const linh = ACCOUNTS[0] as Account;
  const wrong = new ApiSession();
  const bad = await wrong.signIn(linh.email, `${PASSWORD}-wrong`);
  expectDetail(bad, 401, "invalid_credentials");
  expect(wrong.sessionCookie).toBeUndefined();

  // An email that exists nowhere: no lockout risk, same status and body.
  const ghost = new ApiSession();
  const nobody = await ghost.signIn(`nobody.${MARK_94}${RUN}@mekongdevworks.example`, PASSWORD);
  expectDetail(nobody, 401, "invalid_credentials");
  expect(nobody.text).toBe(bad.text);
});

test("AC1 TC-1-3: sign-in through the admin UI for five accounts lands on /w/<default Workspace>/dashboard", async ({
  browser,
}) => {
  const emails = ["linh.tran", "duy.lam", "vy.huynh", "sysadmin", "ngan.trinh"];
  const picked = SIGN_IN.filter((account) =>
    emails.some((prefix) => account.email.startsWith(prefix)),
  );
  expect(picked).toHaveLength(5);
  for (const account of picked) {
    await withPage(browser, undefined, async (page) => {
      const seen = watch(page);
      await signInUi(page, account.email, PASSWORD);
      await expect(page).toHaveURL(new RegExp(`/w/${landingId(account)}/dashboard$`));
      await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
      await expect(page.getByTestId("workspace-switcher")).toContainText(account.lands);
      await expect(page.getByText(/set your password|set-password/i)).toHaveCount(0);
      expect(withoutExpected401(seen.problems), account.email).toEqual([]);
      await page.screenshot({
        path: path.join(SCREENSHOTS_94, `ac1-ui-${account.email.split("@")[0]}.png`),
      });
    });
  }
});

test("AC1 TC-1-4: a person who sets a password still needs at least 12 characters; the shared password is only a seed value", async () => {
  expect(
    PASSWORD.length,
    "the shared password is shorter than the 12-character policy",
  ).toBeLessThan(12);
  const peopleOps = peopleOpsId();
  try {
    const user = inviteUser({ label: `${MARK_94}pw`, role: "viewer", workspaceId: peopleOps });
    const api = new ApiSession();

    // The seed never gives the shared password to an account created outside the manifest.
    expectDetail(await api.signIn(user.email, PASSWORD), 401, "invalid_credentials");

    // The shared password (8 characters) and an 11-character value are refused at set-password.
    const eleven = "Qa94-abcdef";
    expect(eleven).toHaveLength(11);
    for (const candidate of [PASSWORD, eleven]) {
      const link = issueLink(user);
      expectDetail(await api.setPassword(link.token, candidate), 422, "password_too_short");
    }
    const none = rows(
      `select count(*) from user_credentials where org_id = '${MEKONG.id}' and user_id = '${user.id}'`,
    );
    expect(none).toEqual(["0"]);

    // Exactly 12 characters is accepted and signs in.
    const twelve = "Qa94-abcdef1";
    expect(twelve).toHaveLength(12);
    const link = issueLink(user);
    const set = await api.setPassword(link.token, twelve);
    expect(set.status, set.text).toBe(204);
    const signed = await new ApiSession().signIn(user.email, twelve);
    expect(signed.status, signed.text).toBe(200);
  } finally {
    cleanup();
  }
});

test("AC1 TC-1-5: the fresh seed prints exactly the contract output, nothing on stderr, exit code 0", async () => {
  expect(fresh.status).toBe(0);
  expect(fresh.stderr).toBe("");
  expect(normalizeOutput(fresh.stdout)).toEqual(FRESH_OUTPUT);
  expect(fresh.stdout).toContain(`Organization: Mekong Devworks (${MEKONG.id}): created`);
  expect(fresh.stdout).toContain(`Organization: Sông Hàn Retail (${SONGHAN.id}): created`);
  const ids = [
    ...fresh.stdout.matchAll(new RegExp(`Workspace: (.+) \\((${UUID})\\): created`, "g")),
  ];
  expect(ids.map((match) => match[1])).toEqual(["People Ops", "Engineering", "Customer Care"]);
  for (const match of ids) {
    expect(match[2]).toBe(
      idOfWorkspace(match[1] === "Customer Care" ? "songhan" : "mekong", match[1] as string),
    );
  }

  // The state right after the fresh seed matches contract section 4 (taken before any sign-in).
  expect(freshCounts).toEqual({ mekong: EXPECTED_ROWS.mekong, songhan: EXPECTED_ROWS.songhan });
  expect(freshAudit).toEqual({ mekong: EXPECTED_AUDIT.mekong, songhan: EXPECTED_AUDIT.songhan });
  expect(
    rows(
      `select count(*) from user_credentials where org_id in (${ORG_LIST}) and password_hash like '$argon2id$%'`,
    ),
  ).toEqual(["11"]);
});

// ---------------------------------------------------------------------------------------------
// AC2 Every role
// ---------------------------------------------------------------------------------------------

test("AC2: the seed holds a sysadmin, an Org Owner, an Org Admin and every assignable Workspace role", async () => {
  const stored = (org: OrgKey) =>
    rows(
      `select u.email || '|' || coalesce(m.org_role::text, '') from memberships m
       join users u on u.id = m.user_id and u.org_id = m.org_id where m.org_id = '${ORGS[org].id}'`,
    ).sort();
  const storedWs = (org: OrgKey) =>
    rows(
      `select u.email || '|' || w.name || '|' || wm.role::text from workspace_memberships wm
       join users u on u.id = wm.user_id and u.org_id = wm.org_id
       join workspaces w on w.id = wm.workspace_id and w.org_id = wm.org_id
       where wm.org_id = '${ORGS[org].id}'`,
    ).sort();

  for (const org of ["mekong", "songhan"] as const) {
    const expectedOrg = membersOf(org)
      .map((a) => `${a.email}|${a.orgRole ?? ""}`)
      .sort();
    const expectedWs = membersOf(org)
      .flatMap((a) => Object.entries(a.roles).map(([ws, role]) => `${a.email}|${ws}|${role}`))
      .sort();
    expect(stored(org), `${ORGS[org].name} Organization roles`).toEqual(expectedOrg);
    expect(storedWs(org), `${ORGS[org].name} Workspace roles`).toEqual(expectedWs);
  }

  // Coverage: Org Owner, Org Admin and the six assignable Workspace roles all exist.
  const orgRoles = new Set(
    rows(
      `select org_role::text from memberships where org_id = '${MEKONG.id}' and org_role is not null`,
    ),
  );
  expect([...orgRoles].sort()).toEqual(["org_admin", "org_owner"]);
  const wsRoles = new Set(
    rows(`select role::text from workspace_memberships where org_id = '${MEKONG.id}'`),
  );
  for (const role of [
    "workspace_admin",
    "developer",
    "builder",
    "knowledge_editor",
    "reviewer",
    "viewer",
  ]) {
    expect(wsRoles.has(role), `Workspace role ${role} is seeded in Mekong Devworks`).toBe(true);
  }

  // The sysadmin: Org Owner and Workspace Admin in every Workspace of both Organizations.
  const sysadmin = rows(
    `select o.name || '|' || m.org_role::text from users u
     join memberships m on m.user_id = u.id and m.org_id = u.org_id
     join organizations o on o.id = u.org_id where u.email = '${SYSADMIN_EMAIL}'`,
  ).sort();
  expect(sysadmin).toEqual([`${MEKONG.name}|org_owner`, `${SONGHAN.name}|org_owner`].sort());
  const sysadminWs = rows(
    `select w.name || '|' || wm.role::text from workspace_memberships wm
     join users u on u.id = wm.user_id and u.org_id = wm.org_id
     join workspaces w on w.id = wm.workspace_id and w.org_id = wm.org_id
     where u.email = '${SYSADMIN_EMAIL}'`,
  ).sort();
  expect(sysadminWs).toEqual(
    [
      "Customer Care|workspace_admin",
      "Engineering|workspace_admin",
      "People Ops|workspace_admin",
    ].sort(),
  );

  // One person holds different roles in two Workspaces (Quang Le).
  const quang = rows(
    `select w.name || '|' || wm.role::text from workspace_memberships wm
     join users u on u.id = wm.user_id and u.org_id = wm.org_id
     join workspaces w on w.id = wm.workspace_id and w.org_id = wm.org_id
     where u.email = 'quang.le@mekongdevworks.example'`,
  ).sort();
  expect(quang).toEqual(["Engineering|workspace_admin", "People Ops|developer"]);

  // platform_admin is deliberately not stored in this ticket (owner decision).
  expect(
    rows(`select distinct org_role::text from memberships where org_role is not null`).sort(),
  ).toEqual(["org_admin", "org_owner"]);
  expect(
    rows(`select count(*) from workspace_memberships where role::text = 'platform_admin'`),
  ).toEqual(["0"]);
});

test("AC2 TC-2-2: every seeded account holds the role it is documented with, in the API and in the permissions it gets", async () => {
  for (const account of SIGN_IN) {
    const api = await sessionFor(account.email);
    const session = body<SessionBody>(await api.session());
    const orgWorkspaces = ORGS[account.org].workspaces;
    const sees =
      account.orgRole !== null ? orgWorkspaces : orgWorkspaces.filter((ws) => ws in account.roles);
    expect(sorted(session.workspaces.map((w) => w.name)), `${account.email}: Workspaces`).toEqual(
      sorted(sees),
    );
    for (const entry of session.workspaces) {
      expect(entry.id).toBe(idOfWorkspace(account.org, entry.name));
      expect(entry.role, `${account.email} in ${entry.name}`).toBe(
        account.roles[entry.name] ?? null,
      );
    }

    for (const name of orgWorkspaces) {
      const result = await api.workspace(idOfWorkspace(account.org, name));
      if (sees.includes(name)) {
        expect(result.status, `${account.email} GET ${name}: ${result.text}`).toBe(200);
        const info = body<WorkspaceInfo>(result);
        expect(info).toMatchObject({
          id: idOfWorkspace(account.org, name),
          name,
          role: account.roles[name] ?? null,
          org_role: account.orgRole,
        });
        expect(info.permissions, `${account.email} in ${name}`).toEqual(
          permissionsFor(account.orgRole, account.roles[name] ?? null),
        );
      } else {
        // A person without a role there never sees that Workspace.
        expect([403, 404], `${account.email} GET ${name}`).toContain(result.status);
      }
    }
  }
});

// ---------------------------------------------------------------------------------------------
// AC3 Realistic data
// ---------------------------------------------------------------------------------------------

async function listCollections(api: ApiSession, workspaceId: string): Promise<CollectionItem[]> {
  const result = await api.send("GET", collectionsPath(workspaceId));
  expect(result.status, result.text).toBe(200);
  return json<{ collections: CollectionItem[] }>(result).collections;
}

async function detail(api: ApiSession, workspaceId: string, id: string): Promise<CollectionDetail> {
  const result = await api.send("GET", `${collectionsPath(workspaceId)}/${id}`);
  expect(result.status, result.text).toBe(200);
  return json<CollectionDetail>(result);
}

test("AC3: the seeded collections have folders as on the CollectionDetail artboard, at least one nested, and no placeholder text", async () => {
  const admin: Record<OrgKey, ApiSession> = {
    mekong: await sessionFor(SYSADMIN_EMAIL),
    songhan: await sessionFor("ngan.trinh@songhanretail.example"),
  };
  let depth3 = 0;
  let nested = 0;
  let totalFolders = 0;

  for (const org of ["mekong", "songhan"] as const) {
    for (const workspace of ORGS[org].workspaces) {
      const workspaceId = idOfWorkspace(org, workspace);
      const expected = COLLECTIONS.filter((spec) => spec.workspace === workspace);
      const listed = await listCollections(admin[org], workspaceId);
      expect(sorted(listed.map((c) => c.name)), `${workspace}: collections`).toEqual(
        sorted(expected.map((c) => c.name)),
      );
      for (const spec of expected) {
        const item = listed.find((c) => c.name === spec.name) as CollectionItem;
        expect(item, `${workspace} / ${spec.name}`).toMatchObject({
          subtitle: spec.subtitle,
          access_level: spec.access,
          local_only: spec.localOnly,
        });
        expect(sorted(item.groups), `${spec.name}: groups`).toEqual(sorted(spec.groups));

        const full = await detail(admin[org], workspaceId, item.id);
        expect(folderPaths(full), `${spec.name}: folders`).toEqual(sorted(spec.folders));
        for (const folder of full.folders) {
          expect(Object.keys(folder).sort()).toEqual([
            "depth",
            "document_count",
            "id",
            "name",
            "parent_id",
          ]);
          expect(folder.document_count, `${folder.name}: seed holds no documents`).toBe(0);
          expect(folder.depth, `${spec.name} / ${folder.name}`).toBeGreaterThanOrEqual(1);
          expect(folder.depth).toBeLessThanOrEqual(3);
          expect(folder.parent_id === null, `${folder.name}: root has no parent`).toBe(
            folder.depth === 1,
          );
          if (folder.depth > 1) nested += 1;
          if (folder.depth === 3) depth3 += 1;
          totalFolders += 1;
        }
        // Sibling names are unique, case-insensitively.
        const siblings = full.folders.map((f) => `${f.parent_id ?? ""}|${f.name.toLowerCase()}`);
        expect(new Set(siblings).size).toBe(siblings.length);
      }
    }
  }
  expect(totalFolders).toBe(36);
  expect(nested, "at least one nested folder").toBeGreaterThanOrEqual(1);
  expect(depth3, "exactly one folder at depth 3 (Templates / Contracts / Labor contracts)").toBe(1);

  // The folder rows in the database agree with the API, per collection.
  const perCollection = rows(
    `select c.name || '|' || count(f.id) from collections c left join folders f on f.collection_id = c.id and f.org_id = c.org_id
     where c.org_id in (${ORG_LIST}) group by c.name order by c.name`,
  );
  expect(sorted(perCollection)).toEqual(
    sorted(COLLECTIONS.map((c) => `${c.name}|${c.folders.length}`)),
  );

  // The Employee Handbook roots are the four folders of the artboard.
  const handbook = COLLECTIONS.find((c) => c.name === "Employee Handbook");
  expect(handbook?.folders.filter((f) => !f.includes("/"))).toEqual([
    "Policies",
    "Benefits",
    "Onboarding & offboarding",
    "Templates",
  ]);

  // No row, name, subtitle, folder, group or e-mail is placeholder text (case-insensitive whole words).
  const placeholder = String.raw`\m(test|foo|lorem)\M`;
  const hits = rows(
    `select 'organization|' || name from organizations where id in (${ORG_LIST}) and name ~* '${placeholder}'
     union all select 'workspace|' || name from workspaces where org_id in (${ORG_LIST}) and name ~* '${placeholder}'
     union all select 'user|' || display_name || ' ' || email from users where org_id in (${ORG_LIST}) and (display_name || ' ' || email) ~* '${placeholder}'
     union all select 'collection|' || name || ' ' || coalesce(subtitle, '') from collections where org_id in (${ORG_LIST}) and (name || ' ' || coalesce(subtitle, '')) ~* '${placeholder}'
     union all select 'folder|' || name from folders where org_id in (${ORG_LIST}) and name ~* '${placeholder}'`,
  );
  expect(hits, "placeholder text in seeded rows").toEqual([]);
  const everyText = [
    ...COLLECTIONS.flatMap((c) => [c.name, c.subtitle ?? "", ...c.groups, ...c.folders]),
    ...ACCOUNTS.flatMap((a) => [a.name, a.email]),
  ].join("\n");
  expect(everyText).not.toMatch(/\b(test|foo|lorem)\b/i);
});

test("AC3 TC-3-2: the seed uses Vietnamese names with diacritics unchanged in the database and the API", async () => {
  const names = rows(`select display_name from users where org_id in (${ORG_LIST})`);
  for (const name of ["Hà Vũ", "Duy Lâm", "Vy Huỳnh", "Phúc Lương", "Trung Võ", "Ngân Trịnh"]) {
    expect(names, name).toContain(name);
  }
  expect(rows(`select name from organizations where id = '${SONGHAN.id}'`)).toEqual([SONGHAN.name]);
  const api = await sessionFor(SYSADMIN_EMAIL);
  const session = body<SessionBody>(await api.session());
  expect(session.user.display_name).toBe("Trung Võ");
});

test("AC3 TC-3-3: the CollectionDetail screen of Employee Handbook shows its 14 folders", async ({
  browser,
}) => {
  const api = await sessionFor(SYSADMIN_EMAIL);
  const peopleOps = idOfWorkspace("mekong", "People Ops");
  const listed = await listCollections(api, peopleOps);
  const handbook = listed.find((c) => c.name === "Employee Handbook") as CollectionItem;
  await withSession(browser, api, async (page) => {
    const seen = watch(page);
    await page.goto(`/w/${peopleOps}/knowledge/${handbook.id}`);
    await expect(page.getByTestId("collection-detail")).toBeVisible();
    const rowsOnScreen = page.getByTestId("folder-row");
    await expect(rowsOnScreen).toHaveCount(14);
    for (const name of [
      "Policies",
      "Benefits",
      "Onboarding & offboarding",
      "Templates",
      "Leave & time off",
      "Labor contracts",
    ]) {
      await expect(rowsOnScreen.filter({ hasText: name }).first()).toBeVisible();
    }
    await page.screenshot({
      path: path.join(SCREENSHOTS_94, "ac3-employee-handbook-folders.png"),
      fullPage: true,
    });
    expect(withoutExpected401(seen.problems)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------
// AC4 Isolation demo
// ---------------------------------------------------------------------------------------------

const FOREIGN_TERMS = [
  SONGHAN.name,
  "Customer Care",
  "Store Policies",
  "songhanretail",
  "Ngân Trịnh",
];
const MEKONG_TERMS = [MEKONG.name, "People Ops", "Engineering", "mekongdevworks"];

test("AC4: a member of Mekong Devworks never sees Sông Hàn Retail (Organization, Workspaces, collections) and the reverse", async ({
  browser,
}) => {
  const customerCare = idOfWorkspace("songhan", "Customer Care");
  const storePolicies = rows(
    `select id from collections where org_id = '${SONGHAN.id}'`,
  )[0] as string;
  expect(storePolicies).toBeTruthy();
  const mekongWorkspaces = Object.entries(wsIds.mekong);
  const mekongCollection = rows(
    `select id from collections where org_id = '${MEKONG.id}' limit 1`,
  )[0] as string;

  const pickers = ["linh.tran", "son.hoang", "vy.huynh", "sysadmin"];
  for (const account of SIGN_IN.filter(
    (a) => a.org === "mekong" && pickers.some((p) => a.email.startsWith(p)),
  )) {
    const api = await sessionFor(account.email);
    const seenBodies: string[] = [];
    const note = (text: string) => seenBodies.push(text);

    const session = await api.session();
    note(session.text);
    const parsed = body<SessionBody>(session);
    expect(parsed.organization.name, account.email).toBe(MEKONG.name);
    expect(
      parsed.workspaces.map((w) => w.id),
      account.email,
    ).not.toContain(customerCare);

    const org = await api.send("GET", "/api/organization");
    note(org.text);
    expect(org.status).toBe(200);
    expect(org.json, account.email).toEqual({ id: MEKONG.id, name: MEKONG.name });

    expectDetail(await api.send("GET", `/api/workspaces/${customerCare}`), 404, "not_found");
    expectDetail(await api.send("GET", collectionsPath(customerCare)), 404, "not_found");
    expectDetail(
      await api.send("GET", `${collectionsPath(customerCare)}/${storePolicies}`),
      404,
      "not_found",
    );
    // A forged identity parameter changes nothing.
    const forged = await api.send("GET", `/api/organization?org_id=${SONGHAN.id}`);
    expect(forged.json).toEqual({ id: MEKONG.id, name: MEKONG.name });

    for (const text of seenBodies) {
      for (const term of FOREIGN_TERMS)
        expect(text, `${account.email} response`).not.toContain(term);
    }
  }
  // Another Organization's collection id inside an own Workspace is not found either.
  const own = await sessionFor(SYSADMIN_EMAIL);
  expectDetail(
    await own.send(
      "GET",
      `${collectionsPath(idOfWorkspace("mekong", "People Ops"))}/${storePolicies}`,
    ),
    404,
    "not_found",
  );

  // The reverse: Ngân Trịnh sees only Sông Hàn Retail.
  const ngan = await sessionFor("ngan.trinh@songhanretail.example");
  const nganSession = body<SessionBody>(await ngan.session());
  expect(nganSession.organization.name).toBe(SONGHAN.name);
  expect(nganSession.workspaces.map((w) => w.name)).toEqual(["Customer Care"]);
  expect((await ngan.send("GET", "/api/organization")).json).toEqual({
    id: SONGHAN.id,
    name: SONGHAN.name,
  });
  for (const [, id] of mekongWorkspaces) {
    expectDetail(await ngan.send("GET", `/api/workspaces/${id}`), 404, "not_found");
    expectDetail(await ngan.send("GET", collectionsPath(id)), 404, "not_found");
  }
  expectDetail(
    await ngan.send("GET", `${collectionsPath(customerCare)}/${mekongCollection}`),
    404,
    "not_found",
  );
  const nganBodies = [
    (await ngan.session()).text,
    (await ngan.send("GET", collectionsPath(customerCare))).text,
  ];
  for (const text of nganBodies) {
    for (const term of MEKONG_TERMS) expect(text, "Ngân response").not.toContain(term);
  }

  // The admin UI: Workspace switcher and Organization switcher list only the own Organization.
  const expectedMenu: Record<string, string[]> = {
    "linh.tran": ["Engineering", "People Ops"],
    "son.hoang": ["People Ops"],
    "vy.huynh": ["Engineering"],
    sysadmin: ["Engineering", "People Ops"],
    "ngan.trinh": ["Customer Care"],
  };
  for (const account of SIGN_IN.filter((a) =>
    Object.keys(expectedMenu).some((p) => a.email.startsWith(p)),
  )) {
    const key = Object.keys(expectedMenu).find((p) => account.email.startsWith(p)) as string;
    const api = await sessionFor(account.email);
    await withSession(browser, api, async (page) => {
      const seen = watch(page);
      await page.goto(`/w/${landingId(account)}/dashboard`);
      await page.getByTestId("workspace-switcher").click();
      const items = page.getByRole("menu").getByRole("menuitemradio");
      await expect(items).toHaveCount((expectedMenu[key] as string[]).length);
      expect(sorted((await items.allTextContents()).map((t) => t.trim()))).toEqual(
        sorted(expectedMenu[key] as string[]),
      );
      await page.reload();
      await page.getByTestId("org-switcher").click();
      const orgItems = page.getByRole("menu").locator('[role^="menuitem"]');
      await expect(orgItems).toHaveCount(1);
      await expect(orgItems).toContainText(ORGS[account.org].name);
      await page.screenshot({
        path: path.join(SCREENSHOTS_94, `ac4-switchers-${key}.png`),
      });
      const text = await page.locator("body").innerText();
      const foreign = account.org === "mekong" ? FOREIGN_TERMS : MEKONG_TERMS;
      for (const term of foreign) expect(text, `${key}: page text`).not.toContain(term);
      expect(seen.requests.filter((r) => IDENTITY_PARAMS.test(r.url))).toEqual([]);
      expect(withoutExpected401(seen.problems)).toEqual([]);
    });
  }
});

test("AC4 TC-4-2: the sysadmin's Sông Hàn membership has no credential, so the shared password never opens Sông Hàn Retail", async () => {
  const mekongUser = userId(MEKONG.id, SYSADMIN_EMAIL);
  const songhanUser = userId(SONGHAN.id, SYSADMIN_EMAIL);
  expect(songhanUser).not.toBe(mekongUser);
  expect(
    rows(
      `select count(*) from user_credentials where org_id = '${SONGHAN.id}' and user_id = '${songhanUser}'`,
    ),
  ).toEqual(["0"]);
  expect(
    rows(
      `select m.org_role::text from memberships m where m.org_id = '${SONGHAN.id}' and m.user_id = '${songhanUser}'`,
    ),
  ).toEqual([SONGHAN_SYSADMIN.orgRole as string]);

  // Sign-in with the shared password opens Mekong Devworks.
  const first = new ApiSession();
  expect((await first.signIn(SYSADMIN_EMAIL, PASSWORD)).status).toBe(200);
  expect(body<SessionBody>(await first.session()).organization.id).toBe(MEKONG.id);

  // With the Mekong credential gone (saved and restored exactly), nothing opens: 401, never Sông Hàn.
  const saved = saveCredential(MEKONG.id, mekongUser);
  expect(saved, "precondition: the Mekong credential exists").not.toBeNull();
  const hashBefore = passwordHashOf(MEKONG.id, mekongUser);
  try {
    restoreCredential(MEKONG.id, mekongUser, null);
    const second = new ApiSession();
    expectDetail(await second.signIn(SYSADMIN_EMAIL, PASSWORD), 401, "invalid_credentials");
    expect(second.sessionCookie).toBeUndefined();
    expect(
      Number(sql(`select count(*) from user_credentials where org_id = '${SONGHAN.id}'`)),
    ).toBe(1);
  } finally {
    restoreCredential(MEKONG.id, mekongUser, saved);
    forgetSession(SYSADMIN_EMAIL);
  }
  expect(passwordHashOf(MEKONG.id, mekongUser)).toBe(hashBefore);
  const again = new ApiSession();
  expect((await again.signIn(SYSADMIN_EMAIL, PASSWORD)).status).toBe(200);
});

// ---------------------------------------------------------------------------------------------
// AC5 Idempotent and safe
// ---------------------------------------------------------------------------------------------

test("AC5: a second and third `npm run seed` create nothing, print the same text and change no row", async () => {
  const before = snapshot();
  const first = seed("repeat seed 1");
  const second = seed("repeat seed 2");
  for (const run of [first, second]) {
    expect(run.status, run.stderr).toBe(0);
    expect(run.stderr).toBe("");
  }
  expect(second.stdout).toBe(first.stdout);
  expect(normalizeOutput(first.stdout)).toEqual(repeatOutput());
  expect(lines(first.stdout).filter((line) => line.endsWith(": already present"))).toHaveLength(17);
  expect(first.stdout).not.toContain(": created");
  expect(first.stdout).toContain("Audit events written: 0");
  expect(first.stdout).not.toContain("#token=");
  expectNoWrite(before);
});

test("AC5 TC-5-2: a password a user changed is kept by every later seed", async () => {
  const uid = userId(MEKONG.id, "son.hoang@mekongdevworks.example");
  const email = "son.hoang@mekongdevworks.example";
  const saved = saveCredential(MEKONG.id, uid);
  const keep = auditIdsOf(MEKONG.id, uid);
  const hashBefore = passwordHashOf(MEKONG.id, uid);
  expect(saved).not.toBeNull();
  const changed = newPassword();
  try {
    const issued = cli(["user", "link", "--org", MEKONG.id, "--email", email]);
    expect(issued.status, issued.stderr).toBe(0);
    const link = parseLink(lines(issued.stdout)[0]);
    const set = await new ApiSession().setPassword(link.token, changed);
    expect(set.status, set.text).toBe(204);
    const hashChanged = passwordHashOf(MEKONG.id, uid);
    expect(hashChanged).not.toBe(hashBefore);

    const run = seed("seed after a password change");
    expect(run.status, run.stderr).toBe(0);
    expect(normalizeOutput(run.stdout)).toEqual(repeatOutput());
    expect(passwordHashOf(MEKONG.id, uid), "the changed hash is kept").toBe(hashChanged);

    forgetSession(email);
    expect((await new ApiSession().signIn(email, changed)).status).toBe(200);
    expectDetail(await new ApiSession().signIn(email, PASSWORD), 401, "invalid_credentials");
  } finally {
    restoreCredential(MEKONG.id, uid, saved);
    sql(`delete from set_password_tokens where org_id = '${MEKONG.id}' and user_id = '${uid}'`);
    sql(`delete from admin_sessions where org_id = '${MEKONG.id}' and user_id = '${uid}'`);
    deleteAuditExcept(MEKONG.id, uid, keep);
    forgetSession(email);
  }
  expect(passwordHashOf(MEKONG.id, uid)).toBe(hashBefore);
  expect(auditIdsOf(MEKONG.id, uid).sort()).toEqual(keep.sort());
});

test("AC5 TC-5-3: an existing seeded account without a credential gets the shared password; nobody else changes", async () => {
  const email = "phuc.luong@mekongdevworks.example";
  const uid = userId(MEKONG.id, email);
  const saved = saveCredential(MEKONG.id, uid);
  const keep = auditIdsOf(MEKONG.id, uid);
  const hashBefore = passwordHashOf(MEKONG.id, uid);
  const others = rows(
    `select user_id::text || '|' || password_hash from user_credentials where org_id in (${ORG_LIST}) and user_id <> '${uid}'`,
  ).sort();
  expect(saved).not.toBeNull();
  try {
    restoreCredential(MEKONG.id, uid, null);
    const run = seed("seed with one missing credential");
    expect(run.status, run.stderr).toBe(0);
    const out = normalizeOutput(run.stdout);
    expect(out.filter((line) => line.endsWith(": created"))).toEqual([]);
    expect(out).toContain("  Shared test password applied to 1 of 10 accounts");
    expect(out).toContain("  Shared test password applied to 0 of 1 accounts");
    expect(passwordHashOf(MEKONG.id, uid)).not.toBeNull();
    // Every other credential is byte-for-byte unchanged.
    expect(
      rows(
        `select user_id::text || '|' || password_hash from user_credentials where org_id in (${ORG_LIST}) and user_id <> '${uid}'`,
      ).sort(),
    ).toEqual(others);
    forgetSession(email);
    const signed = new ApiSession();
    const result = await signed.signIn(email, PASSWORD);
    expect(result.status, result.text).toBe(200);
    expect(result.json).toEqual({ default_workspace_id: idOfWorkspace("mekong", "Engineering") });
  } finally {
    restoreCredential(MEKONG.id, uid, saved);
    sql(`delete from admin_sessions where org_id = '${MEKONG.id}' and user_id = '${uid}'`);
    deleteAuditExcept(MEKONG.id, uid, keep);
    forgetSession(email);
  }
  expect(passwordHashOf(MEKONG.id, uid)).toBe(hashBefore);
});

test("AC5 TC-5-4: a user created outside the manifest never gets the shared password from a later seed", async () => {
  try {
    const user = inviteUser({
      label: `${MARK_94}outside`,
      role: "viewer",
      workspaceId: peopleOpsId(),
    });
    const before = snapshot();
    const run = seed("seed with an outside user");
    expect(run.status, run.stderr).toBe(0);
    expect(normalizeOutput(run.stdout)).toEqual(repeatOutput());
    expect(snapshot()).toEqual(before);
    expect(
      rows(
        `select count(*) from user_credentials where org_id = '${MEKONG.id}' and user_id = '${user.id}'`,
      ),
    ).toEqual(["0"]);
    expectDetail(await new ApiSession().signIn(user.email, PASSWORD), 401, "invalid_credentials");
  } finally {
    cleanup();
  }
});

test("AC5 TC-5-5: outside local or test the seed refuses with exit code 2 before any password check or write", async () => {
  const before = snapshot();
  const cases: Record<string, string>[] = [
    { EI_AI_ENV: "production" },
    { EI_AI_ENV: "production", EI_AI_SEED_PASSWORD: PASSWORD },
    { EI_AI_ENV: "production", EI_AI_SEED_PASSWORD: "" },
    { EI_AI_ENV: "production", EI_AI_SEED_PASSWORD: "x".repeat(200) },
    { EI_AI_ENV: "staging", EI_AI_SEED_PASSWORD: PASSWORD },
    { EI_AI_ENV: "", EI_AI_SEED_PASSWORD: PASSWORD },
    { EI_AI_ENV: "Production", EI_AI_SEED_PASSWORD: PASSWORD },
  ];
  for (const env of cases) {
    const run = seedDirect(env, `refused ${env.EI_AI_ENV}`);
    const label = `EI_AI_ENV=${env.EI_AI_ENV}`;
    expect(run.status, label).toBe(2);
    expect(run.stdout.trim(), label).toBe("");
    expect(lines(run.stderr), label).toEqual(SEED_REFUSED_LINES);
  }
  expectNoWrite(before);
  // `local` and `test` both run (a second run creates nothing).
  for (const value of ["local", "test"]) {
    const run = seedDirect({ EI_AI_ENV: value, EI_AI_SEED_PASSWORD: PASSWORD }, `env ${value}`);
    expect(run.status, `EI_AI_ENV=${value}: ${run.stderr}`).toBe(0);
    expect(normalizeOutput(run.stdout)).toEqual(repeatOutput());
  }
  expectNoWrite(before);
});

test("AC5 TC-5-6: a missing, empty or over-long password is a configuration error that writes nothing", async () => {
  const before = snapshot();
  const empty = seedDirect({ EI_AI_ENV: "local", EI_AI_SEED_PASSWORD: "" }, "empty password");
  expect(empty.status).toBe(1);
  expect(empty.stdout.trim()).toBe("");
  expect(lines(empty.stderr)).toEqual([PASSWORD_MISSING]);

  const tooLong = "y".repeat(129);
  const long = seedDirect(
    { EI_AI_ENV: "local", EI_AI_SEED_PASSWORD: tooLong },
    "129-character password",
  );
  expect(long.status).toBe(1);
  expect(long.stdout.trim()).toBe("");
  expect(lines(long.stderr)).toEqual([PASSWORD_TOO_LONG]);
  expect(long.stderr).not.toContain(tooLong);
  expectNoWrite(before);

  // 128 characters is the boundary that is still accepted (nothing needs a password: nothing is applied).
  const edge = seedDirect(
    { EI_AI_ENV: "local", EI_AI_SEED_PASSWORD: "y".repeat(128) },
    "128-character password",
  );
  expect(edge.status, edge.stderr).toBe(0);
  expect(normalizeOutput(edge.stdout)).toEqual(repeatOutput());
  expectNoWrite(before);
});

// ---------------------------------------------------------------------------------------------
// AC6 No secret leaks
// ---------------------------------------------------------------------------------------------

test("AC6: the password is never printed in seed output, logs or audit rows and is stored hashed like any other credential", async () => {
  expect(capturedOutputs.length, "seed outputs were captured").toBeGreaterThan(4);
  for (const { label, text } of capturedOutputs) {
    expect(text, label).not.toContain(PASSWORD);
    expect(text, label).not.toMatch(/\$argon2/);
    expect(text, label).not.toContain("#token=");
  }
  expect(fresh.stdout).toContain("Shared test password applied to 10 of 10 accounts");
  expect(fresh.stdout).toContain("Shared test password applied to 1 of 1 accounts");

  // Service logs of the whole run: sign-ins, seeds and failures.
  for (const service of ["api", "admin"]) {
    expect(serviceLogs(service), `${service} container log`).not.toContain(PASSWORD);
  }
  expect(apiLogs()).not.toMatch(/\$argon2id\$/);

  // Database: no tenant row but the credential table holds the value; the hash is argon2id and unique.
  expect(rowsContaining(PASSWORD), "tenant rows that contain the password").toEqual([]);
  expect(
    rows(
      `select count(*) from audit_events where org_id in (${ORG_LIST}) and position('${PW_SQL}' in row_to_json(audit_events)::text) > 0`,
    ),
  ).toEqual(["0"]);
  expect(
    rows(
      `select count(*) from user_credentials where org_id in (${ORG_LIST}) and password_hash not like '$argon2id$%'`,
    ),
  ).toEqual(["0"]);
  expect(
    rows(
      `select count(distinct password_hash) || '|' || count(*) from user_credentials where org_id in (${ORG_LIST})`,
    ),
  ).toEqual(["11|11"]);
  expect(
    rows(
      `select count(*) from user_credentials where org_id in (${ORG_LIST}) and position('${PW_SQL}' in password_hash) > 0`,
    ),
  ).toEqual(["0"]);
  const actors = rows(
    `select distinct actor from audit_events where org_id in (${ORG_LIST}) and action in (${SEED_ACTIONS.map((a) => `'${a}'`).join(", ")})`,
  );
  expect(actors).toEqual(["platform-operator"]);

  // "Like any other credential": the hash of a seeded account and of a person who set a password share
  // the algorithm and its cost parameters.
  const peopleOps = peopleOpsId();
  try {
    const user = inviteUser({ label: `${MARK_94}hash`, role: "viewer", workspaceId: peopleOps });
    const set = await new ApiSession().setPassword(user.link.token, "Qa94-hash-0123");
    expect(set.status, set.text).toBe(204);
    const own = rows(
      `select password_hash from user_credentials where org_id = '${MEKONG.id}' and user_id = '${user.id}'`,
    )[0] as string;
    const seeded = rows(
      `select password_hash from user_credentials where org_id = '${MEKONG.id}' and user_id = '${userId(MEKONG.id, "linh.tran@mekongdevworks.example")}'`,
    )[0] as string;
    const params = (hash: string) => hash.split("$").slice(0, 4).join("$");
    expect(params(seeded)).toBe(params(own));
    expect(seeded).not.toBe(own);
  } finally {
    cleanup();
  }
});

test("AC6 TC-6-2: the default lives only in .env.example; the product source never hard-codes the password and .env is untracked", async () => {
  const example = dotenvValue(path.join(ROOT, ".env.example"));
  expect(example, ".env.example documents EI_AI_SEED_PASSWORD").toBeTruthy();
  const exampleText = fs.readFileSync(path.join(ROOT, ".env.example"), "utf8");
  expect(exampleText.match(/^EI_AI_SEED_PASSWORD=/gm), "exactly one assignment").toHaveLength(1);
  expect(
    (example as string).length,
    "documented default is shorter than the 12-character policy",
  ).toBeLessThan(12);
  expect(example, "not a generated placeholder").not.toBe("__GENERATED__");

  const result = spawnSync(
    "git",
    [
      "grep",
      "-n",
      "-F",
      "-e",
      PASSWORD,
      "--",
      "backend/src",
      "apps",
      "packages",
      "scripts",
      "compose.yaml",
      "package.json",
      ".github",
      ":(exclude)**/*.test.*",
      ":(exclude)**/__tests__/**",
      ":(exclude)**/node_modules/**",
    ],
    { cwd: ROOT, encoding: "utf8" },
  );
  expect(result.status, `product files that contain the password:\n${result.stdout}`).toBe(1);

  const tracked = spawnSync("git", ["ls-files", ".env"], { cwd: ROOT, encoding: "utf8" });
  expect(tracked.stdout.trim()).toBe("");
});

// ---------------------------------------------------------------------------------------------
// AC7 README and its check
// ---------------------------------------------------------------------------------------------

type Table = string[][];

function sectionOf(text: string, heading: string, level: "## " | "### "): string {
  const all = text.replace(/\r\n/g, "\n").split("\n");
  const start = all.findIndex((line) => line.trim() === `${level}${heading}`);
  if (start < 0) return "";
  const next = all.findIndex(
    (line, index) => index > start && line.startsWith(level) && !line.startsWith(`${level}#`),
  );
  return all.slice(start, next < 0 ? undefined : next).join("\n");
}

function tableOf(text: string): Table {
  return text
    .split("\n")
    .filter((line) => line.trim().startsWith("|") && !/^\|[\s:|-]+\|?$/.test(line.trim()))
    .map((line) =>
      line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim().replace(/`/g, "")),
    );
}

function runCheck(readme?: string): { status: number | null; output: string } {
  const env: NodeJS.ProcessEnv = { ...process.env, NODE_TEST_CONTEXT: undefined };
  if (readme !== undefined) env.SEED_README_FILE = readme;
  const result = spawnSync(process.execPath, ["--test", "scripts/checks/seed-data.test.mjs"], {
    cwd: ROOT,
    encoding: "utf8",
    env,
  });
  return { status: result.status, output: `${result.stdout}${result.stderr}` };
}

test("AC7: docs/dev/seed-data.md lists every Organization, Workspace, account, the password, collection and folder exactly as seeded", async () => {
  const file = readmePath();
  expect(fs.existsSync(file), "docs/dev/seed-data.md exists").toBe(true);
  const text = fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n");

  for (const heading of [
    "Shared test password",
    "Sign-in and Organizations",
    "Not seeded yet",
    "Extending the seed",
  ]) {
    expect(sectionOf(text, heading, "## "), `section ${heading}`).not.toBe("");
  }
  expect(text).toContain("npm run seed");
  expect(text).toContain("npm run reset");
  const passwordSection = sectionOf(text, "Shared test password", "## ");
  expect(passwordSection).toContain("EI_AI_SEED_PASSWORD");
  expect(passwordSection).toContain(`\`${PASSWORD}\``);
  expect(passwordSection).toMatch(/12/);
  expect(sectionOf(text, "Sign-in and Organizations", "## ")).toContain(SYSADMIN_EMAIL);
  expect(sectionOf(text, "Sign-in and Organizations", "## ")).toContain(
    "ngan.trinh@songhanretail.example",
  );
  expect(text).toMatch(/platform_admin[^\n]*(planned|not stored|not seeded)/i);

  for (const org of ["mekong", "songhan"] as const) {
    const section = sectionOf(text, ORGS[org].name, "## ");
    expect(section, `section for ${ORGS[org].name}`).not.toBe("");

    const workspaces = tableOf(sectionOf(section, "Workspaces", "### "));
    expect(
      workspaces
        .slice(1)
        .map((row) => row[0])
        .sort(),
      `${ORGS[org].name}: Workspaces`,
    ).toEqual([...ORGS[org].workspaces].sort());

    const accounts = tableOf(sectionOf(section, "Accounts", "### "));
    const header = accounts[0] as string[];
    expect(header.slice(0, 3)).toEqual(["Name", "Email", "Organization role"]);
    expect(header).toContain("Shared password");
    expect(header).toContain("What it can do");
    for (const account of membersOf(org)) {
      const row = accounts.find((cells) => cells[1] === account.email);
      expect(row, `${account.email} is listed in ${ORGS[org].name}`).toBeDefined();
      expect(row?.[0]).toContain(account.name);
      expect(row?.[2], `${account.email}: Organization role`).toBe(account.orgRole ?? "—");
      for (const workspace of ORGS[org].workspaces) {
        const column = header.findIndex((cell) => cell === `Role in ${workspace}`);
        expect(column, `column "Role in ${workspace}"`).toBeGreaterThan(2);
        expect(row?.[column], `${account.email} in ${workspace}`).toBe(
          account.roles[workspace] ?? "—",
        );
      }
      const shared = header.indexOf("Shared password");
      expect(row?.[shared], `${account.email}: shared password`).toMatch(
        account.shared ? /^yes/i : /^no/i,
      );
    }
    expect(accounts.slice(1), `${ORGS[org].name}: account rows`).toHaveLength(
      membersOf(org).length,
    );
    if (org === "mekong") {
      const sysadminRow = accounts.find((cells) => cells[1] === SYSADMIN_EMAIL);
      expect(sysadminRow?.join(" ")).toMatch(/platform_admin/);
      expect(sysadminRow?.join(" ")).toMatch(/planned|not stored/i);
    }

    const collections = tableOf(sectionOf(section, "Collections", "### "));
    expect((collections[0] as string[]).slice(0, 3)).toEqual([
      "Workspace",
      "Collection",
      "Subtitle",
    ]);
    const expectedCollections = collectionsOf(org);
    expect(collections.slice(1), `${ORGS[org].name}: collection rows`).toHaveLength(
      expectedCollections.length,
    );
    for (const spec of expectedCollections) {
      const row = collections.find(
        (cells) => cells[0] === spec.workspace && cells[1] === spec.name,
      );
      expect(row, `collection ${spec.workspace} / ${spec.name}`).toBeDefined();
      expect(row?.join(" | ")).toContain(spec.subtitle ?? "—");
      const cells = row?.join(" | ") ?? "";
      for (const group of spec.groups) expect(cells, `${spec.name}: group`).toContain(group);
      expect(cells, `${spec.name}: who can read`).toMatch(new RegExp(spec.access, "i"));
      if (spec.localOnly) expect(cells, `${spec.name}: data handling`).toMatch(/local/i);
    }

    const folders = tableOf(sectionOf(section, "Folders", "### "));
    expect(folders[0]).toEqual(["Workspace", "Collection", "Folder"]);
    const expectedFolders = expectedCollections.flatMap((spec) =>
      spec.folders.map(
        (folder) => `${spec.workspace}|${spec.name}|${folder.split("/").join(" / ")}`,
      ),
    );
    expect(
      sorted(folders.slice(1).map((cells) => cells.slice(0, 3).join("|"))),
      `${ORGS[org].name}: folders`,
    ).toEqual(sorted(expectedFolders));
  }

  // The root README "Seed data" section links the file.
  const root = fs.readFileSync(path.join(ROOT, "README.md"), "utf8");
  expect(sectionOf(root, "Seed data", "## ")).toContain("docs/dev/seed-data.md");
  // The page does not use placeholder text either.
  expect(text).not.toMatch(/\b(lorem|foo)\b/i);
});

test("AC7 TC-7-2: the README check passes on the real README and fails, naming the row, when a role, account, folder or collection differs", async () => {
  const base = runCheck();
  expect(base.status, base.output).toBe(0);

  const original = fs.readFileSync(readmePath(), "utf8").replace(/\r\n/g, "\n");
  const dir = path.join(ROOT, ".work", "EA-94", "tmp");
  fs.mkdirSync(dir, { recursive: true });

  const mutate = (name: string, change: (text: string) => string, key: string) => {
    const mutated = change(original);
    expect(mutated, `mutation ${name} changes the README`).not.toBe(original);
    const copy = path.join(dir, `seed-data-${name}-${RUN}.md`);
    fs.writeFileSync(copy, mutated);
    try {
      const result = runCheck(copy);
      expect(result.status, `${name}: the check must fail\n${result.output}`).not.toBe(0);
      expect(result.output, `${name}: the failure names the row`).toContain(key);
    } finally {
      fs.rmSync(copy, { force: true });
    }
  };
  const editLine = (
    text: string,
    needles: string[],
    edit: (line: string) => string | null,
  ): string =>
    text
      .split("\n")
      .flatMap((line) => (needles.every((needle) => line.includes(needle)) ? [edit(line)] : [line]))
      .filter((line): line is string => line !== null)
      .join("\n");

  try {
    mutate(
      "role",
      (text) =>
        editLine(text, ["quang.le@mekongdevworks.example"], (line) =>
          line.replace("developer", "viewer"),
        ),
      "quang.le@mekongdevworks.example",
    );
    mutate(
      "account",
      (text) => editLine(text, ["ha.vu@mekongdevworks.example"], () => null),
      "ha.vu@mekongdevworks.example",
    );
    mutate(
      "songhan-account",
      (text) =>
        editLine(text, ["ngan.trinh@songhanretail.example", "|"], () => null).replace(
          /\n{3,}/g,
          "\n\n",
        ),
      "ngan.trinh@songhanretail.example",
    );
    mutate(
      "folder",
      (text) => editLine(text, ["Labor contracts", "|"], () => null),
      "Labor contracts",
    );
    mutate(
      "folder-added",
      (text) =>
        editLine(
          text,
          ["Leaving the company", "|"],
          (line) => `${line}\n${line.replace("Leaving the company", "Parental leave")}`,
        ),
      "Parental leave",
    );
    mutate(
      "collection",
      (text) =>
        editLine(text, ["Runbooks", "on-call"], (line) => line.replace("Runbooks", "Runbook")),
      "Runbooks",
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }

  // A missing README fails the check too.
  const missing = runCheck(path.join(ROOT, ".work", "EA-94", `no-such-readme-${RUN}.md`));
  expect(missing.status, missing.output).not.toBe(0);
});

test("AC7 TC-7-3: the README check runs in `npm test` and CI", async () => {
  expect(fs.existsSync(path.join(ROOT, "scripts", "checks", "seed-data.test.mjs"))).toBe(true);
  const config = fs.readFileSync(path.join(ROOT, "scripts", "node-checks.config.mjs"), "utf8");
  expect(config, "node-checks config has a pattern that covers scripts/checks/*.test.mjs").toMatch(
    /scripts\/(\*\*|checks)\/(\*\*\/)?[^"'`]*\.test\.mjs/,
  );
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8")) as {
    scripts: Record<string, string>;
  };
  expect(pkg.scripts.test).toContain("run-node-checks");
  const workflows = fs.readdirSync(path.join(ROOT, ".github", "workflows"));
  const ci = workflows
    .map((file) => fs.readFileSync(path.join(ROOT, ".github", "workflows", file), "utf8"))
    .join("\n");
  expect(ci).toMatch(/tasks\.mjs|npm run check|npm test|run-node-checks|node-checks/);
});
