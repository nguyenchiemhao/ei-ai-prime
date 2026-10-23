// EA-33 (KB-02): permissions (AC8) and the attack list: tenant isolation, sessions and CSRF, identity
// parameters, file names, logs, Content-Length. Black-box specs from .work/EA-33/contract.md and
// ticket.md only. Runs against a running, migrated and seeded stack:
//   npm run up -- --no-model && npm run seed && npm run e2e -- e2e/knowledge/EA-33-upload-process-documents-access.spec.ts
// Data: seeded accounts of both Organizations. Everything created carries the marker `qa-EA33-<run>`:
// own folders in "Employee Handbook" and in the Sông Hàn Retail collection, own collections. The afterAll
// hook removes it all and proves the row counts equal the counts before the run.
import fs from "node:fs";
import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import {
  DEMO_ORG,
  compose,
  expectSameAnswer,
  peopleOpsId,
  rows,
  sql,
  type ApiResult,
  type ApiSession,
} from "../support/ea22";
import { withSession } from "../support/ea23";
import { collectionsPath, json, type CollectionItem } from "../support/ea32";
import {
  MARK,
  SCREENSHOTS_33,
  SONGHAN_ORG,
  apiOf,
  auditRowsContaining,
  buildPdf,
  chunkRows,
  chunksPath,
  cleanupAll,
  counts,
  deleteDoc,
  docsPath,
  filler,
  listDocs,
  logsOfApi,
  makeCollection,
  makeFolder,
  markerRows,
  mustReady,
  mustUpload,
  orgOfDocument,
  randomJunk,
  rawUpload,
  plaintextHits,
  storedFiles,
  storedHeader,
  textOf,
  textPath,
  uploadRaw,
  waitStatus,
  waitStoredGone,
  type Counts,
  type DocumentItem,
  type FolderItem33,
  type Loc,
} from "../support/ea33";

test.describe.configure({ mode: "serial", timeout: 240_000 });

let ws = "";
let col = "";
let engineeringWs = "";
let baseline: Counts | undefined;
let linh: ApiSession;
let thao: ApiSession;
let minh: ApiSession;
let son: ApiSession;
let ha: ApiSession;
let quang: ApiSession;
let ngan: ApiSession;

function loc(folder: FolderItem33): Loc {
  return { ws, col, folder: folder.id };
}

const SMALL = (): Buffer => Buffer.from(filler("zqsmall", 300));

type Route = { label: string; run: (api: ApiSession) => Promise<ApiResult> };

/** Every route of the contract for one set of ids. Upload sends a small valid TXT. */
function routesOf(ids: { ws: string; col: string; folder: string; doc: string }): Route[] {
  const at: Loc = { ws: ids.ws, col: ids.col, folder: ids.folder };
  return [
    { label: "upload", run: (api) => uploadRaw(api, at, `${MARK}-probe.txt`, SMALL()) },
    { label: "list", run: (api) => api.send("GET", docsPath(ids.ws, ids.col)) },
    {
      label: "list by folder",
      run: (api) => api.send("GET", `${docsPath(ids.ws, ids.col)}?folder_id=${ids.folder}`),
    },
    { label: "text", run: (api) => api.send("GET", textPath(ids.ws, ids.col, ids.doc)) },
    { label: "chunks", run: (api) => api.send("GET", chunksPath(ids.ws, ids.col, ids.doc)) },
    { label: "delete", run: (api) => deleteDoc(api, ids.ws, ids.col, ids.doc) },
  ];
}

function randomIds(): { ws: string; col: string; folder: string; doc: string } {
  return { ws: randomUUID(), col: randomUUID(), folder: randomUUID(), doc: randomUUID() };
}

