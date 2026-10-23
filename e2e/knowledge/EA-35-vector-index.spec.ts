// EA-35 (KB-04): vector index per Organization (thin slice: vectors only; keyword, AC2, AC5 and the 300 ms
// NFR are deferred by the owner and have no cases). Black-box specs written from .work/EA-35/contract.md
// and ticket.md only. Runs against a running, migrated and seeded stack WITH the model profile:
//   npm run up && npm run seed && npm run e2e -- e2e/knowledge/EA-35-vector-index.spec.ts
// Needs the `embedding` service healthy (docker compose ps embedding). Operator CLI: ei-ai index ...
// Data: seeded accounts (Linh Tran admin, Thao Nguyen knowledge editor, Ngân Trịnh Sông Hàn admin); every
// folder, collection and file is named with the marker `qa-EA35-<run>`; seed rows are never changed.
// cleanupAll() deletes the documents (their vectors go with them), folders and collections; afterAll proves
// the row counts equal the counts before the run. Other files: ...-slow.spec.ts (@slow: race, sentinel in
// logs, embedding service stopped), ...-perf.spec.ts (@perf: 50-page PDF).
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import {
  DEMO_ORG as ORG,
  ROOT,
  UUID,
  compose,
  peopleOpsId,
  rows,
  sleep,
  sql,
  type ApiSession,
} from "../support/ea22";
import { collectionsPath, json, type CollectionItem, type FolderItem } from "../support/ea32";
import {
  SONGHAN_ORG as SH_ORG,
  TERMINAL,
  apiOf,
  buildScannedPdf,
  chunksOf,
  uploadRaw,
  waitStatus,
  type DocumentItem,
  type Loc,
} from "../support/ea33";
import { seed } from "../support/ea94";
import {
  INDEX_DEADLINE_MS,
  MARK,
  MODEL_ID,
  MODEL_REF,
  MODEL_VERSION,
  accessFingerprint,
  cleanupAll,
  counts,
  fingerprint,
  getDoc,
  indexCli,
  indexSearch,
  indexStatus,
  isHitLine,
  leaveText,
  makeCollection,
  makeFolder,
  markerRows,
  readyCountOf,
  readyDoc,
  reindex,
  removeDoc,
  securityText,
  setAccess,
  trackDoc,
  txt,
  uploadDoc,
  vectorCount,
  vectorIds,
  vectorRows,
  waitIndexed,
  type Counts,
} from "../support/ea35";

test.describe.configure({ mode: "serial", timeout: 300_000 });

let ws = "";
let col = "";
let shWs = "";
let baseline: Counts | undefined;
let linh: ApiSession;
let thao: ApiSession;
let ngan: ApiSession;

function loc(folder: FolderItem, collection = col, workspace = ws): Loc {
  return { ws: workspace, col: collection, folder: folder.id };
}

type Fixtures = {
  folder: FolderItem;
  leave: DocumentItem;
  leaveNfd: DocumentItem;
  other: DocumentItem;
  shCol: CollectionItem;
  shFolder: FolderItem;
  shLeave: DocumentItem;
};
let fixtures: Promise<Fixtures> | undefined;

/** Shared documents: Vietnamese leave text (NFC and NFD) and a security text in Mekong, the leave text in Sông Hàn. */
function fixture(): Promise<Fixtures> {
  fixtures ??= (async (): Promise<Fixtures> => {
    const folder = await makeFolder(linh, ws, col, "fx");
    const leaveBody = leaveText(6000);
    const leave = await readyDoc(thao, loc(folder), `${MARK}-fx-leave.txt`, txt(leaveBody));
    const leaveNfd = await readyDoc(
      thao,
      loc(folder),
      `${MARK}-fx-leave-nfd.txt`,
      txt(leaveBody.normalize("NFD")),
    );
    const other = await readyDoc(
      thao,
      loc(folder),
      `${MARK}-fx-security.txt`,
      txt(securityText(6000)),
    );
    const shCol = await makeCollection(ngan, shWs, "sh-fx", "authenticated");
    const shFolder = await makeFolder(ngan, shWs, shCol.id, "sh-fx");
    const shLeave = await readyDoc(
      ngan,
      loc(shFolder, shCol.id, shWs),
      `${MARK}-sh-leave.txt`,
      txt(leaveBody),
    );
    for (const doc of [leave, leaveNfd, other]) await waitIndexed(ORG, doc.id);
    await waitIndexed(SH_ORG, shLeave.id);
    return { folder, leave, leaveNfd, other, shCol, shFolder, shLeave };
  })();
  return fixtures;
}

function orgsOf(ids: string[]): Map<string, string> {
  if (ids.length === 0) return new Map();
  const list = ids.map((id) => `'${id}'`).join(", ");
  const found = rows(`select id || ' ' || org_id from documents where id in (${list})`);
  return new Map(found.map((line) => line.split(" ") as [string, string]));
}

