// EA-32 (KB-01): Collections and Folders with 3 access levels and a "Local model only" flag.
// Black-box specs written from .work/EA-32/contract.md and ticket.md only. Runs against a running,
// migrated and seeded stack:
//   npm run up -- --no-model && npm run seed && npm run e2e -- e2e/knowledge/EA-32-collections.spec.ts
// Data: own Workspaces `QA22 qa-EA32-<run> ...`, users `qa22.qa-ea32-<run>.<label>@...`, collections
// named with the marker `qa-EA32-<run>` (except "Employee Handbook" in the empty Workspace of AC1).
// Nothing in People Ops is written; the seed rows are only read. cleanupAll() removes everything and the
// afterAll hook proves the row counts equal the counts before the run.
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import {
  ApiSession,
  RUN,
  addMember,
  apiLogsSince,
  contrastRatio,
  createForeignOrg,
  createWorkspace,
  expectDetail,
  expectSameAnswer,
  newPassword,
  peopleOpsId,
  watch,
  type ForeignOrg,
  type QaUser,
} from "../support/ea22";
import { signedInApi, withSession } from "../support/ea23";
import {
  COPY,
  FOLDER_KEYS,
  ITEM_KEYS,
  MARK,
  SCREENSHOTS_32,
  SEED,
  auditOf,
  auditValues,
  cleanupAll,
  collectionsPath,
  counts,
  createCollection,
  createFolder,
  createMember,
  expectAlert,
  fillCollectionForm,
  folderRow,
  json,
  listedNames,
  markerRows,
  mustCreateCollection,
  mustCreateFolder,
  mutations,
  openDetail,
  openKnowledge,
  openNewCollection,
  openSettings,
  radioOf,
  rowCount,
  rowOf,
  track,
  waitApi,
  withoutStatuses,
  type CollectionDetail,
  type CollectionItem,
  type Counts,
  type FolderItem,
} from "../support/ea32";

test.describe.configure({ mode: "serial", timeout: 240_000 });

let peopleOps = "";
let wsA = ""; // starts empty: AC1 creates the first collection here
let wsEmpty = ""; // never written: AC7
let wsOther = ""; // a second Workspace of the same Organization
let foreign: ForeignOrg;
let baseline: Counts | undefined;
let seedBefore = "";
const users = new Map<string, QaUser>();
const sessions = new Map<string, ApiSession>();
const ids = new Map<string, string>(); // named collection ids shared between tests
const smallTargets: string[] = []; // buttons below 24 x 24 px, collected by the folder test

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

/** The owner of the other Organization. */
async function foreignOwner(): Promise<ApiSession> {
  const cached = sessions.get("foreignOwner");
  if (cached) return cached;
  const owner = new ApiSession();
  const password = newPassword();
  expect((await owner.setPassword(foreign.link.token, password)).status).toBe(204);
  expect((await owner.signIn(foreign.ownerEmail, password)).status).toBeLessThan(300);
  sessions.set("foreignOwner", owner);
  return owner;
}

function idOf(key: string): string {
  const found = ids.get(key);
  if (!found) throw new Error(`no collection ${key}`);
  return found;
}

async function listOf(session: ApiSession, workspaceId: string): Promise<CollectionItem[]> {
  const result = await session.send("GET", collectionsPath(workspaceId));
  expect(result.status, result.text).toBe(200);
  return json<{ collections: CollectionItem[] }>(result).collections;
}

async function detailOf(
  session: ApiSession,
  workspaceId: string,
  collectionId: string,
): Promise<CollectionDetail> {
  const result = await session.send("GET", `${collectionsPath(workspaceId)}/${collectionId}`);
  expect(result.status, result.text).toBe(200);
  return json<CollectionDetail>(result);
}

test.beforeAll(async () => {
  test.setTimeout(420_000);
  await cleanupAll(); // leftovers of a crashed earlier run
  fs.mkdirSync(SCREENSHOTS_32, { recursive: true });
  baseline = counts();
  peopleOps = peopleOpsId();
  wsA = createWorkspace(`QA22 ${MARK} A`);
  wsEmpty = createWorkspace(`QA22 ${MARK} Empty`);
  wsOther = createWorkspace(`QA22 ${MARK} Other`);
  foreign = createForeignOrg();

  const make = async (key: string, role: string, workspaceId: string) => {
    users.set(key, await createMember({ label: key.toLowerCase(), role, workspaceId }));
  };
  await make("admin", "workspace_admin", wsA);
  await make("ke", "knowledge_editor", wsA);
  await make("builder", "builder", wsA);
  await make("viewer", "viewer", wsA);
  await make("otherAdmin", "workspace_admin", wsOther);
  await make("poAdmin", "workspace_admin", peopleOps);
  addMember(wsEmpty, user("admin"), "workspace_admin");
  addMember(wsEmpty, user("ke"), "knowledge_editor");

  // The seed rows of People Ops as they are now (AC8 reads them; nothing may change them).
  seedBefore = JSON.stringify(await listOf(await api("poAdmin"), peopleOps));
});

test.afterAll(async () => {
  expect(
    JSON.stringify(await listOf(await api("poAdmin"), peopleOps)),
    "People Ops unchanged",
  ).toBe(seedBefore);
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the EA-32 marker left behind").toEqual([]);
});

// ---------------------------------------------------------------------------------------------
// AC1 Create
// ---------------------------------------------------------------------------------------------

test('AC1: a Knowledge Editor creates "Employee Handbook" as Authenticated and sees it listed with the Authenticated badge and 0 documents', async ({
  browser,
}) => {
  const ke = user("ke");
  await withSession(browser, await api("ke"), async (page) => {
    const seen = watch(page);
    await openKnowledge(page, wsA);
    await expect(page.getByTestId("collections-empty")).toBeVisible(); // precondition: no collection yet
    const dialog = await openNewCollection(page);
    await expect(dialog).toContainText("New collection");
    await expect(radioOf(page, "Authenticated")).toBeChecked(); // default
    await fillCollectionForm(page, { name: "Employee Handbook" });
    const posted = waitApi(page, "POST", new RegExp(`/api/workspaces/${wsA}/collections$`));
    await dialog.getByRole("button", { name: "Create collection" }).click();
    expect((await posted).status()).toBe(201);
    await expect(dialog).toBeHidden();

    await expect(page.getByTestId("knowledge-status")).toHaveText("Employee Handbook was created.");
    const row = rowOf(page, "Employee Handbook");
    await expect(row).toHaveCount(1);
    const badge = row.getByTestId("access-badge");
    await expect(badge).toHaveText("Authenticated");
    await expect(badge).toHaveAttribute("data-access", "authenticated");
    await expect(row.getByTestId("document-count")).toHaveText("0");
    await expect(row.getByTestId("collection-status")).toHaveText("No documents");
    await expect(row.getByTestId("data-handling")).toHaveText("Any allowed model");
    await expect(row.getByTestId("used-by")).toHaveText("Not used yet");
    await expect(page.getByTestId("collections-empty")).toHaveCount(0);
    await expect(page.getByTestId("collections-table")).toBeVisible();
    await expect(page.getByTestId("new-collection")).toHaveCount(1); // now in the header only

    const id = (await row.getAttribute("data-collection-id")) as string;
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
    ids.set("handbook", id);
    track(id, wsA, await api("ke"));
    expect(auditOf(id)).toEqual([
      {
        actor: `user:${ke.id}`,
        action: "collection.created",
        target_type: "collection",
        workspace_id: wsA,
        old_value: null,
        new_value: "authenticated",
      },
    ]);
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });
  const item = (await listOf(await api("ke"), wsA)).find((entry) => entry.id === idOf("handbook"));
  expect(item).toMatchObject({
    name: "Employee Handbook",
    access_level: "authenticated",
    groups: [],
    local_only: false,
    documents: { total: 0, ready: 0, processing: 0, needs_attention: 0 },
    used_by: [],
  });
});

test("AC1 TC-1-2: the create API returns the CollectionItem shape, normalises names, subtitles and groups, and keeps the list ordered by name", async () => {
  const ke = await api("ke");
  const nfc = "QUẢN LÝ"; // QUẢN LÝ
  const nfd = "Quản lý "; // Quản lý, decomposed, trailing space
  const created = await createCollection(ke, wsA, {
    name: `  Norm ${MARK}  `,
    subtitle: "   ",
    access_level: "restricted",
    groups: [" Managers ", "managers", nfc, nfd],
  });
  expect(created.status, created.text).toBe(201);
  const item = json<CollectionItem>(created);
  expect(Object.keys(item).sort()).toEqual(ITEM_KEYS);
  expect(item.name).toBe(`Norm ${MARK}`);
  expect(item.subtitle).toBeNull();
  expect(item.groups).toEqual(["managers", "quản lý"]); // trimmed, NFC, lower case, no duplicates
  expect(item.local_only).toBe(false);
  expect(item.documents).toEqual({ total: 0, ready: 0, processing: 0, needs_attention: 0 });
  expect(item.used_by).toEqual([]);
  expect(Number.isNaN(Date.parse(item.created_at))).toBe(false);
  expect(Number.isNaN(Date.parse(item.updated_at))).toBe(false);

  const detail = await detailOf(ke, wsA, item.id);
  expect(Object.keys(detail).sort()).toEqual([...ITEM_KEYS, "folders"].sort());
  expect(detail.folders).toEqual([]);

  // The list is ordered by name ignoring case: Alpha, beta, Zeta whatever the creation order.
  await mustCreateCollection(ke, wsA, { name: `Zeta ${MARK}`, access_level: "authenticated" });
  await mustCreateCollection(ke, wsA, { name: `beta ${MARK}`, access_level: "authenticated" });
  await mustCreateCollection(ke, wsA, { name: `Alpha ${MARK}`, access_level: "authenticated" });
  const names = (await listOf(ke, wsA))
    .map((entry) => entry.name)
    .filter((name) => /^(Alpha|beta|Zeta) /.test(name));
  expect(names).toEqual([`Alpha ${MARK}`, `beta ${MARK}`, `Zeta ${MARK}`]);
  expect(Object.keys(json<object>(await ke.send("GET", collectionsPath(wsA))))).toEqual([
    "collections",
  ]);

  // Boundaries: 200 characters are accepted for name and subtitle.
  const longName = `${"x".repeat(200 - MARK.length - 1)} ${MARK}`;
  expect(longName).toHaveLength(200);
  const long = await createCollection(ke, wsA, {
    name: longName,
    subtitle: "y".repeat(200),
    access_level: "authenticated",
  });
  expect(long.status, long.text).toBe(201);

  // A group of 64 characters and a list of 20 groups are accepted.
  const manyGroups = Array.from({ length: 20 }, (_, index) => `g${index}`);
  expect(
    (
      await createCollection(ke, wsA, {
        name: `Groups64 ${MARK}`,
        access_level: "restricted",
        groups: ["g".repeat(64), ...manyGroups.slice(1)],
      })
    ).status,
  ).toBe(201);
});