/** Calls every route with `ids` and expects the answer of a random id (404 not_found, same body). */
async function expectNotFoundLikeUnknown(
  api: ApiSession,
  ids: { ws: string; col: string; folder: string; doc: string },
  label: string,
): Promise<void> {
  const unknown = routesOf(randomIds());
  const actual = routesOf(ids);
  for (let index = 0; index < actual.length; index++) {
    const route = actual[index] as Route;
    const baselineAnswer = await (unknown[index] as Route).run(api);
    expect(baselineAnswer.status, `${label} ${route.label}: random ids`).toBe(404);
    expect(baselineAnswer.json).toEqual({ detail: "not_found" });
    const answer = await route.run(api);
    expectSameAnswer(answer, baselineAnswer, `${label} ${route.label}`);
  }
}

test.beforeAll(async () => {
  await cleanupAll();
  fs.mkdirSync(SCREENSHOTS_33, { recursive: true });
  baseline = counts();
  ws = peopleOpsId();
  engineeringWs = rows(
    `select id from workspaces where org_id = '${DEMO_ORG}' and name = 'Engineering'`,
  )[0] as string;
  linh = await apiOf("linh");
  thao = await apiOf("thao");
  minh = await apiOf("minh");
  son = await apiOf("son");
  ha = await apiOf("ha");
  quang = await apiOf("quang");
  ngan = await apiOf("ngan");
  const result = await linh.send("GET", collectionsPath(ws));
  const handbook = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.name === "Employee Handbook",
  );
  expect(handbook, "precondition: the demo seed created Employee Handbook").toBeTruthy();
  col = (handbook as CollectionItem).id;
});

test.afterAll(async () => {
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the EA-33 marker left behind").toEqual([]);
});

// ---------------------------------------------------------------------------------------------
// AC8 Permission
// ---------------------------------------------------------------------------------------------

test("AC8: a Viewer sees the No access page for the collection and the upload API answers 403 forbidden without creating a row; Builder, Knowledge Editor and Workspace Admin upload (201)", async ({
  browser,
}) => {
  const folder = await makeFolder(linh, ws, col, "ac8-roles");
  const keeper = await mustReady(thao, loc(folder), `${MARK}-ac8-keeper.txt`, SMALL());

  await withSession(browser, son, async (page) => {
    await page.goto(`/w/${ws}/knowledge/${col}`);
    await expect(page.getByTestId("area-forbidden")).toBeVisible();
    await expect(page.getByTestId("area-forbidden").getByRole("heading", { level: 1 })).toHaveText(
      "No access",
    );
    await expect(page.getByTestId("upload-files")).toHaveCount(0);
    await expect(page.getByTestId("drop-zone")).toHaveCount(0);
    await page.screenshot({ path: `${SCREENSHOTS_33}/ac8-viewer-no-access.png` });
  });

  const viewerUpload = await uploadRaw(son, loc(folder), `${MARK}-ac8-viewer.txt`, SMALL());
  expect(viewerUpload.status, viewerUpload.text).toBe(403);
  expect(viewerUpload.json).toEqual({ detail: "forbidden" });

  for (const [label, session] of [
    ["builder", minh],
    ["knowledge editor", thao],
    ["workspace admin", linh],
  ] as const) {
    const result = await uploadRaw(
      session,
      loc(folder),
      `${MARK}-ac8-${label.replace(" ", "-")}.txt`,
      SMALL(),
    );
    expect(result.status, `${label}: ${result.text}`).toBe(201);
    expect(json<DocumentItem>(result).status).toBe("queued");
  }
  const listed = await listDocs(linh, ws, col, folder.id);
  expect(listed.map((item) => item.name).sort()).toEqual(
    [
      `${MARK}-ac8-builder.txt`,
      `${MARK}-ac8-keeper.txt`,
      `${MARK}-ac8-knowledge-editor.txt`,
      `${MARK}-ac8-workspace-admin.txt`,
    ].sort(),
  );
  expect(listed.find((item) => item.id === keeper.id)).toBeTruthy();
});