function docIdsOfOrg(org: string): string[] {
  return rows(`select id from documents where org_id = '${org}'`);
}

function collectionIdsOfOrg(org: string): string[] {
  return rows(`select id from collections where org_id = '${org}'`);
}

test.beforeAll(async () => {
  await cleanupAll();
  baseline = counts();
  ws = peopleOpsId();
  linh = await apiOf("linh");
  thao = await apiOf("thao");
  ngan = await apiOf("ngan");
  const result = await linh.send("GET", collectionsPath(ws));
  expect(result.status, result.text).toBe(200);
  const handbook = json<{ collections: CollectionItem[] }>(result).collections.find(
    (entry) => entry.name === "Employee Handbook",
  );
  expect(handbook, "precondition: the demo seed created Employee Handbook").toBeTruthy();
  col = (handbook as CollectionItem).id;
  shWs = rows(
    `select id from workspaces where org_id = '${SH_ORG}' and name = 'Customer Care'`,
  )[0] as string;
  expect(shWs, "precondition: Sông Hàn Retail Workspace Customer Care").toBeTruthy();
});

test.afterAll(async () => {
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the EA-35 marker left behind").toEqual([]);
});

// ---------------------------------------------------------------------------------------------
// AC1 Indexing (vector half)
// ---------------------------------------------------------------------------------------------

test("AC1 TC-1-1: a Ready 2-page Vietnamese TXT has one vector per chunk within 120 s, stays Ready and counts as ready in the collection", async () => {
  const readyBefore = await readyCountOf(linh, ws, col);
  const folder = await makeFolder(linh, ws, col, "ac1-main");
  const queued = await uploadDoc(thao, loc(folder), `${MARK}-ac1-leave.txt`, txt(leaveText(6000)));
  const ready = await waitStatus(thao, ws, col, queued.id);
  expect(ready.status).toBe("ready");

  const { status, elapsedMs } = await waitIndexed(ORG, ready.id, INDEX_DEADLINE_MS, async () => {
    expect((await getDoc(thao, ws, col, ready.id))?.status, "stays ready while indexing").toBe(
      "ready",
    );
  });
  expect(elapsedMs, "indexed within 120 s of Ready").toBeLessThanOrEqual(INDEX_DEADLINE_MS);
  const chunks = await chunksOf(thao, ws, col, ready.id);
  expect(chunks.length).toBeGreaterThan(1);
  expect(status).toMatchObject({ indexed: 1, not_indexed: 0, stale: 0, model: MODEL_REF });
  expect(status.vectors, "one vector per chunk").toBe(chunks.length);
  expect(vectorCount(ready.id)).toBe(chunks.length);
  expect((await getDoc(thao, ws, col, ready.id))?.status).toBe("ready");
  expect(await readyCountOf(linh, ws, col), "collection counts it as ready").toBe(readyBefore + 1);

  const orgStatus = indexStatus(ORG);
  expect(orgStatus.indexed).toBeGreaterThanOrEqual(1);
  expect(orgStatus.ready_documents).toBeGreaterThanOrEqual(orgStatus.indexed);
});

test('AC1 TC-1-2: a one-passage document ("Đơn xin nghỉ phép năm") gets exactly one vector', async () => {
  const folder = await makeFolder(linh, ws, col, "ac1-tiny");
  const doc = await readyDoc(
    thao,
    loc(folder),
    `${MARK}-ac1-tiny.txt`,
    txt("Đơn xin nghỉ phép năm"),
  );
  const { status } = await waitIndexed(ORG, doc.id);
  const chunks = await chunksOf(thao, ws, col, doc.id);
  expect(chunks).toHaveLength(1);
  expect(status.vectors).toBe(1);
  expect(vectorCount(doc.id)).toBe(1);
});

test("AC1 TC-1-3: a document that fails processing (scanned PDF, not ready) has no vectors and does not count as ready", async () => {
  const before = indexStatus(ORG);
  const folder = await makeFolder(linh, ws, col, "ac1-failed");
  const queued = await uploadDoc(thao, loc(folder), `${MARK}-ac1-scan.pdf`, buildScannedPdf(2));
  const done = await waitStatus(thao, ws, col, queued.id, TERMINAL);
  expect(["failed", "not_supported"]).toContain(done.status);
  await sleep(5000);
  expect(vectorCount(queued.id)).toBe(0);
  const after = indexStatus(ORG);
  expect(after.ready_documents).toBe(before.ready_documents);
  expect(after.vectors).toBe(before.vectors);
});

test("AC1 TC-1-4: deleting an indexed document removes its vectors at once", async () => {
  const folder = await makeFolder(linh, ws, col, "ac1-delete");
  const doc = await readyDoc(thao, loc(folder), `${MARK}-ac1-delete.txt`, txt(leaveText(3000)));
  const { status } = await waitIndexed(ORG, doc.id);
  expect(status.vectors).toBeGreaterThan(0);
  const orgBefore = indexStatus(ORG);
  expect(await removeDoc(thao, loc(folder), doc.id)).toBe(204);
  expect(vectorCount(doc.id), "no vector left right after the 204").toBe(0);
  const orgAfter = indexStatus(ORG);
  expect(orgAfter.vectors).toBe(orgBefore.vectors - status.vectors);
});