test("AC1 TC-1-3: the create API validates the body (422 invalid_request, input never echoed) and refuses duplicate names (409 name_taken, case-insensitive)", async () => {
  const ke = await api("ke");
  const secret = `Echo ${MARK}`;
  const bad: [string, Record<string, unknown>][] = [
    ["empty name", { name: "", access_level: "authenticated" }],
    ["blank name", { name: "   ", access_level: "authenticated" }],
    ["201-character name", { name: "n".repeat(201), access_level: "authenticated" }],
    [
      "201-character subtitle",
      { name: secret, subtitle: "s".repeat(201), access_level: "authenticated" },
    ],
    ["missing name", { access_level: "authenticated" }],
    ["missing access_level", { name: secret }],
    ["unknown access_level", { name: secret, access_level: "internal" }],
    ["upper-case access_level", { name: secret, access_level: "Public" }],
    ["name is a number", { name: 5, access_level: "authenticated" }],
    ["groups with authenticated", { name: secret, access_level: "authenticated", groups: ["hr"] }],
    ["groups with public", { name: secret, access_level: "public", groups: ["hr"] }],
    ["local_only is a string", { name: secret, access_level: "authenticated", local_only: "yes" }],
    ["extra id", { name: secret, access_level: "authenticated", id: randomUUID() }],
    ["extra org_id", { name: secret, access_level: "authenticated", org_id: foreign.orgId }],
    [
      "extra organization_id",
      { name: secret, access_level: "authenticated", organization_id: foreign.orgId },
    ],
    ["extra workspace_id", { name: secret, access_level: "authenticated", workspace_id: wsOther }],
    [
      "control character in the name",
      { name: `bad\u0007${secret}`, access_level: "authenticated" },
    ],
    ["NUL in the name", { name: `bad\u0000${secret}`, access_level: "authenticated" }],
    [
      "control character in the subtitle",
      { name: secret, subtitle: "x\u0007y", access_level: "authenticated" },
    ],
  ];
  for (const [label, body] of bad) {
    // Public needs the admin permission, which is checked before the body: use the admin for it.
    const caller = body.access_level === "public" ? await api("admin") : ke;
    const result = await caller.send("POST", collectionsPath(wsA), { json: body });
    expectDetail(result, 422, "invalid_request");
    expect(result.text, `${label}: input is not echoed`).not.toContain(secret);
  }
  expectDetail(
    await ke.send("POST", collectionsPath(wsA), { rawBody: "{not json" }),
    422,
    "invalid_request",
  );
  expectDetail(await ke.send("POST", collectionsPath(wsA), { json: {} }), 422, "invalid_request");
  expect((await listOf(ke, wsA)).filter((entry) => entry.name.includes("Echo"))).toEqual([]);

  // Duplicates: same name in the Workspace, ignoring case and surrounding spaces.
  for (const name of ["Employee Handbook", "employee handbook", "  EMPLOYEE HANDBOOK "]) {
    const result = await ke.send("POST", collectionsPath(wsA), {
      json: { name, access_level: "authenticated" },
    });
    expectDetail(result, 409, "name_taken");
  }
  // The same name in another Workspace is fine.
  const otherAdmin = await api("otherAdmin");
  const other = await createCollection(otherAdmin, wsOther, {
    name: "Employee Handbook",
    access_level: "authenticated",
  });
  expect(other.status, other.text).toBe(201);
  ids.set("otherHandbook", json<CollectionItem>(other).id);
  expect(
    (await listOf(ke, wsA)).filter((entry) => entry.name === "Employee Handbook"),
  ).toHaveLength(1);
});