test("AC8 TC-8-2: Viewer, Reviewer and Developer get 403 forbidden on every route (also with random ids: permission is checked before ids); nothing changes", async () => {
  const folder = await makeFolder(linh, ws, col, "ac8-denied");
  const doc = await mustReady(thao, loc(folder), `${MARK}-ac8-denied.txt`, SMALL());
  for (const [label, session] of [
    ["viewer", son],
    ["reviewer", ha],
    ["developer", quang],
  ] as const) {
    for (const ids of [
      { ws, col, folder: folder.id, doc: doc.id },
      { ws, col: randomUUID(), folder: randomUUID(), doc: randomUUID() },
    ]) {
      for (const route of routesOf(ids)) {
        const result = await route.run(session);
        expect(result.status, `${label} ${route.label}: ${result.text}`).toBe(403);
        expect(result.json, `${label} ${route.label}`).toEqual({ detail: "forbidden" });
      }
    }
  }
  const after = await listDocs(linh, ws, col, folder.id);
  expect(after.map((item) => item.id)).toEqual([doc.id]);
  expect(chunkRows(doc.id)).toBeGreaterThan(0);
  expect(storedFiles(DEMO_ORG, doc.id)).toBeGreaterThan(0);
});

test("AC8 TC-8-3: no session and an expired or invalid session are 401 unauthenticated; a missing or wrong CSRF header is 403 and changes nothing", async () => {
  const folder = await makeFolder(linh, ws, col, "ac8-session");
  const doc = await mustReady(thao, loc(folder), `${MARK}-ac8-session.txt`, SMALL());
  const csrf = thao.csrfCookie as string;
  expect(csrf, "precondition: the session has a CSRF cookie").toBeTruthy();

  const anonymous = { ei_csrf: csrf };
  const expired = { ei_csrf: csrf, ei_session: `${randomUUID()}.${"x".repeat(43)}` };
  for (const [label, cookies] of [
    ["no session", anonymous],
    ["invalid session", expired],
  ] as const) {
    const upload = await uploadRaw(thao, loc(folder), `${MARK}-ac8-anon.txt`, SMALL(), { cookies });
    expect(upload.status, `${label} upload: ${upload.text}`).toBe(401);
    expect(upload.json).toEqual({ detail: "unauthenticated" });
    for (const path of [
      docsPath(ws, col),
      textPath(ws, col, doc.id),
      chunksPath(ws, col, doc.id),
    ]) {
      const read = await thao.send("GET", path, { cookies });
      expect(read.status, `${label} GET ${path}`).toBe(401);
      expect(read.json).toEqual({ detail: "unauthenticated" });
    }
    const removal = await thao.send("DELETE", `${docsPath(ws, col)}/${doc.id}`, { cookies });
    expect(removal.status, `${label} delete`).toBe(401);
  }

  const noCsrf = await uploadRaw(thao, loc(folder), `${MARK}-ac8-nocsrf.txt`, SMALL(), {
    csrf: "none",
  });
  expect(noCsrf.status, noCsrf.text).toBe(403);
  const wrongCsrf = await uploadRaw(thao, loc(folder), `${MARK}-ac8-wrongcsrf.txt`, SMALL(), {
    csrf: "not-the-token",
  });
  expect(wrongCsrf.status, wrongCsrf.text).toBe(403);
  const deleteNoCsrf = await thao.send("DELETE", `${docsPath(ws, col)}/${doc.id}`, {
    csrf: "none",
  });
  expect(deleteNoCsrf.status, deleteNoCsrf.text).toBe(403);
  const listed = await listDocs(linh, ws, col, folder.id);
  expect(listed.map((item) => item.id)).toEqual([doc.id]);
});

test("AC8 TC-8-4: a Viewer that announces a 50 MB body gets the 403 at once, without the server reading the body", async () => {
  const folder = await makeFolder(linh, ws, col, "ac8-fast");
  const answer = await rawUpload({
    loc: loc(folder),
    api: son,
    name: `${MARK}-ac8-fast.txt`,
    contentLength: 52_428_800,
    body: Buffer.alloc(1024, 0x41),
  });
  expect(answer.status, answer.text).toBe(403);
  expect(answer.json).toEqual({ detail: "forbidden" });
  expect(answer.ms, "answered without waiting for the 50 MB body").toBeLessThan(5000);
  expect(await listDocs(linh, ws, col, folder.id)).toEqual([]);
});