test("AC1 TC-1-5: raw search returns the right document first, nearest first, with only ids in the output", async () => {
  const testInfo = test.info();
  const fx = await fixture();
  const leaveQ = indexSearch(ORG, "Đơn xin nghỉ phép năm gửi cho quản lý trước bao nhiêu ngày?");
  expect(leaveQ.run.status, leaveQ.run.stderr).toBe(0);
  expect(leaveQ.nonHitLines, "only hit lines").toEqual([]);
  expect(leaveQ.hits.length).toBeGreaterThan(0);
  expect(leaveQ.hits.length).toBeLessThanOrEqual(5);
  // Earlier tests of the run also uploaded leave texts, so any leave document may rank first; the
  // security document must not.
  expect(leaveQ.hits[0]?.document).not.toBe(fx.other.id);
  expect(leaveQ.hits.map((hit) => hit.document)).not.toContain(fx.other.id);
  expect(leaveQ.hits[0]?.collection).toBe(col);

  const securityQ = indexSearch(
    ORG,
    "Mật khẩu phải có bao nhiêu ký tự và xác thực hai lớp là gì?",
    { k: 5 },
  );
  expect(securityQ.hits[0]?.document).toBe(fx.other.id);

  for (const result of [leaveQ, securityQ]) {
    const distances = result.hits.map((hit) => hit.distance);
    expect(distances, "nearest first").toEqual([...distances].sort((a, b) => a - b));
    const ranks = result.hits.map((hit) => hit.rank);
    expect(ranks, "consecutive ranks").toEqual(ranks.map((_, index) => (ranks[0] ?? 0) + index));
    for (const hit of result.hits) {
      const known = Number(
        sql(
          `select count(*) from chunk_embeddings where chunk_id = '${hit.chunk}' and document_id = '${hit.document}'`,
        ),
      );
      expect(known, `hit chunk ${hit.chunk} belongs to its document`).toBe(1);
    }
  }
  // --k bounds
  expect(indexSearch(ORG, "nghỉ phép", { k: 1 }).hits).toHaveLength(1);
  const wide = indexSearch(ORG, "nghỉ phép", { k: 40 });
  expect(wide.hits.length).toBeGreaterThan(5);
  expect(wide.hits.length).toBeLessThanOrEqual(40);
  // Observation only (not an AC): an accent-free query on the same topic.
  const plain = indexSearch(ORG, "don xin nghi phep nam gui cho quan ly");
  testInfo.annotations.push({
    type: "observation",
    description: `unaccented query top-1 is not the security document: ${plain.hits[0]?.document !== fx.other.id}`,
  });
});

test("AC1 TC-1-6: the same text in NFC and NFD gives the same vectors (distances equal per chunk)", async () => {
  const fx = await fixture();
  const query = "Đơn xin nghỉ phép năm phải được gửi cho quản lý trực tiếp ít nhất ba ngày";
  const { hits } = indexSearch(ORG, query, { k: 40 });
  const byOrdinal = (id: string): Map<number, number> =>
    new Map(hits.filter((hit) => hit.document === id).map((hit) => [hit.ordinal, hit.distance]));
  const nfc = byOrdinal(fx.leave.id);
  const nfd = byOrdinal(fx.leaveNfd.id);
  const shared = [...nfc.keys()].filter((ordinal) => nfd.has(ordinal));
  expect(shared.length, "chunks present in both documents").toBeGreaterThan(0);
  for (const ordinal of shared) {
    expect(
      Math.abs((nfc.get(ordinal) ?? 0) - (nfd.get(ordinal) ?? 0)),
      `chunk ${ordinal}`,
    ).toBeLessThanOrEqual(0.005);
  }
});

// ---------------------------------------------------------------------------------------------
// AC3 Permission metadata
// ---------------------------------------------------------------------------------------------

let restricted: CollectionItem | undefined;
let restrictedFolder: FolderItem | undefined;
let restrictedDoc: DocumentItem | undefined;

test("AC3 TC-3-1: every vector of a restricted collection carries collection id, access level, groups, workspace, folder and document", async () => {
  restricted = await makeCollection(linh, ws, "r", "restricted", ["HR-Team"]);
  restrictedFolder = await makeFolder(linh, ws, restricted.id, "r-folder");
  restrictedDoc = await readyDoc(
    linh,
    loc(restrictedFolder, restricted.id),
    `${MARK}-r-doc.txt`,
    txt(leaveText(4000)),
  );
  const { status } = await waitIndexed(ORG, restrictedDoc.id);
  const vectors = vectorRows({ documentId: restrictedDoc.id });
  expect(vectors).toHaveLength(status.vectors);
  expect(vectors.length).toBeGreaterThan(1);
  for (const row of vectors) {
    expect(row).toMatchObject({
      org_id: ORG,
      collection_id: restricted.id,
      workspace_id: ws,
      folder_id: restrictedFolder.id,
      document_id: restrictedDoc.id,
      access_level: "restricted",
      groups: ["hr-team"],
    });
  }
});