test("AC1 TC-1-4: the create dialog: required name, duplicate message, Escape and Cancel send nothing, markup in a name is shown as text, Vietnamese text is kept", async ({
  browser,
}) => {
  await withSession(browser, await api("ke"), async (page) => {
    const sent = mutations(page);
    const seen = watch(page);
    await openKnowledge(page, wsA);

    // Escape and Cancel close the dialog without a request.
    let dialog = await openNewCollection(page);
    await fillCollectionForm(page, { name: `Never saved ${MARK}` });
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    dialog = await openNewCollection(page);
    await expect(dialog.getByRole("textbox", { name: "Name", exact: true })).toHaveValue(""); // fresh form
    await fillCollectionForm(page, { name: `Never saved ${MARK}` });
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    expect(sent).toEqual([]);
    await expect(rowOf(page, `Never saved ${MARK}`)).toHaveCount(0);

    // The helper texts of the form.
    dialog = await openNewCollection(page);
    await expect(dialog).toContainText(COPY.localHelp);
    await dialog.getByRole("radio", { name: /^Restricted/ }).check();
    await expect(dialog).toContainText(COPY.groupsHelper);
    await dialog.getByRole("button", { name: "Cancel" }).click();

    // A required name: nothing is created with an empty name.
    dialog = await openNewCollection(page);
    await dialog.getByRole("button", { name: "Create collection" }).click();
    await expect(dialog).toBeVisible();
    const afterEmpty = await listOf(await api("ke"), wsA);
    expect(afterEmpty.some((entry) => entry.name.trim() === "")).toBe(false);

    // A duplicate (other case) shows the 409 message and keeps the dialog open.
    await fillCollectionForm(page, { name: "employee handbook" });
    await dialog.getByRole("button", { name: "Create collection" }).click();
    await expectAlert(page, COPY.collectionTaken);
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();

    // Markup in a name and Vietnamese text with diacritics are shown literally.
    const markup = `<b>bold</b> ${MARK}`;
    const vietnamese = `Quy định nội bộ ${MARK}`;
    const subtitle = "Chính sách công ty · phiên bản 2026";
    for (const [name, sub] of [
      [markup, ""],
      [vietnamese, subtitle],
    ] as const) {
      dialog = await openNewCollection(page);
      await fillCollectionForm(page, { name, subtitle: sub });
      await dialog.getByRole("button", { name: "Create collection" }).click();
      await expect(dialog).toBeHidden();
      await expect(page.getByTestId("knowledge-status")).toHaveText(`${name} was created.`);
    }
    const markupRow = rowOf(page, markup);
    await expect(markupRow).toHaveCount(1);
    await expect(markupRow.locator("b")).toHaveCount(0);
    const vietnameseRow = rowOf(page, vietnamese);
    await expect(vietnameseRow).toContainText(subtitle);
    ids.set("vietnamese", (await vietnameseRow.getAttribute("data-collection-id")) as string);
    ids.set("markup", (await markupRow.getAttribute("data-collection-id")) as string);
    track(idOf("vietnamese"), wsA, await api("ke"));
    track(idOf("markup"), wsA, await api("ke"));
    const detail = await detailOf(await api("ke"), wsA, idOf("vietnamese"));
    expect(detail).toMatchObject({ name: vietnamese, subtitle });
    expect(sent.filter((call) => call.method !== "POST")).toEqual([]);
    expect(withoutStatuses(seen.problems, [409])).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------
// AC2 Restricted needs groups
// ---------------------------------------------------------------------------------------------

test('AC2: choosing Restricted without a group shows "At least one group is required" and sends no request; the API answers 422 groups_required', async ({
  browser,
}) => {
  await withSession(browser, await api("ke"), async (page) => {
    const sent = mutations(page);
    const seen = watch(page);
    await openKnowledge(page, wsA);
    const dialog = await openNewCollection(page);
    await expect(dialog.getByRole("textbox", { name: "Groups", exact: true })).toHaveCount(0); // only when Restricted
    await fillCollectionForm(page, { name: `Need groups ${MARK}`, access: "Restricted" });
    await expect(dialog.getByRole("textbox", { name: "Groups", exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Create collection" }).click();
    await expect(page.getByTestId("groups-error")).toHaveText(COPY.groupsRequired);
    await expect(dialog).toBeVisible();
    // The error is announced (role alert or accessible description) and focus is on the Groups input.
    const groupsInput = dialog.getByRole("textbox", { name: "Groups", exact: true });
    await expect(groupsInput).toBeFocused();
    const announced = await page.evaluate(() => {
      const error = document.querySelector('[data-testid="groups-error"]');
      const input = document.querySelector(
        '[data-testid="collection-dialog"] input[aria-describedby]',
      );
      const described = (input?.getAttribute("aria-describedby") ?? "")
        .split(" ")
        .some((id) => id !== "" && document.getElementById(id)?.contains(error ?? null));
      return (
        error?.getAttribute("role") === "alert" ||
        error?.closest("[role=alert]") !== null ||
        described
      );
    });
    expect(announced, "the groups error is announced").toBe(true);
    // Only commas and spaces are still no group.
    await fillCollectionForm(page, { groups: " , ,  " });
    await dialog.getByRole("button", { name: "Create collection" }).click();
    await expect(page.getByTestId("groups-error")).toHaveText(COPY.groupsRequired);
    expect(sent, "no request is sent").toEqual([]);
    expect(
      (await listOf(await api("ke"), wsA)).some((entry) => entry.name.includes("Need groups")),
    ).toBe(false);

    // With groups (any case, spaces, a repeated group) it is created and shown in stored order.
    await fillCollectionForm(page, { groups: " Managers , HR ,managers" });
    const posted = waitApi(page, "POST", new RegExp(`/api/workspaces/${wsA}/collections$`));
    await dialog.getByRole("button", { name: "Create collection" }).click();
    expect((await posted).status()).toBe(201);
    await expect(dialog).toBeHidden();
    const row = rowOf(page, `Need groups ${MARK}`);
    await expect(row.getByTestId("access-badge")).toHaveText("Restricted · managers, hr");
    await expect(row.getByTestId("access-badge")).toHaveAttribute("data-access", "restricted");
    ids.set("restricted", (await row.getAttribute("data-collection-id")) as string);
    track(idOf("restricted"), wsA, await api("ke"));
    expect((await detailOf(await api("ke"), wsA, idOf("restricted"))).groups).toEqual([
      "managers",
      "hr",
    ]);
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });

  // The API: no groups, an empty list, a missing key all give groups_required.
  const ke = await api("ke");
  for (const body of [
    { name: `NoGroups ${MARK}`, access_level: "restricted" },
    { name: `NoGroups ${MARK}`, access_level: "restricted", groups: [] },
  ]) {
    const result = await ke.send("POST", collectionsPath(wsA), { json: body });
    expectDetail(result, 422, "groups_required");
  }
  expect((await listOf(ke, wsA)).some((entry) => entry.name.includes("NoGroups"))).toBe(false);
});

test("AC2 TC-2-2: group names are validated (422 invalid_group) on create and on the access route; the error never echoes them", async () => {
  const ke = await api("ke");
  const admin = await api("admin");
  const secret = `secret-group-${RUN}`;
  const badGroups: [string, string[]][] = [
    ["comma inside a group", [`${secret},two`]],
    ["65 characters", ["g".repeat(65)]],
    ["21 groups", Array.from({ length: 21 }, (_, index) => `g${index}`)],
    ["control character", [`${secret}\u0007`]],
    ["empty after trimming", ["   "]],
  ];
  for (const [label, groups] of badGroups) {
    const result = await ke.send("POST", collectionsPath(wsA), {
      json: { name: `BadGroup ${MARK}`, access_level: "restricted", groups },
    });
    expect(result.status, label).toBe(422);
    expect(
      label === "empty after trimming" ? ["invalid_group", "groups_required"] : ["invalid_group"],
      label,
    ).toContain((result.json as { detail: string }).detail);
    expect(result.text, `${label}: input is not echoed`).not.toContain(secret);
  }
  expect((await listOf(ke, wsA)).some((entry) => entry.name.includes("BadGroup"))).toBe(false);
  // The access route (admin) validates the same way and keeps the collection unchanged.
  const target = idOf("restricted");
  const snapshot = await detailOf(admin, wsA, target);
  expectDetail(
    await admin.send("PUT", `${collectionsPath(wsA)}/${target}/access`, {
      json: { access_level: "restricted", groups: [] },
    }),
    422,
    "groups_required",
  );
  expectDetail(
    await admin.send("PUT", `${collectionsPath(wsA)}/${target}/access`, {
      json: { access_level: "restricted", groups: ["a,b"] },
    }),
    422,
    "invalid_group",
  );
  expectDetail(
    await admin.send("PUT", `${collectionsPath(wsA)}/${target}/access`, {
      json: { access_level: "authenticated", groups: ["hr"] },
    }),
    422,
    "invalid_request",
  );
  expect(await detailOf(admin, wsA, target)).toEqual(snapshot);
});

test("AC2 TC-2-3: the UI shows the invalid-group message under a bad group list and the 'Groups' field keeps what was typed", async ({
  browser,
}) => {
  await withSession(browser, await api("ke"), async (page) => {
    await openKnowledge(page, wsA);
    const dialog = await openNewCollection(page);
    await fillCollectionForm(page, {
      name: `UI bad group ${MARK}`,
      access: "Restricted",
      groups: "g".repeat(65),
    });
    await dialog.getByRole("button", { name: "Create collection" }).click();
    await expectAlert(page, COPY.invalidGroup);
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("textbox", { name: "Groups", exact: true })).toHaveValue(
      "g".repeat(65),
    );
    await dialog.getByRole("button", { name: "Cancel" }).click();
    expect(
      (await listOf(await api("ke"), wsA)).some((entry) => entry.name.includes("UI bad group")),
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------------------------
// AC3 Changing access
// ---------------------------------------------------------------------------------------------

test("AC3: a Knowledge Editor cannot change Public to Restricted (API 403, controls disabled in the UI); a Workspace Admin can, and old to new is audited", async ({
  browser,
}) => {
  const admin = user("admin");
  const ke = await api("ke");
  const adminApi = await api("admin");
  const publicItem = await mustCreateCollection(adminApi, wsA, {
    name: `Public ${MARK}`,
    access_level: "public",
  });
  ids.set("public", publicItem.id);
  const restrictedItem = await mustCreateCollection(adminApi, wsA, {
    name: `Locked groups ${MARK}`,
    access_level: "restricted",
    groups: ["managers"],
  });

  // KE in the UI: radios disabled, note shown, Groups disabled, name and subtitle still editable.
  await withSession(browser, ke, async (page) => {
    await openDetail(page, wsA, publicItem.id);
    let dialog = await openSettings(page);
    await expect(page.getByTestId("access-locked-note")).toHaveText(COPY.lockedNote);
    const radios = dialog.getByRole("radio");
    await expect(radios).toHaveCount(3);
    for (let index = 0; index < 3; index++) await expect(radios.nth(index)).toBeDisabled();
    await expect(radioOf(page, "Public")).toBeChecked();
    await expect(dialog.getByRole("textbox", { name: "Name", exact: true })).toBeEnabled();
    await expect(
      dialog.getByRole("textbox", { name: "Subtitle (optional)", exact: true }),
    ).toBeEnabled();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();

    await openDetail(page, wsA, restrictedItem.id);
    dialog = await openSettings(page);
    const groups = dialog.getByRole("textbox", { name: "Groups", exact: true });
    await expect(groups).toBeVisible();
    await expect(groups).toBeDisabled();
    await expect(groups).toHaveValue("managers");
    await dialog.getByRole("button", { name: "Cancel" }).click();
  });

  // KE through the API: 403, nothing changes, nothing is audited.
  const auditBefore = auditOf(publicItem.id);
  const forbidden = await ke.send("PUT", `${collectionsPath(wsA)}/${publicItem.id}/access`, {
    json: { access_level: "restricted", groups: ["managers"] },
  });
  expectDetail(forbidden, 403, "forbidden");
  expect((await detailOf(ke, wsA, publicItem.id)).access_level).toBe("public");
  expect(auditOf(publicItem.id)).toEqual(auditBefore);

  // The Workspace Admin changes it in the UI.
  await withSession(browser, adminApi, async (page) => {
    const sent = mutations(page);
    const seen = watch(page);
    await openDetail(page, wsA, publicItem.id);
    const dialog = await openSettings(page);
    await expect(page.getByTestId("access-locked-note")).toHaveCount(0);
    await expect(radioOf(page, "Restricted")).toBeEnabled();
    await fillCollectionForm(page, { access: "Restricted" });
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("groups-error")).toHaveText(COPY.groupsRequired); // AC2 on edit
    expect(sent).toEqual([]);
    await fillCollectionForm(page, { groups: "Managers" });
    const put = waitApi(page, "PUT", new RegExp(`/collections/${publicItem.id}/access$`));
    await dialog.getByRole("button", { name: "Save" }).click();
    expect((await put).status()).toBe(200);
    await expect(page.getByTestId("knowledge-status")).toHaveText("Changes saved.");
    await expect(dialog).toBeHidden();
    const badge = page.getByTestId("collection-detail").getByTestId("access-badge");
    await expect(badge).toHaveText("Restricted · managers");
    await expect(badge).toHaveAttribute("data-access", "restricted");
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });
  expect(auditOf(publicItem.id)).toEqual([
    {
      actor: `user:${admin.id}`,
      action: "collection.created",
      target_type: "collection",
      workspace_id: wsA,
      old_value: null,
      new_value: "public",
    },
    {
      actor: `user:${admin.id}`,
      action: "collection.access_changed",
      target_type: "collection",
      workspace_id: wsA,
      old_value: "public",
      new_value: "restricted",
    },
  ]);
});

test("AC3 TC-3-2: the access route for the Workspace Admin: groups changes are audited, the same value writes no event, a Builder is refused like a Knowledge Editor, name and subtitle stay editable for a Knowledge Editor", async ({
  browser,
}) => {
  const adminApi = await api("admin");
  const admin = user("admin");
  const keUser = user("ke");
  const target = idOf("public"); // restricted · managers after AC3
  const route = `${collectionsPath(wsA)}/${target}/access`;

  const same = await adminApi.send("PUT", route, {
    json: { access_level: "restricted", groups: ["managers"] },
  });
  expect(same.status, same.text).toBe(200);
  const afterSame = auditOf(target).length;
  expect(afterSame).toBe(2); // created + access_changed, nothing for the repeat

  const changed = await adminApi.send("PUT", route, {
    json: { access_level: "restricted", groups: ["Managers", "HR"] },
  });
  expect(changed.status, changed.text).toBe(200);
  expect(json<CollectionItem>(changed).groups).toEqual(["managers", "hr"]);
  expect(auditOf(target).slice(2)).toEqual([
    {
      actor: `user:${admin.id}`,
      action: "collection.groups_changed",
      target_type: "collection",
      workspace_id: wsA,
      old_value: "restricted",
      new_value: "restricted",
    },
  ]);
  for (const row of auditOf(target)) {
    expect(row.old_value ?? "").toMatch(/^[a-z_]{0,40}$/);
    expect(row.new_value ?? "").toMatch(/^[a-z_]{0,40}$/);
  }

  const back = await adminApi.send("PUT", route, {
    json: { access_level: "authenticated", groups: [] },
  });
  expect(back.status, back.text).toBe(200);
  expect(json<CollectionItem>(back)).toMatchObject({ access_level: "authenticated", groups: [] });
  expect(auditOf(target).at(-1)).toMatchObject({
    action: "collection.access_changed",
    old_value: "restricted",
    new_value: "authenticated",
  });

  // A Builder holds knowledge.manage but not collections.access.manage.
  const builder = await api("builder");
  expectDetail(
    await builder.send("PUT", route, { json: { access_level: "public", groups: [] } }),
    403,
    "forbidden",
  );
  expectDetail(
    await builder.send("PUT", route, { json: { access_level: "restricted", groups: ["x"] } }),
    403,
    "forbidden",
  );
  expect((await detailOf(adminApi, wsA, target)).access_level).toBe("authenticated");

  // A Knowledge Editor edits the name and subtitle in the UI: one PATCH, no PUT, audited as updated.
  await withSession(browser, await api("ke"), async (page) => {
    const sent = mutations(page);
    await openDetail(page, wsA, target);
    const dialog = await openSettings(page);
    await fillCollectionForm(page, { subtitle: "Updated by the editor" });
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("knowledge-status")).toHaveText("Changes saved.");
    expect(
      sent.some((call) => call.path.endsWith("/access")),
      "no access call",
    ).toBe(false);
    expect(sent.some((call) => call.method === "PATCH")).toBe(true);
  });
  expect(auditOf(target).at(-1)).toEqual({
    actor: `user:${keUser.id}`,
    action: "collection.updated",
    target_type: "collection",
    workspace_id: wsA,
    old_value: null,
    new_value: null,
  });
  const reNamed = await (
    await api("ke")
  ).send("PATCH", `${collectionsPath(wsA)}/${target}`, {
    json: { name: `Public ${MARK}`, subtitle: null },
  });
  expect(reNamed.status, reNamed.text).toBe(200);
  expect(json<CollectionItem>(reNamed).subtitle).toBeNull();
  const noChange = auditOf(target).length;
  expect(
    (
      await (
        await api("ke")
      ).send("PATCH", `${collectionsPath(wsA)}/${target}`, { json: { name: `Public ${MARK}` } })
    ).status,
  ).toBe(200);
  expect(auditOf(target)).toHaveLength(noChange); // the same value again writes no event
});

// ---------------------------------------------------------------------------------------------
// AC4 Making Public
// ---------------------------------------------------------------------------------------------

test("AC4: a Workspace Admin setting a collection to Public gets a confirmation dialog before anything is saved, Cancel sends nothing, and the change is audited", async ({
  browser,
}) => {
  const admin = user("admin");
  const adminApi = await api("admin");
  const item = await mustCreateCollection(adminApi, wsA, {
    name: `Going public ${MARK}`,
    access_level: "authenticated",
  });
  ids.set("goingPublic", item.id);
  await withSession(browser, adminApi, async (page) => {
    const sent = mutations(page);
    const seen = watch(page);
    await openDetail(page, wsA, item.id);
    const dialog = await openSettings(page);
    await fillCollectionForm(page, { access: "Public" });
    await dialog.getByRole("button", { name: "Save" }).click();

    const confirm = page.getByTestId("confirm-public-dialog");
    await expect(confirm).toBeVisible();
    await expect(confirm).toContainText(COPY.publicTitle);
    await expect(confirm).toContainText(COPY.publicBody);
    expect(sent, "the dialog comes before any request").toEqual([]);
    expect((await detailOf(adminApi, wsA, item.id)).access_level).toBe("authenticated");

    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toBeHidden();
    await expect(dialog).toBeVisible(); // back on the form, Public still selected
    expect(
      await page.evaluate(
        () => document.activeElement?.closest('[data-testid="collection-dialog"]') !== null,
      ),
      "focus returns to the form",
    ).toBe(true);
    await expect(radioOf(page, "Public")).toBeChecked();
    expect(sent).toEqual([]);
    expect((await detailOf(adminApi, wsA, item.id)).access_level).toBe("authenticated");
    expect(auditOf(item.id)).toHaveLength(1);

    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(confirm).toBeVisible();
    const put = waitApi(page, "PUT", new RegExp(`/collections/${item.id}/access$`));
    await confirm.getByRole("button", { name: "Make public" }).click();
    expect((await put).status()).toBe(200);
    await expect(page.getByTestId("knowledge-status")).toHaveText("Changes saved.");
    const badge = page.getByTestId("collection-detail").getByTestId("access-badge");
    await expect(badge).toHaveText("Public");
    await expect(badge).toHaveAttribute("data-access", "public");

    // Already Public: saving another change shows no confirmation.
    const again = await openSettings(page);
    await fillCollectionForm(page, { subtitle: "Still public" });
    await again.getByRole("button", { name: "Save" }).click();
    await expect(again).toBeHidden();
    await expect(page.getByTestId("knowledge-status")).toHaveText("Changes saved.");
    await expect(confirm).toHaveCount(0);

    // Leaving Public needs no confirmation.
    const down = await openSettings(page);
    await fillCollectionForm(page, { access: "Authenticated" });
    await down.getByRole("button", { name: "Save" }).click();
    await expect(down).toBeHidden();
    await expect(page.getByTestId("knowledge-status")).toHaveText("Changes saved.");
    await expect(confirm).toHaveCount(0);
    await expect(page.getByTestId("collection-detail").getByTestId("access-badge")).toHaveText(
      "Authenticated",
    );
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });
  expect(
    auditOf(item.id).map((row) => [row.action, row.old_value, row.new_value, row.actor]),
  ).toEqual([
    ["collection.created", null, "authenticated", `user:${admin.id}`],
    ["collection.access_changed", "authenticated", "public", `user:${admin.id}`],
    ["collection.updated", null, null, `user:${admin.id}`],
    ["collection.access_changed", "public", "authenticated", `user:${admin.id}`],
  ]);
});

test("AC4 TC-4-2: creating a collection as Public asks for confirmation too (Workspace Admin); a Knowledge Editor cannot choose Public and the API refuses it", async ({
  browser,
}) => {
  const admin = user("admin");
  const publicName = `Born public ${MARK}`;
  await withSession(browser, await api("admin"), async (page) => {
    const sent = mutations(page);
    await openKnowledge(page, wsA);
    const dialog = await openNewCollection(page);
    await fillCollectionForm(page, { name: publicName, access: "Public" });
    await dialog.getByRole("button", { name: "Create collection" }).click();
    const confirm = page.getByTestId("confirm-public-dialog");
    await expect(confirm).toBeVisible();
    expect(sent).toEqual([]);
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeVisible();
    expect(sent).toEqual([]);
    await dialog.getByRole("button", { name: "Create collection" }).click();
    const posted = waitApi(page, "POST", new RegExp(`/api/workspaces/${wsA}/collections$`));
    await confirm.getByRole("button", { name: "Make public" }).click();
    expect((await posted).status()).toBe(201);
    const row = rowOf(page, publicName);
    await expect(row.getByTestId("access-badge")).toHaveText("Public");
    const id = (await row.getAttribute("data-collection-id")) as string;
    track(id, wsA, await api("admin"));
    expect(auditOf(id)).toEqual([
      {
        actor: `user:${admin.id}`,
        action: "collection.created",
        target_type: "collection",
        workspace_id: wsA,
        old_value: null,
        new_value: "public",
      },
    ]);
  });

  await withSession(browser, await api("ke"), async (page) => {
    const sent = mutations(page);
    await openKnowledge(page, wsA);
    const dialog = await openNewCollection(page);
    await expect(radioOf(page, "Public")).toBeDisabled();
    await expect(radioOf(page, "Authenticated")).toBeEnabled();
    await expect(radioOf(page, "Restricted")).toBeEnabled();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    expect(sent).toEqual([]);
  });

  for (const key of ["ke", "builder"]) {
    const session = await api(key);
    const eventsBefore = counts().audit;
    const result = await session.send("POST", collectionsPath(wsA), {
      json: { name: `KE public ${MARK}`, access_level: "public" },
    });
    expectDetail(result, 403, "forbidden");
    expect(counts().audit, `${key}: no audit event`).toBe(eventsBefore);
  }
  expect(
    (await listOf(await api("ke"), wsA)).some((entry) => entry.name.startsWith("KE public")),
  ).toBe(false);
});

// ---------------------------------------------------------------------------------------------
// AC5 Local only
// ---------------------------------------------------------------------------------------------

test('AC5: "Local model only" shows in the Data handling column; only a Workspace Admin can switch it off, anyone with knowledge.manage can switch it on; changes are audited', async ({
  browser,
}) => {
  const admin = user("admin");
  const keUser = user("ke");
  const keApi = await api("ke");
  const localName = `Local only ${MARK}`;
  await withSession(browser, keApi, async (page) => {
    const sent = mutations(page);
    await openKnowledge(page, wsA);
    const dialog = await openNewCollection(page);
    await expect(dialog.getByRole("checkbox", { name: /^Local model only/ })).not.toBeChecked();
    await fillCollectionForm(page, { name: localName, localOnly: true });
    const posted = waitApi(page, "POST", new RegExp(`/api/workspaces/${wsA}/collections$`));
    await dialog.getByRole("button", { name: "Create collection" }).click();
    const response = await posted;
    expect(response.status()).toBe(201);
    expect((await response.json()) as CollectionItem).toMatchObject({ local_only: true });
    const row = rowOf(page, localName);
    await expect(row.getByTestId("data-handling")).toHaveText("Local model only");
    await expect(rowOf(page, "Employee Handbook").getByTestId("data-handling")).toHaveText(
      "Any allowed model",
    );
    ids.set("local", (await row.getAttribute("data-collection-id")) as string);
    track(idOf("local"), wsA, keApi);
    expect(sent.map((call) => call.method)).toEqual(["POST"]);
  });
  const id = idOf("local");
  expect(auditOf(id)).toEqual([
    {
      actor: `user:${keUser.id}`,
      action: "collection.created",
      target_type: "collection",
      workspace_id: wsA,
      old_value: null,
      new_value: "authenticated",
    },
  ]);

  // KE cannot switch it off (API 403 and the checkbox is disabled); the flag and the audit stay.
  const path = `${collectionsPath(wsA)}/${id}`;
  expectDetail(await keApi.send("PATCH", path, { json: { local_only: false } }), 403, "forbidden");
  expect((await detailOf(keApi, wsA, id)).local_only).toBe(true);
  expect(auditOf(id)).toHaveLength(1);
  await withSession(browser, keApi, async (page) => {
    await openDetail(page, wsA, id);
    await expect(page.getByTestId("collection-detail").getByTestId("data-handling")).toHaveText(
      "Local model only",
    );
    const dialog = await openSettings(page);
    const box = dialog.getByRole("checkbox", { name: /^Local model only/ });
    await expect(box).toBeChecked();
    await expect(box).toBeDisabled();
    await dialog.getByRole("button", { name: "Cancel" }).click();
  });
  expectDetail(
    await (await api("builder")).send("PATCH", path, { json: { local_only: false } }),
    403,
    "forbidden",
  );

  // The Workspace Admin switches it off in the UI, then anyone can switch it on again.
  const adminApi = await api("admin");
  await withSession(browser, adminApi, async (page) => {
    await openDetail(page, wsA, id);
    const dialog = await openSettings(page);
    const box = dialog.getByRole("checkbox", { name: /^Local model only/ });
    await expect(box).toBeEnabled();
    await box.uncheck();
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("knowledge-status")).toHaveText("Changes saved.");
    await expect(page.getByTestId("collection-detail").getByTestId("data-handling")).toHaveText(
      "Any allowed model",
    );
  });
  expect(auditOf(id).at(-1)).toEqual({
    actor: `user:${admin.id}`,
    action: "collection.local_only_changed",
    target_type: "collection",
    workspace_id: wsA,
    old_value: "local_only",
    new_value: "any_model",
  });
  const on = await keApi.send("PATCH", path, { json: { local_only: true } });
  expect(on.status, on.text).toBe(200);
  expect(json<CollectionItem>(on).local_only).toBe(true);
  expect(auditOf(id).at(-1)).toEqual({
    actor: `user:${keUser.id}`,
    action: "collection.local_only_changed",
    target_type: "collection",
    workspace_id: wsA,
    old_value: "any_model",
    new_value: "local_only",
  });
  const count = auditOf(id).length;
  expect((await keApi.send("PATCH", path, { json: { local_only: true } })).status).toBe(200);
  expect(auditOf(id)).toHaveLength(count); // same value, no event
  expect((await adminApi.send("PATCH", path, { json: { local_only: false } })).status).toBe(200);
  expect(auditOf(id).at(-1)).toMatchObject({ old_value: "local_only", new_value: "any_model" });
  expect(auditValues([id]).every((value) => /^[a-z_]*\|[a-z_]*$/.test(value))).toBe(true);
});

// ---------------------------------------------------------------------------------------------
// AC6 Delete
// ---------------------------------------------------------------------------------------------

test("AC6: deleting a collection needs the typed name (exact, case-sensitive); afterwards the collection and its folders are gone at once and the delete is audited", async ({
  browser,
}) => {
  const keUser = user("ke");
  const keApi = await api("ke");
  const name = `Xóa thử nghiệm ${MARK}`;
  const item = await mustCreateCollection(keApi, wsA, {
    name,
    access_level: "restricted",
    groups: ["hr"],
  });
  const parent = await mustCreateFolder(keApi, wsA, item.id, { name: "Policies" });
  const child = await mustCreateFolder(keApi, wsA, item.id, { name: "2026", parent_id: parent.id });
  expect(child.depth).toBe(2);
  expect(rowCount("folders", [parent.id, child.id])).toBe(2);

  await withSession(browser, keApi, async (page) => {
    const sent = mutations(page);
    const seen = watch(page);
    await openDetail(page, wsA, item.id);
    const danger = page.getByTestId("delete-collection-row");
    await expect(danger).toContainText("Delete collection");
    await expect(danger).toContainText(COPY.deleteLine);
    await page.getByTestId("delete-collection").click();
    const dialog = page.getByTestId("delete-collection-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(`Delete ${name}?`);
    const confirm = page.getByTestId("confirm-delete-collection");
    await expect(confirm).toHaveText("Delete collection");
    await expect(confirm).toBeDisabled();
    const input = dialog.getByRole("textbox", { name: `Type ${name} to confirm` });
    for (const wrong of [
      name.toUpperCase(),
      name.toLowerCase(),
      name.slice(0, -1),
      "Xoa thu nghiem",
      `x${name}`,
    ]) {
      await input.fill(wrong);
      await expect(confirm, `"${wrong}" does not confirm`).toBeDisabled();
    }
    // Escape closes without deleting.
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(sent).toEqual([]);
    expect(await detailOf(keApi, wsA, item.id)).toMatchObject({ name });

    await page.getByTestId("delete-collection").click();
    await input.fill(`  ${name}  `); // the trimmed input is compared
    await expect(confirm).toBeEnabled();
    await input.fill(name);
    await expect(confirm).toBeEnabled();
    const deleted = waitApi(page, "DELETE", new RegExp(`/collections/${item.id}$`));
    await confirm.click();
    expect((await deleted).status()).toBe(204);
    await expect(page).toHaveURL(new RegExp(`/w/${wsA}/knowledge$`));
    await expect(page.getByTestId("knowledge-status")).toHaveText(`${name} was deleted.`);
    await expect(rowOf(page, name)).toHaveCount(0);
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });

  // At once: no collection, no folder, the detail is 404 and so is a second delete.
  expectDetail(await keApi.send("GET", `${collectionsPath(wsA)}/${item.id}`), 404, "not_found");
  expectDetail(await keApi.send("DELETE", `${collectionsPath(wsA)}/${item.id}`), 404, "not_found");
  expect(rowCount("collections", [item.id])).toBe(0);
  expect(rowCount("folders", [parent.id, child.id])).toBe(0);
  expect((await listOf(keApi, wsA)).some((entry) => entry.id === item.id)).toBe(false);
  expectDetail(
    await keApi.send("POST", `${collectionsPath(wsA)}/${item.id}/folders`, {
      json: { name: "Ghost" },
    }),
    404,
    "not_found",
  );
  const events = auditOf(item.id);
  expect(events.at(-1)).toEqual({
    actor: `user:${keUser.id}`,
    action: "collection.deleted",
    target_type: "collection",
    workspace_id: wsA,
    old_value: "restricted",
    new_value: null,
  });
  expect(JSON.stringify(events)).not.toContain(name);
  ids.set("deletedId", item.id);
});

test("AC6 TC-6-2: the deleted collection's page is the Not found page; a Viewer cannot delete; unknown ids are 404", async ({
  browser,
}) => {
  await withSession(browser, await api("ke"), async (page) => {
    await page.goto(`/w/${wsA}/knowledge/${idOf("deletedId")}`);
    await expect(page.getByTestId("collection-detail")).toHaveCount(0);
    await expect(page.getByText(/not found/i).first()).toBeVisible();
  });
  const viewer = await api("viewer");
  expectDetail(
    await viewer.send("DELETE", `${collectionsPath(wsA)}/${idOf("handbook")}`),
    403,
    "forbidden",
  );
  expectDetail(
    await (await api("ke")).send("DELETE", `${collectionsPath(wsA)}/${randomUUID()}`),
    404,
    "not_found",
  );
  expect((await detailOf(await api("ke"), wsA, idOf("handbook"))).name).toBe("Employee Handbook");
});

// ---------------------------------------------------------------------------------------------
// AC7 Empty state
// ---------------------------------------------------------------------------------------------

test('AC7: a Workspace with no collections shows the empty state with exactly one "New collection" button, no search or table, and keeps the legend and footnote', async ({
  browser,
}) => {
  const ke = await api("ke");
  expect(json<{ collections: unknown[] }>(await ke.send("GET", collectionsPath(wsEmpty)))).toEqual({
    collections: [],
  });
  await withSession(browser, ke, async (page) => {
    const seen = watch(page);
    await openKnowledge(page, wsEmpty);
    const empty = page.getByTestId("collections-empty");
    await expect(empty).toBeVisible();
    await expect(empty).toContainText(COPY.emptyTitle);
    await expect(empty).toContainText(COPY.emptyBody);
    await expect(empty.getByRole("button", { name: "New collection" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New collection" })).toHaveCount(1);
    await expect(page.getByTestId("new-collection")).toHaveCount(1);
    await expect(page.getByTestId("collections-table")).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Search collections" })).toHaveCount(0);
    await expect(page.getByTestId("collection-row")).toHaveCount(0);
    await expect(page.getByTestId("access-legend")).toBeVisible();
    await expect(page.getByTestId("collections-footnote")).toHaveText(COPY.footnote);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Knowledge");
    await page.screenshot({
      path: path.join(SCREENSHOTS_32, "ac7-empty-state.png"),
      fullPage: true,
    });

    // The button opens the create dialog; Cancel leaves the empty state untouched.
    await page.getByTestId("new-collection").click();
    await expect(page.getByTestId("collection-dialog")).toBeVisible();
    await page.getByTestId("collection-dialog").getByRole("button", { name: "Cancel" }).click();
    await expect(empty).toBeVisible();
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------
// AC8 Matches the design
// ---------------------------------------------------------------------------------------------

test("AC8: the Collections screen has the header, legend, search, table columns, badges with text and footnote of the Collections artboard (seeded People Ops)", async ({
  browser,
}) => {
  await withSession(browser, await api("poAdmin"), async (page) => {
    const seen = watch(page);
    await openKnowledge(page, peopleOps);
    await expect(page).toHaveTitle("Knowledge · ei-ai");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Knowledge");
    await expect(page.getByTestId("knowledge-page")).toContainText(COPY.subtitle);
    await expect(
      page.getByTestId("sidebar").getByRole("link", { name: "Knowledge", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("button", { name: "New collection" })).toHaveCount(1);

    // Legend: three items, each with a badge and a text.
    const legend = page.getByTestId("access-legend");
    for (const [label, text] of COPY.legend) {
      await expect(legend, label).toContainText(label);
      await expect(legend, label).toContainText(text);
    }

    // Search box and table headers in order.
    await expect(page.getByRole("textbox", { name: "Search collections" })).toBeVisible();
    const table = page.getByTestId("collections-table");
    const headers = (await table.getByRole("columnheader").allTextContents()).map((text) =>
      text.trim(),
    );
    expect(headers).toEqual([...COPY.headers]);

    // The seed rows, in name order, with the exact values of the artboard.
    const names = await listedNames(page);
    const seedNames = SEED.map((entry) => entry.name);
    expect(names.filter((name) => seedNames.includes(name))).toEqual(seedNames);
    for (const entry of SEED) {
      const row = rowOf(page, entry.name);
      await expect(row, entry.name).toHaveCount(1);
      await expect(row.getByRole("link", { name: entry.name, exact: true })).toHaveAttribute(
        "href",
        new RegExp(`/w/${peopleOps}/knowledge/[0-9a-f-]{36}$`),
      );
      const badge = row.getByTestId("access-badge");
      await expect(badge, entry.name).toHaveText(entry.badge);
      await expect(badge, entry.name).toHaveAttribute("data-access", entry.access);
      await expect(row.getByTestId("data-handling"), entry.name).toHaveText(
        entry.local ? "Local model only" : "Any allowed model",
      );
      await expect(row.getByTestId("document-count"), entry.name).toHaveText("0");
      await expect(row.getByTestId("collection-status"), entry.name).toHaveText("No documents");
      await expect(row.getByTestId("used-by"), entry.name).toHaveText("Not used yet");
      if (entry.subtitle) await expect(row, entry.name).toContainText(entry.subtitle);
    }

    // Badges never rely on colour alone: every badge has text, and the text is readable (>= 4.5:1).
    const badges = page.getByTestId("access-badge");
    const badgeCount = await badges.count();
    expect(badgeCount).toBeGreaterThanOrEqual(SEED.length);
    for (let index = 0; index < badgeCount; index++) {
      const badge = badges.nth(index);
      const text = ((await badge.textContent()) ?? "").trim();
      expect(text, `badge ${index} has text`).toMatch(/^(Public|Authenticated|Restricted)/);
      expect(await contrastRatio(badge), `badge "${text}" contrast`).toBeGreaterThanOrEqual(4.5);
    }
    const localBadge = rowOf(page, "Project Falcon").getByTestId("data-handling");
    expect(await contrastRatio(localBadge)).toBeGreaterThanOrEqual(4.5);

    await expect(page.getByTestId("collections-footnote")).toHaveText(COPY.footnote);
    await page.screenshot({
      path: path.join(SCREENSHOTS_32, "ac8-collections-list.png"),
      fullPage: true,
    });
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });
});

test("AC8 TC-8-2: search filters as you type on name and subtitle, ignoring case and Vietnamese diacritics; no match shows the message", async ({
  browser,
}) => {
  const keApi = await api("ke");
  const item = await mustCreateCollection(keApi, wsA, {
    name: `Hướng dẫn nhân sự ${MARK}`,
    subtitle: "Chính sách nghỉ phép",
    access_level: "authenticated",
  });
  await withSession(browser, keApi, async (page) => {
    await openKnowledge(page, wsA);
    const search = page.getByRole("textbox", { name: "Search collections" });
    const rows = page.getByTestId("collection-row");
    await expect(rows.first()).toBeVisible();
    const total = await rows.count();
    expect(total).toBeGreaterThan(3);
    const target = page.locator(`[data-collection-id="${item.id}"]`);
    const queries: [string, number][] = [
      ["huong dan nhan su", 1],
      ["HƯỚNG DẪN", 1],
      ["nghi phep", 1],
      ["CHÍNH SÁCH", 2], // this subtitle and the one of the Vietnamese collection of TC-1-4
      ["chinh sach nghi", 1],
    ];
    for (const [query, expected] of queries) {
      await search.fill(query);
      await expect(target, `"${query}" finds the collection`).toBeVisible();
      await expect(rows, `"${query}"`).toHaveCount(expected);
    }
    await search.fill("zzzz-no-such-collection");
    await expect(page.getByTestId("collections-no-match")).toHaveText(COPY.noMatch);
    await expect(rows).toHaveCount(0);
    await search.fill("");
    await expect(rows).toHaveCount(total);
    await expect(page.getByTestId("collections-no-match")).toHaveCount(0);
    await search.pressSequentially("employee");
    await expect(rows).toHaveCount(1); // filters as you type, without Enter
  });
});

test("AC8 TC-8-3: the collection detail has the breadcrumb, title, badge, data handling, Folders panel, documents placeholder and delete row", async ({
  browser,
}) => {
  const id = idOf("handbook");
  await withSession(browser, await api("ke"), async (page) => {
    const seen = watch(page);
    await openDetail(page, wsA, id);
    await expect(page).toHaveTitle("Employee Handbook · ei-ai");
    const detail = page.getByTestId("collection-detail");
    await expect(detail.getByRole("heading", { level: 1 })).toHaveText("Employee Handbook");
    const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(crumbs.getByRole("link", { name: "Knowledge", exact: true })).toHaveAttribute(
      "href",
      `/w/${wsA}/knowledge`,
    );
    await expect(crumbs).toContainText("Employee Handbook");
    await expect(detail.getByTestId("access-badge")).toHaveText("Authenticated");
    await expect(detail.getByTestId("data-handling")).toHaveText("Any allowed model");
    await expect(page.getByTestId("collection-settings")).toHaveText("Access & settings");
    await expect(
      page.getByTestId("sidebar").getByRole("link", { name: "Knowledge", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    const panel = page.getByRole("navigation", { name: "Folders" });
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("folders-panel")).toBeVisible();
    await expect(page.getByTestId("new-folder")).toHaveText("New folder");
    await expect(panel).toContainText("No folders yet.");
    await expect(page.getByTestId("documents-empty")).toHaveText("No documents yet.");
    const danger = page.getByTestId("delete-collection-row");
    await expect(danger).toContainText("Delete collection");
    await expect(danger).toContainText(COPY.deleteLine);
    await expect(danger.getByRole("button", { name: "Delete collection" })).toBeVisible();
    await page.screenshot({
      path: path.join(SCREENSHOTS_32, "ac8-collection-detail.png"),
      fullPage: true,
    });
    // The breadcrumb link goes back to the list.
    await crumbs.getByRole("link", { name: "Knowledge", exact: true }).click();
    await expect(page.getByTestId("knowledge-page")).toBeVisible();
    // The list link goes to the detail.
    await rowOf(page, "Employee Handbook")
      .getByRole("link", { name: "Employee Handbook", exact: true })
      .click();
    await expect(page).toHaveURL(new RegExp(`/w/${wsA}/knowledge/${id}$`));
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------
// Folders (scope: Folder CRUD nested 1-3 levels)
// ---------------------------------------------------------------------------------------------

test("Folders TC-F-1: a Knowledge Editor creates folders nested to 3 levels, renames and deletes them; depth 3 has no 'Add subfolder'; a parent with subfolders cannot be deleted", async ({
  browser,
}) => {
  const keUser = user("ke");
  const keApi = await api("ke");
  const item = await mustCreateCollection(keApi, wsA, {
    name: `Folders ${MARK}`,
    access_level: "authenticated",
  });
  await withSession(browser, keApi, async (page) => {
    const seen = watch(page);
    await openDetail(page, wsA, item.id);
    const panel = page.getByTestId("folders-panel");
    await expect(panel).toContainText("No folders yet.");

    const addFolder = async (trigger: () => Promise<void>, name: string, title: string) => {
      await trigger();
      const dialog = page.getByTestId("folder-dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog).toContainText(title);
      await dialog.getByRole("textbox", { name: "Folder name" }).fill(name);
      const posted = waitApi(page, "POST", /\/folders$/);
      await dialog.getByRole("button", { name: "Create folder" }).click();
      expect((await posted).status()).toBe(201);
      await expect(dialog).toBeHidden();
    };
    await addFolder(() => page.getByTestId("new-folder").click(), "Policies", "New folder");
    await expect(panel).not.toContainText("No folders yet.");
    await addFolder(
      () => page.getByRole("button", { name: "Add subfolder to Policies" }).click(),
      "2026",
      "New folder",
    );
    await addFolder(
      () => page.getByRole("button", { name: "Add subfolder to 2026" }).click(),
      "Approved",
      "New folder",
    );

    const rowsNow = page.getByTestId("folder-row");
    await expect(rowsNow).toHaveCount(3);
    const levels = await rowsNow.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-depth")),
    );
    expect(levels).toEqual(["1", "2", "3"]);
    // Indented by depth: the name of each deeper row starts further right.
    const lefts: number[] = [];
    for (const name of ["Policies", "2026", "Approved"]) {
      const box = await folderRow(page, name)
        .getByText(name, { exact: true })
        .first()
        .boundingBox();
      lefts.push(box?.x ?? -1);
    }
    expect(lefts[0]).toBeLessThan(lefts[1] ?? 0);
    expect(lefts[1]).toBeLessThan(lefts[2] ?? 0);
    // Depth 3: no "Add subfolder"; the other buttons exist and are at least 24 x 24 px.
    await expect(page.getByRole("button", { name: "Add subfolder to Approved" })).toHaveCount(0);
    for (const label of [
      "Add subfolder to Policies",
      "Rename Policies",
      "Delete Policies",
      "Rename Approved",
      "Delete Approved",
    ]) {
      const box = await page.getByRole("button", { name: label, exact: true }).boundingBox();
      expect(box, label).not.toBeNull();
      if ((box?.width ?? 0) < 24 || (box?.height ?? 0) < 24) {
        smallTargets.push(`${label}: ${box?.width} x ${box?.height}`); // asserted in TC-A11Y-1
      }
    }

    // Sibling duplicate: the same name under the same parent.
    await page.getByRole("button", { name: "Add subfolder to Policies" }).click();
    let dialog = page.getByTestId("folder-dialog");
    await dialog.getByRole("textbox", { name: "Folder name" }).fill("2026");
    await dialog.getByRole("button", { name: "Create folder" }).click();
    await expectAlert(page, COPY.folderTaken);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(rowsNow).toHaveCount(3);

    // Rename.
    await page.getByRole("button", { name: "Rename Policies" }).click();
    dialog = page.getByTestId("folder-dialog");
    await expect(dialog).toContainText("Rename folder");
    await expect(dialog.getByRole("textbox", { name: "Folder name" })).toHaveValue("Policies");
    await dialog.getByRole("textbox", { name: "Folder name" }).fill("Chính sách");
    const patched = waitApi(page, "PATCH", /\/folders\/[0-9a-f-]{36}$/);
    await dialog.getByRole("button", { name: "Save" }).click();
    expect((await patched).status()).toBe(200);
    await expect(folderRow(page, "Chính sách")).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Rename Chính sách" })).toBeVisible();

    // Delete a parent with a subfolder: refused with the message; Cancel keeps everything.
    await page.getByRole("button", { name: "Delete Chính sách" }).click();
    const confirm = page.getByTestId("confirm-folder-delete");
    await expect(confirm).toBeVisible();
    await expect(confirm).toContainText("Delete folder?");
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toBeHidden();
    await expect(rowsNow).toHaveCount(3);
    await page.getByRole("button", { name: "Delete Chính sách" }).click();
    await confirm.getByRole("button", { name: "Delete folder" }).click();
    await expectAlert(page, COPY.folderNotEmpty);
    await expect(rowsNow).toHaveCount(3);
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toBeHidden();

    // Delete from the leaf up.
    for (const name of ["Approved", "2026", "Chính sách"]) {
      await page.getByRole("button", { name: `Delete ${name}` }).click();
      const deleted = waitApi(page, "DELETE", /\/folders\/[0-9a-f-]{36}$/);
      await page
        .getByTestId("confirm-folder-delete")
        .getByRole("button", { name: "Delete folder" })
        .click();
      expect((await deleted).status()).toBe(204);
      await expect(folderRow(page, name)).toHaveCount(0);
    }
    await expect(panel).toContainText("No folders yet.");
    expect(withoutStatuses(seen.problems, [409])).toEqual([]);
  });
  expect((await detailOf(keApi, wsA, item.id)).folders).toEqual([]);
  ids.set("folders", item.id);
  expect(auditOf(item.id).map((row) => row.actor)).toEqual([`user:${keUser.id}`]); // only the collection itself
});

test("Folders TC-F-2: the folder API: depth, ordering, 3-level limit, duplicates, other collections, audit events", async () => {
  const keApi = await api("ke");
  const keUser = user("ke");
  const first = await mustCreateCollection(keApi, wsA, {
    name: `FolderApi one ${MARK}`,
    access_level: "authenticated",
  });
  const second = await mustCreateCollection(keApi, wsA, {
    name: `FolderApi two ${MARK}`,
    access_level: "authenticated",
  });
  const root = await mustCreateFolder(keApi, wsA, first.id, { name: "Zebra" });
  const rootB = await mustCreateFolder(keApi, wsA, first.id, { name: "alpha", parent_id: null });
  const level2 = await mustCreateFolder(keApi, wsA, first.id, {
    name: "Level two",
    parent_id: root.id,
  });
  const level3 = await mustCreateFolder(keApi, wsA, first.id, {
    name: "Level three",
    parent_id: level2.id,
  });
  expect([root.depth, rootB.depth, level2.depth, level3.depth]).toEqual([1, 1, 2, 3]);
  expect(Object.keys(level3).sort()).toEqual(FOLDER_KEYS);
  expect(level3.parent_id).toBe(level2.id);
  expect(root.parent_id).toBeNull();

  // Depth 4 is refused; nothing is created.
  expectDetail(
    await keApi.send("POST", `${collectionsPath(wsA)}/${first.id}/folders`, {
      json: { name: "Level four", parent_id: level3.id },
    }),
    422,
    "folder_too_deep",
  );
  // Duplicates under the same parent, ignoring case; the same name under another parent is fine.
  for (const name of ["zebra", "ALPHA"]) {
    expectDetail(
      await keApi.send("POST", `${collectionsPath(wsA)}/${first.id}/folders`, { json: { name } }),
      409,
      "name_taken",
    );
  }
  expect(
    (await createFolder(keApi, wsA, first.id, { name: "Level two", parent_id: rootB.id })).status,
  ).toBe(201);
  // A parent of another collection, or an unknown one: 404.
  const foreignParent = await mustCreateFolder(keApi, wsA, second.id, { name: "Elsewhere" });
  for (const parent of [foreignParent.id, randomUUID()]) {
    expectDetail(
      await keApi.send("POST", `${collectionsPath(wsA)}/${first.id}/folders`, {
        json: { name: "Orphan", parent_id: parent },
      }),
      404,
      "not_found",
    );
  }
  // Validation.
  for (const body of [
    {},
    { name: "" },
    { name: "f".repeat(201) },
    { name: "ok", id: randomUUID() },
    { name: 5 },
  ]) {
    expectDetail(
      await keApi.send("POST", `${collectionsPath(wsA)}/${first.id}/folders`, { json: body }),
      422,
      "invalid_request",
    );
  }

  // The detail lists folders flat, by depth and then name.
  const folders = (await detailOf(keApi, wsA, first.id)).folders;
  expect(folders.map((folder) => [folder.depth, folder.name])).toEqual([
    [1, "alpha"],
    [1, "Zebra"],
    [2, "Level two"],
    [2, "Level two"],
    [3, "Level three"],
  ]);
  for (const folder of folders) expect(Object.keys(folder).sort()).toEqual(FOLDER_KEYS);

  // Rename: duplicate refused, new name accepted, a folder of another collection is 404.
  const route = (collectionId: string, folderId: string) =>
    `${collectionsPath(wsA)}/${collectionId}/folders/${folderId}`;
  expectDetail(
    await keApi.send("PATCH", route(first.id, root.id), { json: { name: "Alpha" } }),
    409,
    "name_taken",
  );
  const renamed = await keApi.send("PATCH", route(first.id, root.id), {
    json: { name: "Zebra 2" },
  });
  expect(renamed.status, renamed.text).toBe(200);
  expect(json<FolderItem>(renamed)).toMatchObject({ id: root.id, name: "Zebra 2", depth: 1 });
  expectDetail(
    await keApi.send("PATCH", route(second.id, root.id), { json: { name: "Nope" } }),
    404,
    "not_found",
  );
  expectDetail(
    await keApi.send("PATCH", route(first.id, root.id), { json: { name: "" } }),
    422,
    "invalid_request",
  );
  // Delete: a parent with subfolders is 409; the leaf goes; then the parents; a repeat is 404.
  expectDetail(await keApi.send("DELETE", route(first.id, root.id)), 409, "folder_not_empty");
  expect((await keApi.send("DELETE", route(first.id, level3.id))).status).toBe(204);
  expect((await keApi.send("DELETE", route(first.id, level2.id))).status).toBe(204);
  expectDetail(await keApi.send("DELETE", route(first.id, level2.id)), 404, "not_found");
  expectDetail(await keApi.send("DELETE", route(second.id, root.id)), 404, "not_found");
  expect(rowCount("folders", [level3.id, level2.id])).toBe(0);

  // Audit: folder events carry no names (NULL to NULL) and the Workspace of the collection.
  expect(
    auditOf(level3.id).map((row) => [row.action, row.target_type, row.old_value, row.new_value]),
  ).toEqual([
    ["folder.created", "folder", null, null],
    ["folder.deleted", "folder", null, null],
  ]);
  expect(auditOf(root.id).map((row) => row.action)).toEqual(["folder.created", "folder.renamed"]);
  expect(auditOf(root.id)[0]).toMatchObject({ actor: `user:${keUser.id}`, workspace_id: wsA });
  // A Viewer cannot touch folders.
  const viewer = await api("viewer");
  expectDetail(
    await viewer.send("POST", `${collectionsPath(wsA)}/${first.id}/folders`, {
      json: { name: "V" },
    }),
    403,
    "forbidden",
  );
  expectDetail(await viewer.send("DELETE", route(first.id, root.id)), 403, "forbidden");
});

// ---------------------------------------------------------------------------------------------
// Roles in the UI and Not found pages
// ---------------------------------------------------------------------------------------------

test("TC-ROLE-1: a Viewer sees no Knowledge item and gets the No access page on the list and the detail; a Builder sees Knowledge", async ({
  browser,
}) => {
  await withSession(browser, await api("viewer"), async (page) => {
    for (const url of [`/w/${wsA}/knowledge`, `/w/${wsA}/knowledge/${idOf("handbook")}`]) {
      await page.goto(url);
      await expect(page.getByTestId("area-forbidden")).toBeVisible();
      await expect(
        page.getByTestId("area-forbidden").getByRole("heading", { level: 1 }),
      ).toHaveText("No access");
      await expect(page.getByTestId("knowledge-page")).toHaveCount(0);
      await expect(page.getByTestId("collection-detail")).toHaveCount(0);
      await expect(
        page.getByTestId("sidebar").getByRole("link", { name: "Knowledge", exact: true }),
      ).toHaveCount(0);
    }
  });
  await withSession(browser, await api("builder"), async (page) => {
    await openKnowledge(page, wsA);
    await expect(
      page.getByTestId("sidebar").getByRole("link", { name: "Knowledge", exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("new-collection")).toBeVisible();
  });
});

test("TC-ROLE-2: an unknown id, an id of another Workspace and an id of another Organization all give the same Not found page", async ({
  browser,
}) => {
  const foreignId = (
    await mustCreateCollection(await foreignOwner(), foreign.workspaceId, {
      name: `Foreign page ${MARK}`,
      access_level: "authenticated",
    })
  ).id;
  const otherId = idOf("otherHandbook");
  await withSession(browser, await api("admin"), async (page) => {
    const bodies: string[] = [];
    for (const id of [randomUUID(), otherId, foreignId]) {
      await page.goto(`/w/${wsA}/knowledge/${id}`);
      await expect(page.getByTestId("collection-detail")).toHaveCount(0);
      await expect(page.getByText(/not found/i).first()).toBeVisible();
      bodies.push((await page.locator("body").innerText()).trim());
    }
    expect(new Set(bodies).size, "the three Not found pages are identical").toBe(1);
    expect(bodies[0]).not.toContain("Employee Handbook");
    await page.goto(`/w/${wsA}/knowledge/not-a-uuid`);
    await expect(page.getByTestId("collection-detail")).toHaveCount(0);
    await expect(page.getByText(/not found/i).first()).toBeVisible();
    expect((await page.locator("body").innerText()).trim(), "same page as an unknown id").toBe(
      bodies[0],
    );
    await page.goto(`/w/${wsA}/assistants/anything`);
    await expect(page.getByText(/not found/i).first()).toBeVisible();
  });
});

// ---------------------------------------------------------------------------------------------
// Attack list (API)
// ---------------------------------------------------------------------------------------------

type Call = [method: string, path: string, body?: unknown];

/** Every collection and folder route for a Workspace, with ids for the path. */
function allRoutes(ws: string, collectionId: string, folderId: string): Call[] {
  const base = collectionsPath(ws);
  return [
    ["GET", base],
    ["POST", base, { name: `Route ${MARK}`, access_level: "authenticated" }],
    ["GET", `${base}/${collectionId}`],
    ["PATCH", `${base}/${collectionId}`, { subtitle: "route" }],
    ["PUT", `${base}/${collectionId}/access`, { access_level: "authenticated", groups: [] }],
    ["DELETE", `${base}/${collectionId}`],
    ["POST", `${base}/${collectionId}/folders`, { name: `Route ${MARK}` }],
    ["PATCH", `${base}/${collectionId}/folders/${folderId}`, { name: `Route ${MARK}` }],
    ["DELETE", `${base}/${collectionId}/folders/${folderId}`],
  ];
}

test("ATTACK-1: no session, a garbage or expired session cookie and a forged identity header give 401 unauthenticated on every route", async () => {
  const anonymous = new ApiSession();
  await anonymous.ensureCsrf();
  const keApi = await api("ke");
  const collectionId = idOf("handbook");
  const folder = await mustCreateFolder(keApi, wsA, collectionId, { name: `Attack ${MARK}` });
  for (const [method, route, body] of allRoutes(wsA, collectionId, folder.id)) {
    const result = await anonymous.send(method, route, body === undefined ? {} : { json: body });
    expectDetail(result, 401, "unauthenticated");
    const garbage = await anonymous.send(method, route, {
      ...(body === undefined ? {} : { json: body }),
      cookies: {
        ei_session: `${randomUUID()}.${randomUUID()}`,
        ei_csrf: anonymous.csrfCookie ?? "x",
      },
    });
    expectDetail(garbage, 401, "unauthenticated");
  }
  const forged = await anonymous.send("GET", collectionsPath(wsA), {
    headers: {
      "x-role": "workspace_admin",
      "x-user-id": user("admin").id,
      "x-org-id": foreign.orgId,
    },
  });
  expectDetail(forged, 401, "unauthenticated");
  // A write without the CSRF token is refused and writes nothing.
  const auditBefore = counts();
  const noCsrf = await keApi.send("POST", collectionsPath(wsA), {
    json: { name: `NoCsrf ${MARK}`, access_level: "authenticated" },
    csrf: "none",
  });
  expect(noCsrf.status).toBeGreaterThanOrEqual(400);
  expect(counts()).toEqual(auditBefore);
  ids.set("attackFolder", folder.id);
});

test("ATTACK-2: a Viewer gets 403 forbidden on every route; a member of no Workspace gets 404 for the Workspace, identical to an unknown Workspace", async () => {
  const collectionId = idOf("handbook");
  const folderId = idOf("attackFolder");
  const viewer = await api("viewer");
  const before = counts();
  for (const [method, route, body] of allRoutes(wsA, collectionId, folderId)) {
    const result = await viewer.send(method, route, body === undefined ? {} : { json: body });
    expectDetail(result, 403, "forbidden");
  }
  expect(counts(), "a refused call changes nothing").toEqual(before);

  // The KE is a member of wsA and wsEmpty only: wsOther and the foreign Workspace do not exist for them.
  const ke = await api("ke");
  const random = randomUUID();
  const unknown = await ke.send("GET", collectionsPath(random));
  expectDetail(unknown, 404, "not_found");
  for (const workspace of [wsOther, foreign.workspaceId]) {
    for (const [method, route, body] of allRoutes(workspace, idOf("otherHandbook"), randomUUID())) {
      const result = await ke.send(method, route, body === undefined ? {} : { json: body });
      expectDetail(result, 404, "not_found");
    }
  }
  expectSameAnswer(
    await ke.send("GET", collectionsPath(wsOther)),
    unknown,
    "KE on another Workspace",
  );
  expectSameAnswer(
    await ke.send("GET", collectionsPath(foreign.workspaceId)),
    unknown,
    "KE on a foreign Workspace",
  );
  expect(counts()).toEqual(before);
  // The owner of the other Organization has no access to People Ops either.
  const owner = await foreignOwner();
  expectSameAnswer(
    await owner.send("GET", collectionsPath(peopleOps)),
    unknown,
    "foreign owner on People Ops",
  );
  expectSameAnswer(await owner.send("GET", collectionsPath(wsA)), unknown, "foreign owner on wsA");
});

test("ATTACK-3: ids of another Workspace or another Organization on every collection and folder route answer 404 not_found, byte-identical to an unknown id, and change nothing", async () => {
  const admin = await api("admin");
  const owner = await foreignOwner();
  const otherAdmin = await api("otherAdmin");
  const otherCollection = idOf("otherHandbook");
  const otherFolder = await mustCreateFolder(otherAdmin, wsOther, otherCollection, {
    name: `Other ${MARK}`,
  });
  const foreignCollection = await mustCreateCollection(owner, foreign.workspaceId, {
    name: `Foreign ${MARK}`,
    access_level: "authenticated",
  });
  const foreignFolder = await mustCreateFolder(owner, foreign.workspaceId, foreignCollection.id, {
    name: `Foreign ${MARK}`,
  });
  const ownCollection = idOf("handbook");
  const snapshots = {
    own: JSON.stringify(await detailOf(admin, wsA, ownCollection)),
    other: JSON.stringify(await detailOf(otherAdmin, wsOther, otherCollection)),
    foreign: JSON.stringify(await detailOf(owner, foreign.workspaceId, foreignCollection.id)),
  };
  const baselineCounts = counts();
  const reference = async (method: string, route: string, body: unknown) =>
    admin.send(method, route, body === undefined ? {} : { json: body });

  const cases: [label: string, collectionId: string, folderId: string][] = [
    ["unknown ids", randomUUID(), randomUUID()],
    ["other Workspace", otherCollection, otherFolder.id],
    ["other Organization", foreignCollection.id, foreignFolder.id],
  ];
  const firstAnswers = new Map<string, Awaited<ReturnType<typeof reference>>>();
  for (const [label, collectionId, folderId] of cases) {
    for (const [method, route, body] of allRoutes(wsA, collectionId, folderId).slice(2)) {
      const result = await reference(method, route, body);
      expectDetail(result, 404, "not_found");
      const key = `${method} ${route.replace(collectionId, ":c").replace(folderId, ":f")}`;
      const first = firstAnswers.get(key);
      if (first) expectSameAnswer(result, first, `${key} (${label})`);
      else firstAnswers.set(key, result);
    }
  }
  // A folder of another Workspace / Organization used through an own collection path, and as parent_id.
  for (const folderId of [otherFolder.id, foreignFolder.id, randomUUID()]) {
    expectDetail(
      await admin.send("PATCH", `${collectionsPath(wsA)}/${ownCollection}/folders/${folderId}`, {
        json: { name: "Hijack" },
      }),
      404,
      "not_found",
    );
    expectDetail(
      await admin.send("DELETE", `${collectionsPath(wsA)}/${ownCollection}/folders/${folderId}`),
      404,
      "not_found",
    );
    expectDetail(
      await admin.send("POST", `${collectionsPath(wsA)}/${ownCollection}/folders`, {
        json: { name: "Hijack", parent_id: folderId },
      }),
      404,
      "not_found",
    );
  }
  // A foreign Workspace id in the path with an own collection id.
  for (const workspace of [wsOther, foreign.workspaceId]) {
    expectDetail(
      await admin.send("GET", `${collectionsPath(workspace)}/${ownCollection}`),
      404,
      "not_found",
    );
    expectDetail(
      await admin.send("DELETE", `${collectionsPath(workspace)}/${ownCollection}`),
      404,
      "not_found",
    );
  }
  expect(counts(), "nothing was created, changed or deleted").toEqual(baselineCounts);
  expect(JSON.stringify(await detailOf(admin, wsA, ownCollection))).toBe(snapshots.own);
  expect(JSON.stringify(await detailOf(otherAdmin, wsOther, otherCollection))).toBe(
    snapshots.other,
  );
  expect(JSON.stringify(await detailOf(owner, foreign.workspaceId, foreignCollection.id))).toBe(
    snapshots.foreign,
  );
  // The lists do not leak each other's rows.
  const ownNames = (await listOf(admin, wsA)).map((entry) => entry.id);
  expect(ownNames).not.toContain(otherCollection);
  expect(ownNames).not.toContain(foreignCollection.id);
  const foreignIds = (await listOf(owner, foreign.workspaceId)).map((entry) => entry.id);
  expect(foreignIds).toContain(foreignCollection.id);
  expect(foreignIds).not.toContain(ownCollection);
  expect(foreignIds).not.toContain(otherCollection);
});

test("ATTACK-4: Knowledge Editor and Builder cannot change access, create Public or switch local-only off: 403, no row change, no audit event", async () => {
  const adminApi = await api("admin");
  const localItem = await mustCreateCollection(adminApi, wsA, {
    name: `Attack local ${MARK}`,
    access_level: "restricted",
    groups: ["managers"],
    local_only: true,
  });
  for (const key of ["ke", "builder"]) {
    const session = await api(key);
    const beforeDetail = JSON.stringify(await detailOf(adminApi, wsA, localItem.id));
    const beforeCounts = counts();
    const attempts: Call[] = [
      [
        "PUT",
        `${collectionsPath(wsA)}/${localItem.id}/access`,
        { access_level: "public", groups: [] },
      ],
      [
        "PUT",
        `${collectionsPath(wsA)}/${localItem.id}/access`,
        { access_level: "authenticated", groups: [] },
      ],
      [
        "PUT",
        `${collectionsPath(wsA)}/${localItem.id}/access`,
        { access_level: "restricted", groups: ["other"] },
      ],
      ["POST", collectionsPath(wsA), { name: `Attack public ${MARK}`, access_level: "public" }],
      ["PATCH", `${collectionsPath(wsA)}/${localItem.id}`, { local_only: false }],
      [
        "PATCH",
        `${collectionsPath(wsA)}/${localItem.id}`,
        { local_only: false, name: `Renamed ${MARK}` },
      ],
    ];
    for (const [method, route, body] of attempts) {
      expectDetail(await session.send(method, route, { json: body }), 403, "forbidden");
    }
    expect(
      JSON.stringify(await detailOf(adminApi, wsA, localItem.id)),
      `${key}: collection unchanged`,
    ).toBe(beforeDetail);
    expect(counts(), `${key}: no row and no audit event`).toEqual(beforeCounts);
  }
  expect(auditOf(localItem.id).map((row) => row.action)).toEqual(["collection.created"]);
});

test("ATTACK-5: identity and mass-assignment fields are refused (422 invalid_request) and never used; ?org_id and X-Org-Id are ignored", async () => {
  const admin = await api("admin");
  const ke = await api("ke");
  const target = idOf("handbook");
  const before = counts();
  const detailBefore = JSON.stringify(await detailOf(admin, wsA, target));
  const base = collectionsPath(wsA);
  const patchBodies: Record<string, unknown>[] = [
    { subtitle: "x", org_id: foreign.orgId },
    { subtitle: "x", organization_id: foreign.orgId },
    { subtitle: "x", workspace_id: wsOther },
    { subtitle: "x", id: randomUUID() },
    { access_level: "public" },
    { subtitle: "x", access_level: "public" },
    { subtitle: "x", groups: ["hr"] },
    {},
    { local_only: "yes" },
    { name: "" },
    { name: "n".repeat(201) },
  ];
  for (const body of patchBodies) {
    expectDetail(
      await ke.send("PATCH", `${base}/${target}`, { json: body }),
      422,
      "invalid_request",
    );
  }
  for (const extra of [
    { org_id: foreign.orgId },
    { workspace_id: wsOther },
    { id: randomUUID() },
    { name: "x" },
  ]) {
    expectDetail(
      await admin.send("PUT", `${base}/${target}/access`, {
        json: { access_level: "authenticated", groups: [], ...extra },
      }),
      422,
      "invalid_request",
    );
  }
  expectDetail(
    await admin.send("PUT", `${base}/${target}/access`, { json: { groups: [] } }),
    422,
    "invalid_request",
  );
  expect(counts()).toEqual(before);
  expect(JSON.stringify(await detailOf(admin, wsA, target))).toBe(detailBefore);

  // Query parameter and header are ignored: the answer is the same, and a create lands in the path's Workspace.
  const plain = await admin.send("GET", base);
  const forged = await admin.send(
    "GET",
    `${base}?org_id=${foreign.orgId}&workspace_id=${wsOther}`,
    {
      headers: { "x-org-id": foreign.orgId, "x-workspace-id": wsOther },
    },
  );
  expect(forged.status).toBe(200);
  expect(forged.text).toBe(plain.text);
  const created = await admin.send("POST", `${base}?org_id=${foreign.orgId}`, {
    json: { name: `Query ${MARK}`, access_level: "authenticated" },
    headers: { "x-org-id": foreign.orgId },
  });
  expect(created.status, created.text).toBe(201);
  const createdItem = json<CollectionItem>(created);
  track(createdItem.id, wsA, admin);
  expect(auditOf(createdItem.id)[0]).toMatchObject({ workspace_id: wsA });
  const owner = await foreignOwner();
  expect(
    (await listOf(owner, foreign.workspaceId)).some((entry) => entry.id === createdItem.id),
  ).toBe(false);
  // A path that is not a UUID.
  expect([404, 422]).toContain((await admin.send("GET", `${base}/not-a-uuid`)).status);
});

test("ATTACK-6: names, subtitles and groups never appear in error bodies, audit values or the API logs", async () => {
  const admin = await api("admin");
  const ke = await api("ke");
  const secret = `leak-${MARK}`;
  const created = await createCollection(admin, wsA, {
    name: secret,
    subtitle: `${secret} subtitle`,
    access_level: "restricted",
    groups: [`${secret}-group`],
    local_only: true,
  });
  expect(created.status, created.text).toBe(201);
  const item = json<CollectionItem>(created);
  const answers = [
    await admin.send("POST", collectionsPath(wsA), {
      json: { name: secret, access_level: "public" },
    }), // 409
    await ke.send("POST", collectionsPath(wsA), {
      json: { name: `${secret}2`, access_level: "public" },
    }), // 403
    await admin.send("POST", collectionsPath(wsA), {
      json: { name: `${secret}3`, access_level: "restricted", groups: [`${secret},comma`] },
    }), // 422
    await ke.send("PATCH", `${collectionsPath(wsA)}/${item.id}`, {
      json: { local_only: false, name: secret },
    }), // 403
    await ke.send("PUT", `${collectionsPath(wsA)}/${item.id}/access`, {
      json: { access_level: "restricted", groups: [`${secret}-group`] },
    }), // 403
    await admin.send("POST", `${collectionsPath(wsA)}/${item.id}/folders`, {
      json: { name: `${secret}-f`, org_id: wsOther },
    }), // 422
  ];
  for (const answer of answers) {
    expect(answer.status).toBeGreaterThanOrEqual(400);
    expect(answer.text, `${answer.method} ${answer.status}`).not.toContain("leak-");
    expect(Object.keys(answer.json as object)).toEqual(["detail"]);
    expect((answer.json as { detail: string }).detail).toMatch(/^[a-z_]+$/);
  }
  await admin.send("PATCH", `${collectionsPath(wsA)}/${item.id}`, {
    json: { name: `${secret} renamed` },
  });
  await mustCreateFolder(admin, wsA, item.id, { name: `${secret}-folder` });
  const values = auditValues([item.id]);
  expect(values.length).toBeGreaterThan(0);
  for (const value of values) expect(value).toMatch(/^[a-z_]*\|[a-z_]*$/);
  expect(apiLogsSince(600)).not.toContain("leak-");
});

test("ATTACK-7: groups are case-insensitive: 'Managers' is stored and shown as 'managers'", async ({
  browser,
}) => {
  const admin = await api("admin");
  const item = await mustCreateCollection(admin, wsA, {
    name: `Case ${MARK}`,
    access_level: "restricted",
    groups: ["Managers"],
  });
  expect(item.groups).toEqual(["managers"]);
  await withSession(browser, admin, async (page) => {
    await openKnowledge(page, wsA);
    await expect(rowOf(page, `Case ${MARK}`).getByTestId("access-badge")).toHaveText(
      "Restricted · managers",
    );
  });
  const put = await admin.send("PUT", `${collectionsPath(wsA)}/${item.id}/access`, {
    json: { access_level: "restricted", groups: ["MANAGERS"] },
  });
  expect(put.status, put.text).toBe(200);
  expect(auditOf(item.id).map((row) => row.action)).toEqual(["collection.created"]); // same group, no event
});

// ---------------------------------------------------------------------------------------------
// Console and network on the main pages
// ---------------------------------------------------------------------------------------------

test("TC-NET-1: the list and detail pages load without console errors, failed requests or identity parameters, and none takes more than 1 s", async ({
  browser,
}) => {
  await withSession(browser, await api("ke"), async (page) => {
    const slow: string[] = [];
    const timings = new Map<string, number>();
    page.on("request", (request) => timings.set(request.url(), Date.now()));
    page.on("response", (response) => {
      const started = timings.get(response.url());
      if (started !== undefined && Date.now() - started > 1000) slow.push(response.url());
    });
    const seen = watch(page);
    await openKnowledge(page, wsA);
    await openDetail(page, wsA, idOf("handbook"));
    const unnamed = () =>
      page.evaluate(() =>
        [...document.querySelectorAll("input, select, textarea")]
          .filter((field) => !field.id && !field.getAttribute("name"))
          .map((field) => field.outerHTML.slice(0, 80)),
      );
    expect(await unnamed(), "detail page fields without id or name").toEqual([]);
    await openSettings(page);
    expect(await unnamed(), "dialog fields without id or name").toEqual([]);
    await page.keyboard.press("Escape");
    await openKnowledge(page, wsA);
    await expect(page.getByTestId("collection-row").first()).toBeVisible();
    expect(await unnamed(), "list fields without id or name").toEqual([]);
    expect(withoutStatuses(seen.problems, [])).toEqual([]);
    expect(
      seen.requests.filter((request) =>
        /[?&](user_?id|org_?id|workspace_?id|groups?|role|permissions?)=/i.test(request.url),
      ),
    ).toEqual([]);
    expect.soft(slow, "requests slower than 1 s").toEqual([]);
  });
});

test("AC8 TC-8-4: the list follows the artboard in layout and colour: legend cards in one row, accent links, full-width search, muted Any allowed model", async ({
  browser,
}) => {
  await withSession(browser, await api("poAdmin"), async (page) => {
    await openKnowledge(page, peopleOps);
    await expect(page.getByTestId("collection-row").first()).toBeVisible();
    const facts = await page.evaluate(() => {
      const legend = document.querySelector('[data-testid="access-legend"]');
      const items = [...(legend?.children ?? [])] as HTMLElement[];
      const tops = items.map((item) => Math.round(item.getBoundingClientRect().top));
      const borders = items.map((item) => Number.parseFloat(getComputedStyle(item).borderTopWidth));
      const link = document.querySelector('[data-testid="collection-row"] a') as HTMLElement;
      const search = document.querySelector(
        'input[type="search"], input[placeholder]',
      ) as HTMLElement;
      const table = document.querySelector('[data-testid="collections-table"]') as HTMLElement;
      const plain = document.querySelector('[data-testid="data-handling"]') as HTMLElement;
      return {
        count: items.length,
        sameRow: new Set(tops).size === 1,
        bordered: borders.every((width) => width >= 1),
        link: getComputedStyle(link).color,
        search: search.getBoundingClientRect().width,
        table: table.getBoundingClientRect().width,
        plain: getComputedStyle(plain).color,
      };
    });
    expect(facts.count).toBe(3);
    expect(facts.sameRow, "the three legend cards are on one row").toBe(true);
    expect(facts.bordered, "each legend item is a bordered card").toBe(true);
    expect(facts.link, "collection links use the accent colour").toBe("rgb(35, 70, 199)");
    expect(facts.search, "search is (almost) full width").toBeGreaterThan(facts.table * 0.8);
    expect(facts.plain, "Any allowed model is muted (not the primary text colour)").not.toBe(
      "rgb(22, 24, 29)",
    );
  });
  await withSession(browser, await api("ke"), async (page) => {
    await openDetail(page, wsA, idOf("handbook"));
    const crumb = page
      .getByRole("navigation", { name: "Breadcrumb" })
      .getByRole("link", { name: "Knowledge" });
    expect(await crumb.evaluate((node) => getComputedStyle(node).color)).toBe("rgb(35, 70, 199)");
  });
});

test("Q1-2 / Q1-3: Escape returns focus to the opener in every dialog; the folder delete dialog keeps Escape and its focus trap after a 409", async ({
  browser,
}) => {
  const keApi = await api("ke");
  const item = await mustCreateCollection(keApi, wsA, {
    name: `Focus ${MARK}`,
    access_level: "authenticated",
  });
  const parent = await mustCreateFolder(keApi, wsA, item.id, { name: "Parent" });
  await mustCreateFolder(keApi, wsA, item.id, { name: "Child", parent_id: parent.id });
  await withSession(browser, keApi, async (page) => {
    await openKnowledge(page, wsA);
    // The list: New collection, by Escape and by Cancel.
    const opener = page.getByTestId("new-collection");
    await opener.click();
    await expect(page.getByTestId("collection-dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("collection-dialog")).toBeHidden();
    await expect(opener, "new collection (Escape)").toBeFocused();
    await opener.click();
    await page.getByTestId("collection-dialog").getByRole("button", { name: "Cancel" }).click();
    await expect(opener, "new collection (Cancel)").toBeFocused();

    // The detail page.
    await openDetail(page, wsA, item.id);
    const checks: [string, () => ReturnType<typeof page.getByRole>, string][] = [
      ["settings", () => page.getByTestId("collection-settings"), "collection-dialog"],
      [
        "delete collection",
        () => page.getByTestId("delete-collection"),
        "delete-collection-dialog",
      ],
      ["new folder", () => page.getByTestId("new-folder"), "folder-dialog"],
      [
        "add subfolder",
        () => page.getByRole("button", { name: "Add subfolder to Parent" }),
        "folder-dialog",
      ],
      ["rename", () => page.getByRole("button", { name: "Rename Parent" }), "folder-dialog"],
      [
        "delete child",
        () => page.getByRole("button", { name: "Delete Child" }),
        "confirm-folder-delete",
      ],
    ];
    for (const [label, find, dialogId] of checks) {
      await find().click();
      await expect(page.getByTestId(dialogId), label).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByTestId(dialogId), label).toBeHidden();
      await expect(find(), `${label}: focus returns to the opener`).toBeFocused();
    }

    // A 409 inside the folder delete dialog: the dialog stays usable.
    const deleteParent = page.getByRole("button", { name: "Delete Parent" });
    await deleteParent.click();
    const confirm = page.getByTestId("confirm-folder-delete");
    await confirm.getByRole("button", { name: "Delete folder" }).click();
    await expectAlert(page, COPY.folderNotEmpty);
    for (let press = 0; press < 4; press++) {
      await page.keyboard.press("Tab");
      expect(
        await page.evaluate(
          () => document.activeElement?.closest('[data-testid="confirm-folder-delete"]') !== null,
        ),
        `focus stays in the dialog after Tab ${press + 1}`,
      ).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(confirm).toBeHidden();
    await expect(deleteParent, "focus returns after the error").toBeFocused();
    await expect(folderRow(page, "Parent")).toHaveCount(1);
  });

  // The Public confirmation: Escape and Cancel keep the form open and focus inside it.
  await withSession(browser, await api("admin"), async (page) => {
    await openKnowledge(page, wsA);
    const dialog = await openNewCollection(page);
    await fillCollectionForm(page, { name: `Focus public ${MARK}`, access: "Public" });
    await dialog.getByRole("button", { name: "Create collection" }).click();
    const confirm = page.getByTestId("confirm-public-dialog");
    await expect(confirm).toBeVisible();
    await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(confirm).toBeHidden();
    await expect(dialog).toBeVisible();
    expect(
      await page.evaluate(
        () => document.activeElement?.closest('[data-testid="collection-dialog"]') !== null,
      ),
    ).toBe(true);
    expect(
      (await listOf(await api("admin"), wsA)).some((entry) =>
        entry.name.startsWith("Focus public"),
      ),
    ).toBe(false);
  });
});

test("AC6 TC-6-3 / AC5: an action on a collection that was deleted elsewhere shows the Not found page, not a generic error", async ({
  browser,
}) => {
  const keApi = await api("ke");
  const adminApi = await api("admin");
  const notFound = async (page: Page) => {
    await expect(page.getByText(/not found/i).first()).toBeVisible();
    await expect(page.getByTestId("collection-detail")).toHaveCount(0);
    await expect(page.getByText(COPY.generic)).toHaveCount(0);
  };
  const make = async (label: string, localOnly = false) => {
    const created = await mustCreateCollection(keApi, wsA, {
      name: `Gone ${label} ${MARK}`,
      access_level: "authenticated",
      local_only: localOnly,
    });
    return created;
  };
  await withSession(browser, adminApi, async (page) => {
    // Save settings (AC5: the local-only flag) after a delete elsewhere.
    const local = await make("flag", true);
    await openDetail(page, wsA, local.id);
    const dialog = await openSettings(page);
    await dialog.getByRole("checkbox", { name: /^Local model only/ }).uncheck();
    expect((await keApi.send("DELETE", `${collectionsPath(wsA)}/${local.id}`)).status).toBe(204);
    await dialog.getByRole("button", { name: "Save" }).click();
    await notFound(page);

    // Save the access level after a delete elsewhere.
    const access = await make("access");
    await openDetail(page, wsA, access.id);
    const accessDialog = await openSettings(page);
    await fillCollectionForm(page, { access: "Restricted", groups: "hr" });
    expect((await keApi.send("DELETE", `${collectionsPath(wsA)}/${access.id}`)).status).toBe(204);
    await accessDialog.getByRole("button", { name: "Save" }).click();
    await notFound(page);

    // Delete (AC6) after a delete elsewhere.
    const del = await make("delete");
    await openDetail(page, wsA, del.id);
    await page.getByTestId("delete-collection").click();
    await page
      .getByTestId("delete-collection-dialog")
      .getByRole("textbox", { name: `Type ${del.name} to confirm` })
      .fill(del.name);
    expect((await keApi.send("DELETE", `${collectionsPath(wsA)}/${del.id}`)).status).toBe(204);
    await page.getByTestId("confirm-delete-collection").click();
    await notFound(page);

    // New folder after a delete elsewhere.
    const folder = await make("folder");
    await openDetail(page, wsA, folder.id);
    await page.getByTestId("new-folder").click();
    const folderDialog = page.getByTestId("folder-dialog");
    await folderDialog.getByRole("textbox", { name: "Folder name" }).fill("Orphan");
    expect((await keApi.send("DELETE", `${collectionsPath(wsA)}/${folder.id}`)).status).toBe(204);
    await folderDialog.getByRole("button", { name: "Create folder" }).click();
    await notFound(page);
  });
});

test("TC-A11Y-1: every folder action button is at least 24 x 24 px (design rule of DSN-01)", () => {
  expect(smallTargets).toEqual([]);
});