// ---------------------------------------------------------------------------------------------
// Attack list: tenant isolation
// ---------------------------------------------------------------------------------------------

test("Attack TC-A-1: ids of the other Organization are answered like unknown ids on every route, in both directions, and nothing changes", async () => {
  const songhanWs = rows(
    `select id from workspaces where org_id = '${SONGHAN_ORG}' and name = 'Customer Care'`,
  )[0] as string;
  expect(songhanWs, "precondition: Sông Hàn Retail Workspace Customer Care").toBeTruthy();
  const songhanList = await ngan.send("GET", collectionsPath(songhanWs));
  expect(songhanList.status, songhanList.text).toBe(200);
  const songhanCol = json<{ collections: CollectionItem[] }>(songhanList).collections[0];
  expect(songhanCol, "precondition: the Sông Hàn Retail collection").toBeTruthy();
  const foreignCol = (songhanCol as CollectionItem).id;
  const foreignFolder = await makeFolder(ngan, songhanWs, foreignCol, "foreign");
  const foreignDoc = await mustReady(
    ngan,
    { ws: songhanWs, col: foreignCol, folder: foreignFolder.id },
    `${MARK}-foreign.txt`,
    SMALL(),
  );
  const ownFolder = await makeFolder(linh, ws, col, "iso");
  const ownDoc = await mustReady(thao, loc(ownFolder), `${MARK}-own.txt`, SMALL());

  const foreign = { ws: songhanWs, col: foreignCol, folder: foreignFolder.id, doc: foreignDoc.id };
  const own = { ws, col, folder: ownFolder.id, doc: ownDoc.id };
  await expectNotFoundLikeUnknown(thao, foreign, "Mekong user, Sông Hàn ids");
  await expectNotFoundLikeUnknown(
    thao,
    { ...own, ws: songhanWs },
    "Mekong user, Sông Hàn Workspace id",
  );
  await expectNotFoundLikeUnknown(
    thao,
    { ...own, col: foreignCol, folder: foreignFolder.id, doc: foreignDoc.id },
    "Mekong Workspace, Sông Hàn collection",
  );
  await expectNotFoundLikeUnknown(ngan, own, "Sông Hàn user, Mekong ids");
  await expectNotFoundLikeUnknown(ngan, { ...foreign, ws }, "Sông Hàn user, Mekong Workspace id");

  const stillForeign = await listDocs(ngan, songhanWs, foreignCol);
  expect(stillForeign.map((item) => item.id)).toEqual([foreignDoc.id]);
  const stillOwn = await listDocs(thao, ws, col, ownFolder.id);
  expect(stillOwn.map((item) => item.id)).toEqual([ownDoc.id]);
  expect((await textOf(ngan, songhanWs, foreignCol, foreignDoc.id)).text).toContain("zqsmall");
  expect(Number(sql(`select count(*) from documents where id = '${foreignDoc.id}'`))).toBe(1);
  expect(orgOfDocument(foreignDoc.id)).toBe(SONGHAN_ORG);
  expect(orgOfDocument(ownDoc.id)).toBe(DEMO_ORG);
  expect(
    await listDocs(ngan, songhanWs, foreignCol),
    "no probe landed in the other Organization",
  ).toHaveLength(1);
});