test("AC3 TC-3-2: an access change updates every vector of the collection at once and touches no other vector", async () => {
  expect(restricted && restrictedDoc, "TC-3-1 ran first").toBeTruthy();
  const mine = restricted as CollectionItem;
  const myDoc = restrictedDoc as DocumentItem;
  const otherCol = await makeCollection(linh, ws, "o", "authenticated");
  const otherFolder = await makeFolder(linh, ws, otherCol.id, "o-folder");
  const otherDoc = await readyDoc(
    linh,
    loc(otherFolder, otherCol.id),
    `${MARK}-o-doc.txt`,
    txt(leaveText(3000)),
  );
  await waitIndexed(ORG, otherDoc.id);

  const notMine = `collection_id <> '${mine.id}'`;
  const otherBefore = accessFingerprint(notMine);
  const shBefore = accessFingerprint(`org_id = '${SH_ORG}'`);

  const steps: {
    level: "public" | "authenticated" | "restricted";
    groups: string[];
    expectLevel: string;
    expectGroups: string[];
  }[] = [
    { level: "public", groups: [], expectLevel: "public", expectGroups: [] },
    { level: "authenticated", groups: [], expectLevel: "authenticated", expectGroups: [] },
    {
      level: "restricted",
      groups: ["HR-Team", "FINANCE"],
      expectLevel: "restricted",
      expectGroups: ["finance", "hr-team"],
    },
    {
      level: "restricted",
      groups: ["HR-Team"],
      expectLevel: "restricted",
      expectGroups: ["hr-team"],
    },
  ];
  for (const step of steps) {
    const result = await setAccess(linh, ws, mine.id, step.level, step.groups);
    expect([200, 204], result.text).toContain(result.status);
    // No waiting: "at once" means the vectors are already updated when the answer arrives.
    const vectors = vectorRows({ collectionId: mine.id });
    expect(vectors.length).toBeGreaterThan(0);
    for (const row of vectors) {
      expect(row.access_level, `after ${step.level}`).toBe(step.expectLevel);
      expect([...row.groups].sort(), `groups after ${step.level}`).toEqual(step.expectGroups);
    }
  }
  expect(accessFingerprint(notMine), "vectors of other collections unchanged").toBe(otherBefore);
  expect(accessFingerprint(`org_id = '${SH_ORG}'`), "Sông Hàn vectors unchanged").toBe(shBefore);
  expect(vectorCount(myDoc.id)).toBeGreaterThan(0);
});

test("AC3 TC-3-3: a document uploaded after an access change gets the new level and groups on its vectors", async () => {
  const mine = restricted as CollectionItem;
  const folder = restrictedFolder as FolderItem;
  const change = await setAccess(linh, ws, mine.id, "authenticated", []);
  expect([200, 204], change.text).toContain(change.status);
  const doc = await readyDoc(
    linh,
    loc(folder, mine.id),
    `${MARK}-r-doc2.txt`,
    txt(leaveText(2500)),
  );
  await waitIndexed(ORG, doc.id);
  for (const row of vectorRows({ documentId: doc.id })) {
    expect(row.access_level).toBe("authenticated");
    expect(row.groups).toEqual([]);
  }
  // The earlier document of the collection follows the same level.
  for (const row of vectorRows({ documentId: (restrictedDoc as DocumentItem).id })) {
    expect(row.access_level).toBe("authenticated");
  }
  const back = await setAccess(linh, ws, mine.id, "restricted", ["HR-Team"]);
  expect([200, 204], back.text).toContain(back.status);
  for (const row of vectorRows({ collectionId: mine.id })) {
    expect(row.access_level).toBe("restricted");
    expect(row.groups).toEqual(["hr-team"]);
  }
});

test("AC3 TC-3-4: every vector row in the database has a collection, a valid level and groups that fit the level", async () => {
  await fixture();
  const bad = rows(
    `select id from chunk_embeddings where collection_id is null or workspace_id is null or folder_id is null
        or document_id is null or org_id is null
        or access_level is null or access_level not in ('public', 'authenticated', 'restricted')
        or (access_level = 'restricted' and coalesce(cardinality(groups), 0) = 0)
        or (access_level <> 'restricted' and coalesce(cardinality(groups), 0) > 0)
        or exists (select 1 from unnest(groups) g where g <> lower(g))`,
  );
  expect(bad, "rows violating the metadata rules").toEqual([]);
  // Every vector belongs to a collection that exists.
  const orphans = rows(
    `select e.id from chunk_embeddings e where not exists (select 1 from collections c where c.id = e.collection_id)`,
  );
  expect(orphans).toEqual([]);
});

// ---------------------------------------------------------------------------------------------
// AC4 Isolation
// ---------------------------------------------------------------------------------------------

test("AC4 TC-4-1: the same text indexed in two Organizations: a query in one returns only its own documents, even with --k 40", async () => {
  const fx = await fixture();
  const query =
    "Đơn xin nghỉ phép năm phải được gửi cho quản lý trực tiếp ít nhất ba ngày làm việc";

  const inSh = indexSearch(SH_ORG, query, { k: 40 });
  expect(inSh.run.status, inSh.run.stderr).toBe(0);
  expect(inSh.hits.length).toBeGreaterThan(0);
  expect(inSh.hits.map((hit) => hit.document)).toContain(fx.shLeave.id);
  const mekongDocs = docIdsOfOrg(ORG);
  const mekongCols = collectionIdsOfOrg(ORG);
  for (const hit of inSh.hits) {
    expect(mekongDocs, `Mekong document in a Sông Hàn query: ${hit.line}`).not.toContain(
      hit.document,
    );
    expect(mekongCols, `Mekong collection in a Sông Hàn query: ${hit.line}`).not.toContain(
      hit.collection,
    );
  }
  const shOrgs = orgsOf([...new Set(inSh.hits.map((hit) => hit.document))]);
  for (const org of shOrgs.values()) expect(org).toBe(SH_ORG);
  expect(inSh.run.stdout).not.toContain(fx.leave.id);

  const inMekong = indexSearch(ORG, query, { k: 40 });
  expect(inMekong.hits.map((hit) => hit.document)).toContain(fx.leave.id);
  const shDocs = docIdsOfOrg(SH_ORG);
  for (const hit of inMekong.hits) expect(shDocs, hit.line).not.toContain(hit.document);
  expect(inMekong.run.stdout).not.toContain(fx.shLeave.id);
  expect(inMekong.run.stdout).not.toContain(fx.shCol.id);
});

test("AC4 TC-4-2: another Organization's document id is 'document not found' for reindex and status, changes nothing and looks like an unknown id", async () => {
  const fx = await fixture();
  const mekongPrint = fingerprint(`org_id = '${ORG}'`);
  const shPrint = fingerprint(`org_id = '${SH_ORG}'`);
  const random = "0192a000-0000-7000-8000-0000000fffff";

  for (const [org, foreign] of [
    [SH_ORG, fx.leave.id],
    [ORG, fx.shLeave.id],
  ] as const) {
    for (const action of ["reindex", "status"] as const) {
      const foreignRun = indexCli([action, "--org", org, "--document", foreign]);
      const unknownRun = indexCli([action, "--org", org, "--document", random]);
      expect(foreignRun.status, `${action} foreign id`).toBe(1);
      expect(foreignRun.stderr.trim()).toBe("error: document not found");
      expect(foreignRun.stdout.trim(), "no output on stdout").toBe("");
      expect(unknownRun.status).toBe(foreignRun.status);
      expect(unknownRun.stderr.trim(), "same answer as an unknown id").toBe(
        foreignRun.stderr.trim(),
      );
    }
  }
  expect(fingerprint(`org_id = '${ORG}'`), "Mekong vectors unchanged").toBe(mekongPrint);
  expect(fingerprint(`org_id = '${SH_ORG}'`), "Sông Hàn vectors unchanged").toBe(shPrint);
});

test("AC4 TC-4-3: a query in Sông Hàn for text that exists only in Mekong returns no Mekong id", async () => {
  const fx = await fixture();
  const result = indexSearch(
    SH_ORG,
    "Mật khẩu phải có ít nhất mười hai ký tự, xác thực hai lớp là bắt buộc",
    { k: 40 },
  );
  expect(result.run.status, result.run.stderr).toBe(0);
  const mekongDocs = docIdsOfOrg(ORG);
  const mekongCols = collectionIdsOfOrg(ORG);
  for (const hit of result.hits) {
    expect(hit.document).not.toBe(fx.other.id);
    expect(mekongDocs).not.toContain(hit.document);
    expect(mekongCols).not.toContain(hit.collection);
  }
  const mekongChunks = new Set(
    rows(`select chunk_id from chunk_embeddings where org_id = '${ORG}'`),
  );
  for (const hit of result.hits) expect(mekongChunks.has(hit.chunk), hit.line).toBe(false);
});

test("AC4 TC-4-4: --collection of one Organization used with the other Organization returns no hit; the right pair returns only that collection", async () => {
  const fx = await fixture();
  const wrong = indexSearch(SH_ORG, "nghỉ phép năm", { k: 40, collection: col });
  expect(wrong.hits, "Mekong collection with --org Sông Hàn").toEqual([]);
  expect([0, 1]).toContain(wrong.run.status);
  expect(wrong.run.stdout + wrong.run.stderr).not.toContain(fx.leave.id);

  const wrongTheOtherWay = indexSearch(ORG, "nghỉ phép năm", { k: 40, collection: fx.shCol.id });
  expect(wrongTheOtherWay.hits, "Sông Hàn collection with --org Mekong").toEqual([]);

  const right = indexSearch(SH_ORG, "nghỉ phép năm", { k: 40, collection: fx.shCol.id });
  expect(right.hits.length).toBeGreaterThan(0);
  for (const hit of right.hits) expect(hit.collection).toBe(fx.shCol.id);
});