test("Attack TC-A-2: ids of another Workspace of the same Organization (People Ops vs Engineering) are 404 not_found", async () => {
  const engineeringList = await linh.send("GET", collectionsPath(engineeringWs));
  expect(engineeringList.status, engineeringList.text).toBe(200);
  const engineeringCol = json<{ collections: CollectionItem[] }>(engineeringList).collections[0];
  expect(engineeringCol, "precondition: an Engineering collection").toBeTruthy();
  const folder = await makeFolder(linh, ws, col, "cross-ws");
  const doc = await mustReady(thao, loc(folder), `${MARK}-cross-ws.txt`, SMALL());
  const engineeringDetail = await linh.send(
    "GET",
    `${collectionsPath(engineeringWs)}/${(engineeringCol as CollectionItem).id}`,
  );
  const engineeringFolders = json<{ folders: FolderItem33[] }>(engineeringDetail).folders;
  const engineeringFolder = engineeringFolders[0]?.id ?? randomUUID();

  // Org admin, allowed in both Workspaces: the ids of the other Workspace are unknown.
  await expectNotFoundLikeUnknown(
    linh,
    { ws: engineeringWs, col, folder: folder.id, doc: doc.id },
    "People Ops ids under the Engineering Workspace",
  );
  await expectNotFoundLikeUnknown(
    linh,
    {
      ws,
      col: (engineeringCol as CollectionItem).id,
      folder: engineeringFolder,
      doc: doc.id,
    },
    "Engineering collection under the People Ops Workspace",
  );
  // A Knowledge Editor of People Ops has no role in Engineering: refused (403) or unknown (404), never served.
  for (const route of routesOf({ ws: engineeringWs, col, folder: folder.id, doc: doc.id })) {
    const result = await route.run(thao);
    expect([403, 404], `${route.label}: ${result.text}`).toContain(result.status);
  }
  expect((await listDocs(linh, ws, col, folder.id)).map((item) => item.id)).toEqual([doc.id]);
});

test("Attack TC-A-3: a folder or document of another collection (same Workspace) in the path is 404 not_found and nothing changes", async () => {
  const other = await makeCollection(linh, ws, "other");
  const otherFolder = await makeFolder(linh, ws, other.id, "other-folder");
  const otherDoc = await mustReady(
    thao,
    { ws, col: other.id, folder: otherFolder.id },
    `${MARK}-other.txt`,
    SMALL(),
  );
  const folder = await makeFolder(linh, ws, col, "ownfolder");
  const doc = await mustReady(thao, loc(folder), `${MARK}-ownfile.txt`, SMALL());

  const intoOther = await uploadRaw(
    thao,
    { ws, col, folder: otherFolder.id },
    `${MARK}-misplaced.txt`,
    SMALL(),
  );
  expect(intoOther.status, intoOther.text).toBe(404);
  expect(intoOther.json).toEqual({ detail: "not_found" });
  const filtered = await thao.send("GET", `${docsPath(ws, col)}?folder_id=${otherFolder.id}`);
  expect(filtered.status, filtered.text).toBe(404);
  expect(filtered.json).toEqual({ detail: "not_found" });
  for (const route of [
    { label: "text", run: () => thao.send("GET", textPath(ws, col, otherDoc.id)) },
    { label: "chunks", run: () => thao.send("GET", chunksPath(ws, col, otherDoc.id)) },
    { label: "delete", run: () => deleteDoc(thao, ws, col, otherDoc.id) },
  ]) {
    const result = await route.run();
    expect(result.status, `${route.label}: ${result.text}`).toBe(404);
    expect(result.json).toEqual({ detail: "not_found" });
  }
  expect((await listDocs(thao, ws, other.id)).map((item) => item.id)).toEqual([otherDoc.id]);
  expect(await listDocs(thao, ws, col, folder.id)).toHaveLength(1);
  expect((await textOf(thao, ws, col, doc.id)).text).toContain("zqsmall");
  expect(
    await listDocs(thao, ws, col, folder.id),
    "the misplaced file created no row",
  ).toHaveLength(1);
});