test("AC4 TC-4-5: every vector row belongs to the same Organization as its document and its collection", async () => {
  await fixture();
  const mismatch = rows(
    `select e.id from chunk_embeddings e join documents d on d.id = e.document_id where e.org_id <> d.org_id
     union all select e.id from chunk_embeddings e join collections c on c.id = e.collection_id where e.org_id <> c.org_id`,
  );
  expect(mismatch).toEqual([]);
});

test("AC4 TC-4-6: npm run seed prints one vector partition line per demo Organization and stays idempotent", async () => {
  const before = counts();
  const run = seed("EA-35 npm run seed");
  expect(run.status, run.stderr).toBe(0);
  const partitionLines = run.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.startsWith("vector partition"));
  expect(partitionLines).toHaveLength(2);
  for (const line of partitionLines) {
    expect(line).toMatch(new RegExp(`^vector partition (created|already present): ${UUID}$`));
    expect(line, "the stack was seeded before").toContain("already present");
  }
  expect(counts(), "seed repeat changes none of the counted tables").toEqual(before);
});

test("AC4 TC-4-7: Organization fields in the query, headers or body of the upload and access routes are ignored", async () => {
  const folder = await makeFolder(linh, ws, col, "ac4-ignore");
  const forged = `?org_id=${SH_ORG}&organization_id=${SH_ORG}&tenant=${SH_ORG}`;
  const shBefore = fingerprint(`org_id = '${SH_ORG}'`);
  const result = await uploadRaw(
    thao,
    loc(folder),
    `${MARK}-ac4-forged.txt`,
    txt(leaveText(2500)),
    {
      query: forged,
      headers: { "x-org-id": SH_ORG, "x-organization-id": SH_ORG },
    },
  );
  expect(result.status, result.text).toBe(201);
  const item = json<DocumentItem>(result);
  trackDoc(item.id, { api: thao, ws, col });
  const done = await waitStatus(thao, ws, col, item.id);
  expect(done.status).toBe("ready");
  await waitIndexed(ORG, item.id);
  const vectors = vectorRows({ documentId: item.id });
  expect(vectors.length).toBeGreaterThan(0);
  for (const row of vectors) expect(row.org_id).toBe(ORG);
  expect(fingerprint(`org_id = '${SH_ORG}'`), "no vector landed in Sông Hàn").toBe(shBefore);

  // Access route: query + headers must be ignored; a forged body field is ignored (200) or refused (422),
  // never honoured.
  const mine = await makeCollection(linh, ws, "ac4-access", "authenticated");
  const query = await linh.send("PUT", `${collectionsPath(ws)}/${mine.id}/access${forged}`, {
    json: { access_level: "public", groups: [] },
    headers: { "x-org-id": SH_ORG },
  });
  expect([200, 204], query.text).toContain(query.status);
  const body = await setAccess(linh, ws, mine.id, "authenticated", [], { org_id: SH_ORG });
  expect([200, 204, 422], body.text).toContain(body.status);
  expect(fingerprint(`org_id = '${SH_ORG}'`), "Sông Hàn vectors unchanged").toBe(shBefore);
  for (const row of vectorRows({ collectionId: mine.id })) expect(row.org_id).toBe(ORG);
});

test("AC4 TC-4-8: the embedding service publishes no port and carries no credentials", async () => {
  const config = composeConfig();
  const service = (config.services as Record<string, Record<string, unknown>>).embedding;
  expect(service, "service embedding in compose.yaml").toBeTruthy();
  const ports = service?.ports as unknown[] | undefined;
  expect(ports ?? [], "no published port").toEqual([]);
  const environment = (service?.environment ?? {}) as Record<string, unknown> | string[];
  const keys = Array.isArray(environment)
    ? environment.map((entry) => entry.split("=")[0] ?? "")
    : Object.keys(environment);
  const secretish = keys.filter((key) =>
    /(PASSWORD|SECRET|TOKEN|API_?KEY|CREDENTIAL|DATABASE_URL|DSN|PRIVATE)/i.test(key),
  );
  expect(secretish, "credential-like environment keys").toEqual([]);
  expect(service?.secrets, "no secrets mounted").toBeUndefined();
  expect(service?.env_file, "no env_file").toBeUndefined();
  const example = path.join(ROOT, ".env.example");
  if (fs.existsSync(example)) {
    const leaked = fs
      .readFileSync(example, "utf8")
      .split(/\r?\n/)
      .filter(
        (line) =>
          /embedding/i.test(line) && /(PASSWORD|SECRET|TOKEN|KEY)[A-Z_]*\s*=\s*\S+/i.test(line),
      );
    expect(leaked, ".env.example credential lines for the embedding service").toEqual([]);
  }
});

/** `docker compose config --format json`: the resolved Compose file, no text parsing needed. */
function composeConfig(): { services: unknown } {
  const run = compose(["--profile", "model", "config", "--format", "json"]);
  expect(run.status, run.stderr).toBe(0);
  return JSON.parse(run.stdout) as { services: unknown };
}

// ---------------------------------------------------------------------------------------------
// AC6 Embedding version and reindex
// ---------------------------------------------------------------------------------------------

test("AC6 TC-6-1: every vector stores the model name and version bge-m3 / 2026.10", async () => {
  const fx = await fixture();
  for (const [org, id] of [
    [ORG, fx.leave.id],
    [ORG, fx.other.id],
    [SH_ORG, fx.shLeave.id],
  ] as const) {
    const distinct = rows(
      `select distinct model_id || '|' || model_version from chunk_embeddings where document_id = '${id}'`,
    );
    expect(distinct, `model of ${id}`).toEqual([`${MODEL_ID}|${MODEL_VERSION}`]);
    expect(indexStatus(org, id).model).toBe(MODEL_REF);
  }
});

test("AC6 TC-6-2: index reindex --org re-embeds every Ready document of the Organization (new vector ids), same counts, other Organization untouched", async () => {
  const fx = await fixture();
  const mine = [fx.leave.id, fx.leaveNfd.id, fx.other.id];
  const statusBefore = indexStatus(ORG);
  expect(statusBefore.indexed).toBeGreaterThanOrEqual(2);
  const perDocBefore = new Map(mine.map((id) => [id, vectorIds(`document_id = '${id}'`)]));
  const shBefore = fingerprint(`org_id = '${SH_ORG}'`);
  const startedAt = sql("select clock_timestamp()");

  const result = reindex(ORG);
  expect(result.run.status, result.run.stderr).toBe(0);
  expect(result.other, "no unexpected output lines").toEqual([]);
  expect(result.failed).toEqual([]);
  expect(result.indexed.length, "one indexed: line per Ready document").toBe(
    statusBefore.ready_documents,
  );
  expect(result.done).toEqual({
    documents: statusBefore.ready_documents,
    vectors: result.indexed.reduce((sum, entry) => sum + entry.vectors, 0),
    failed: 0,
    model: MODEL_REF,
  });
  const indexedIds = result.indexed.map((entry) => entry.id);
  for (const id of mine) expect(indexedIds, "own document reindexed").toContain(id);

  for (const id of mine) {
    const after = vectorIds(`document_id = '${id}'`);
    const before = perDocBefore.get(id) ?? [];
    expect(after.length, "same vector count").toBe(before.length);
    expect(
      after.filter((vid) => before.includes(vid)),
      "new vector ids",
    ).toEqual([]);
    expect(
      Number(
        sql(
          `select count(*) from chunk_embeddings where document_id = '${id}' and created_at <= '${startedAt}'`,
        ),
      ),
      "new created_at",
    ).toBe(0);
    expect(result.indexed.find((entry) => entry.id === id)?.vectors).toBe(after.length);
  }
  expect(fingerprint(`org_id = '${SH_ORG}'`), "Sông Hàn vectors unchanged").toBe(shBefore);
  const statusAfter = indexStatus(ORG);
  expect(statusAfter).toMatchObject({
    ready_documents: statusBefore.ready_documents,
    indexed: statusBefore.ready_documents,
    not_indexed: 0,
    stale: 0,
    model: MODEL_REF,
  });
  expect(statusAfter.vectors).toBe(statusBefore.vectors);
});

test("AC6 TC-6-3: reindex of one document replaces its vectors without duplicates", async () => {
  const fx = await fixture();
  const chunks = await chunksOf(thao, ws, col, fx.leave.id);
  const before = vectorIds(`document_id = '${fx.leave.id}'`);
  const result = reindex(ORG, fx.leave.id);
  expect(result.run.status, result.run.stderr).toBe(0);
  expect(result.indexed).toEqual([{ id: fx.leave.id, vectors: chunks.length }]);
  expect(result.done).toEqual({
    documents: 1,
    vectors: chunks.length,
    failed: 0,
    model: MODEL_REF,
  });
  const after = vectorIds(`document_id = '${fx.leave.id}'`);
  expect(after).toHaveLength(chunks.length);
  expect(after.filter((id) => before.includes(id))).toEqual([]);
  // Twice in a row stays at one vector per chunk.
  expect(reindex(ORG, fx.leave.id).run.status).toBe(0);
  expect(vectorCount(fx.leave.id)).toBe(chunks.length);
});