test("Attack TC-A-4: org_id, organization_id and X-Org-Id sent by the client are ignored: the document belongs to the caller's Organization", async () => {
  const folder = await makeFolder(linh, ws, col, "orgparams");
  const query = `?org_id=${SONGHAN_ORG}&organization_id=${SONGHAN_ORG}&tenant=${SONGHAN_ORG}`;
  const result = await uploadRaw(thao, loc(folder), `${MARK}-orgparams.txt`, SMALL(), {
    query,
    headers: { "x-org-id": SONGHAN_ORG, "x-organization-id": SONGHAN_ORG },
  });
  expect(result.status, result.text).toBe(201);
  const item = json<DocumentItem>(result);
  expect(orgOfDocument(item.id)).toBe(DEMO_ORG);
  const done = await waitStatus(thao, ws, col, item.id);
  expect(done.status).toBe("ready");
  const listed = await thao.send(
    "GET",
    `${docsPath(ws, col)}?folder_id=${folder.id}&org_id=${SONGHAN_ORG}`,
    { headers: { "x-org-id": SONGHAN_ORG } },
  );
  expect(listed.status, listed.text).toBe(200);
  expect(json<{ documents: DocumentItem[] }>(listed).documents.map((entry) => entry.id)).toEqual([
    item.id,
  ]);
  expect(storedFiles(DEMO_ORG, item.id), "stored under the caller's Organization").toBeGreaterThan(
    0,
  );
  expect(storedFiles(SONGHAN_ORG, item.id), "not under the claimed Organization").toBe(0);
});

// ---------------------------------------------------------------------------------------------
// Attack list: names, binaries, logs, sizes
// ---------------------------------------------------------------------------------------------

function sha256OfEtcPasswd(): string {
  return compose([
    "exec",
    "-T",
    "api",
    "sh",
    "-c",
    "sha256sum /etc/passwd | cut -d' ' -f1",
  ]).stdout.trim();
}

test("Attack TC-A-5: a path-traversal file name is reduced to its base name and nothing is written outside the Organization's storage", async () => {
  const folder = await makeFolder(linh, ws, col, "traversal");
  const before = sha256OfEtcPasswd();
  const traversal = await uploadRaw(thao, loc(folder), null, SMALL(), {
    rawName: "..%2F..%2Fetc%2Fpasswd.txt",
  });
  expect(traversal.status, traversal.text).toBe(201);
  const item = json<DocumentItem>(traversal);
  expect(item.name).toBe("passwd.txt");
  const nested = await uploadRaw(thao, loc(folder), "a/b/c.txt", SMALL());
  expect(nested.status, nested.text).toBe(201);
  expect(json<DocumentItem>(nested).name).toBe("c.txt");
  const windows = await uploadRaw(thao, loc(folder), "..\\..\\windows\\win.txt", SMALL());
  expect(windows.status, windows.text).toBe(201);
  expect(["win.txt", "..\\..\\windows\\win.txt"]).toContain(json<DocumentItem>(windows).name);
  await waitStatus(thao, ws, col, item.id);
  expect(sha256OfEtcPasswd(), "/etc/passwd unchanged").toBe(before);
  const stray = compose([
    "exec",
    "-T",
    "api",
    "sh",
    "-c",
    "find / -xdev -name passwd.txt -not -path '/proc/*' -not -path '/var/lib/ei-ai/files/*' 2>/dev/null | wc -l",
  ]).stdout.trim();
  expect(Number(stray), "no passwd.txt outside the storage directory").toBe(0);
  expect(storedFiles(DEMO_ORG, item.id)).toBeGreaterThan(0);
});

test("Attack TC-A-6: a renamed binary is Failed (corrupt_file), other files keep processing and the API stays up", async ({
  request,
}) => {
  const folder = await makeFolder(linh, ws, col, "renamed");
  const binary = Buffer.concat([Buffer.from("MZ\u0090\u0000"), randomJunk(16_384)]);
  const bad = await mustUpload(thao, loc(folder), "setup.pdf", binary);
  const good = await mustUpload(thao, loc(folder), `${MARK}-renamed-good.txt`, SMALL());
  const badDone = await waitStatus(thao, ws, col, bad.id);
  const goodDone = await waitStatus(thao, ws, col, good.id);
  expect(badDone).toMatchObject({ status: "failed", reason: "corrupt_file" });
  expect(goodDone.status).toBe("ready");
  expect((await request.get("/api/healthz")).status()).toBe(200);
});