test("AC6 TC-6-4: a configured model that is not a local embedding model of the manifest is refused and changes no vector", async () => {
  await fixture();
  const before = fingerprint(`org_id = '${ORG}'`);
  for (const ref of ["qwen3-4b-instruct-2507@2026.10", "no-such-model@1"]) {
    const run = indexCli(["reindex", "--org", ORG], { EMBEDDING_MODEL_REF: ref });
    expect(run.status, `${ref}: ${run.stdout}`).toBe(1);
    expect(run.stderr).toContain(
      "configuration error: EMBEDDING_MODEL_REF must name a local embedding model of the platform manifest",
    );
    expect(run.stdout, "no indexed:/done: lines").not.toMatch(/^(indexed|done):/m);
  }
  expect(fingerprint(`org_id = '${ORG}'`), "no vector changed").toBe(before);
  // The pinned model given explicitly works as the default does.
  const ok = indexCli(["status", "--org", ORG], { EMBEDDING_MODEL_REF: MODEL_REF });
  expect(ok.status, ok.stderr).toBe(0);
  expect(ok.stdout).toContain(`model=${MODEL_REF}`);
});

test("AC6 TC-6-5: vectors of another model are reported stale and a reindex brings them to the current model", async () => {
  const folder = await makeFolder(linh, ws, col, "ac6-stale");
  const a = await readyDoc(thao, loc(folder), `${MARK}-ac6-a.txt`, txt(leaveText(2500)));
  const b = await readyDoc(thao, loc(folder), `${MARK}-ac6-b.txt`, txt(securityText(2500)));
  await waitIndexed(ORG, a.id);
  await waitIndexed(ORG, b.id);
  const before = indexStatus(ORG);

  sql(`update chunk_embeddings set model_version = '2026.07' where document_id = '${a.id}'`);
  sql(`update chunk_embeddings set model_id = 'qa-old-model' where document_id = '${b.id}'`);
  for (const id of [a.id, b.id]) {
    const status = indexStatus(ORG, id);
    expect(status, `stale document ${id}`).toMatchObject({ indexed: 0, stale: 1 });
  }
  const during = indexStatus(ORG);
  expect(during.stale).toBe(before.stale + 2);
  expect(during.indexed).toBe(before.indexed - 2);

  for (const id of [a.id, b.id]) {
    const result = reindex(ORG, id);
    expect(result.run.status, result.run.stderr).toBe(0);
    expect(result.indexed).toHaveLength(1);
    expect(indexStatus(ORG, id)).toMatchObject({ indexed: 1, stale: 0, model: MODEL_REF });
    const models = rows(
      `select distinct model_id || '|' || model_version from chunk_embeddings where document_id = '${id}'`,
    );
    expect(models).toEqual([`${MODEL_ID}|${MODEL_VERSION}`]);
  }
  expect(indexStatus(ORG).stale).toBe(before.stale);
});

test("AC6 TC-6-6: bad arguments exit 2 with the documented message; unknown Organization exits 1", async () => {
  const unknownOrg = "0192a000-0000-7000-8000-0000000eeeee";
  const orgMsg = "error: --org must be an Organization id (UUID)";
  const docMsg = "error: --document must be a document id (UUID)";
  const kMsg = "error: --k must be an integer from 1 to 40";
  const cases: { args: string[]; status: number; stderr: string }[] = [
    { args: ["reindex", "--org", "not-a-uuid"], status: 2, stderr: orgMsg },
    { args: ["status", "--org", "123"], status: 2, stderr: orgMsg },
    { args: ["search", "--org", "", "--query", "x"], status: 2, stderr: orgMsg },
    { args: ["reindex", "--org", ORG, "--document", "nope"], status: 2, stderr: docMsg },
    { args: ["status", "--org", ORG, "--document", "1234"], status: 2, stderr: docMsg },
    ...["0", "41", "abc", "-1", "2.5", ""].map((k) => ({
      args: ["search", "--org", ORG, "--query", "x", "--k", k],
      status: 2,
      stderr: kMsg,
    })),
    { args: ["reindex", "--org", unknownOrg], status: 1, stderr: "error: Organization not found" },
    { args: ["status", "--org", unknownOrg], status: 1, stderr: "error: Organization not found" },
    {
      args: ["search", "--org", unknownOrg, "--query", "x"],
      status: 1,
      stderr: "error: Organization not found",
    },
  ];
  for (const entry of cases) {
    const run = indexCli(entry.args);
    expect(run.status, `index ${entry.args.join(" ")} -> ${run.stderr}`).toBe(entry.status);
    expect(run.stderr, `index ${entry.args.join(" ")}`).toContain(entry.stderr);
    expect(run.stdout.split(/\r?\n/).filter(isHitLine), "no hit lines on error").toEqual([]);
  }
  const noOrg = indexCli(["status"]);
  expect(noOrg.status, "missing --org").toBe(2);
  expect(noOrg.stderr.trim().length).toBeGreaterThan(0);
  const noAction = indexCli([]);
  expect(noAction.status, "missing action").toBe(2);
});