test("Attack TC-A-7: file names and document text never appear in the API logs or in audit_events, for ready and failed files, after removal too", async () => {
  const folder = await makeFolder(linh, ws, col, "logs");
  const secretName = `${MARK}-secret-name.txt`;
  const secretText = `${MARK}-secret-text`;
  const body = Buffer.from(`${secretText} ${filler("zqlog", 600)}`);
  const ok = await mustReady(thao, loc(folder), secretName, body);
  const brokenName = `${MARK}-secret-broken.pdf`;
  const broken = await mustUpload(thao, loc(folder), brokenName, randomJunk(2048));
  await waitStatus(thao, ws, col, broken.id);
  const scanned = await mustUpload(
    thao,
    loc(folder),
    `${MARK}-secret-scan.pdf`,
    buildPdf(["x", "y"]),
  );
  await waitStatus(thao, ws, col, scanned.id);
  // Read paths too: the text and chunk routes must not log what they return.
  expect((await textOf(thao, ws, col, ok.id)).text).toContain(secretText);
  expect((await thao.send("GET", chunksPath(ws, col, ok.id))).status).toBe(200);
  expect((await thao.send("GET", textPath(ws, col, broken.id))).status).toBe(409);
  for (const id of [ok.id, broken.id, scanned.id])
    expect((await deleteDoc(thao, ws, col, id)).status).toBe(204);

  const logs = logsOfApi();
  for (const secret of [
    secretName,
    secretText,
    brokenName,
    "secret-name",
    "secret-text",
    "secret-broken",
  ]) {
    expect(logs.includes(secret), `API logs contain "${secret}"`).toBe(false);
  }
  for (const secret of ["secret-name", "secret-text", "secret-broken", "secret-scan"]) {
    expect(auditRowsContaining(secret), `audit_events contain "${secret}"`).toBe(0);
  }
});

test("Attack TC-A-8: a Content-Length above the limit is refused before the body is read (413 file_too_large), also when the real body is short", async () => {
  const folder = await makeFolder(linh, ws, col, "lengthlie");
  const lie = await rawUpload({
    loc: loc(folder),
    api: thao,
    name: `${MARK}-lie.txt`,
    contentLength: 60_000_000,
    body: Buffer.from("short body"),
  });
  expect(lie.status, lie.text).toBe(413);
  expect(lie.json).toEqual({ detail: "file_too_large" });
  const justOver = await rawUpload({
    loc: loc(folder),
    api: thao,
    name: `${MARK}-over.txt`,
    contentLength: 52_428_801,
  });
  expect(justOver.status, justOver.text).toBe(413);
  expect(justOver.json).toEqual({ detail: "file_too_large" });
  expect(justOver.ms, "refused without waiting for the body").toBeLessThan(5000);
  expect(await listDocs(linh, ws, col, folder.id), "no row created").toEqual([]);
});

test("Attack TC-A-9: originals are encrypted on disk: no plaintext, header EIA+0x01, size +32, only under the caller's Organization directory, gone after Remove", async () => {
  const folder = await makeFolder(linh, ws, col, "plaintext");
  const marker = `${MARK}-disk-marker`;
  const content = Buffer.from(`${marker} `.repeat(20));
  const item = await mustReady(thao, loc(folder), `${MARK}-disk.txt`, content);
  expect(item.status).toBe("ready");
  const preview = await thao.send("GET", `${docsPath(ws, col)}/${item.id}/text`);
  expect(preview.status, preview.text).toBe(200);
  expect(preview.text).toContain(marker);
  expect(plaintextHits(marker), "grep -rl finds no file").toBe(0);
  expect(storedFiles(DEMO_ORG, item.id), "under the Mekong Devworks directory").toBe(1);
  expect(storedFiles(SONGHAN_ORG, item.id), "not under the Sông Hàn Retail directory").toBe(0);
  const header = storedHeader(DEMO_ORG, item.id);
  expect(header, "stored file readable").not.toBeNull();
  expect(header?.head).toBe("45494101");
  expect(header?.size).toBe(content.length + 32);
  const removed = await deleteDoc(thao, ws, col, item.id);
  expect(removed.status, removed.text).toBe(204);
  expect(await waitStoredGone(DEMO_ORG, item.id, 30_000), "gone within seconds").toBe(true);
});
