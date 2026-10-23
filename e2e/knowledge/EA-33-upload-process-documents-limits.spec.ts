// EA-33 (KB-02) AC3 and the storage limits (slow tier): files above 50 MB are rejected with the limit,
// a file of exactly 50 MB is accepted, and the Organization storage quota (1 GB of originals).
// Black-box specs from .work/EA-33/contract.md only. Run with the full tier:
//   npm run e2e:full -- e2e/knowledge/EA-33-upload-process-documents-limits.spec.ts
// The quota test uploads about 1 GB and is opt-in: set EA33_QUOTA=1 to run it.
// Everything carries the marker `qa-EA33-<run>` and is removed in afterAll (row counts proven equal).
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { DEMO_ORG, peopleOpsId, sleep, type ApiSession } from "../support/ea22";
import { withSession } from "../support/ea23";
import { collectionsPath, json, type CollectionItem } from "../support/ea32";
import {
  LIMIT_BYTES,
  MARK,
  MSG,
  SCREENSHOTS_33,
  apiOf,
  chooseFiles,
  chunkRows,
  cleanupAll,
  counts,
  deleteDoc,
  docRow,
  exactText,
  expectStatusText,
  filler,
  listDocs,
  makeFolder,
  markerRows,
  openCollectionPage,
  rawUpload,
  ready,
  rejectionLines,
  selectFolder,
  tempFile,
  tempFileOfSize,
  uploadRaw,
  uploadRequests,
  fileIdOf,
  waitStoredGone,
  type Counts,
  type DocumentItem,
  type FolderItem33,
  type Loc,
} from "../support/ea33";

test.describe.configure({ mode: "serial", timeout: 600_000 });

let ws = "";
let col = "";
let baseline: Counts | undefined;
let linh: ApiSession;
let thao: ApiSession;

function loc(folder: FolderItem33): Loc {
  return { ws, col, folder: folder.id };
}

test.beforeAll(async () => {
  await cleanupAll();
  fs.mkdirSync(SCREENSHOTS_33, { recursive: true });
  baseline = counts();
  ws = peopleOpsId();
  linh = await apiOf("linh");
  thao = await apiOf("thao");
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

test(
  "AC3: the UI rejects a 52 428 801-byte file with the 50 MB limit before any request; a small valid file of the same drop is uploaded",
  { tag: "@slow" },
  async ({ browser }) => {
    const folder = await makeFolder(linh, ws, col, "ac3-ui");
    const big = `${MARK}-big.pdf`;
    const small = `${MARK}-ac3-small.txt`;
    const paths = [tempFileOfSize(big, LIMIT_BYTES + 1), tempFile(small, filler("zqac3", 300))];
    await withSession(browser, thao, async (page) => {
      await openCollectionPage(page, ws, col);
      await selectFolder(page, folder.name);
      const requests = uploadRequests(page);
      await chooseFiles(page, paths);
      await expect(page.getByTestId("upload-rejection")).toHaveCount(1);
      expect(await rejectionLines(page)).toEqual([MSG.tooLarge(big)]);
      await expectStatusText(docRow(page, small), ready(1));
      await expect(docRow(page, big)).toHaveCount(0);
      expect(requests.map((request) => request.name)).toEqual([small]);
      await page.screenshot({ path: `${SCREENSHOTS_33}/ac3-too-large.png`, fullPage: true });
    });
    expect((await listDocs(thao, ws, col, folder.id)).map((item) => item.name)).toEqual([small]);
  },
);

test(
  "AC3 TC-3-2: the API answers 413 file_too_large for 52 428 801 bytes (no row) and accepts exactly 52 428 800 bytes; removing it while it processes leaves no document, chunk or original",
  { tag: "@slow" },
  async () => {
    const folder = await makeFolder(linh, ws, col, "ac3-api");
    const over = await uploadRaw(
      thao,
      loc(folder),
      `${MARK}-over.txt`,
      Buffer.from(exactText(LIMIT_BYTES + 1)),
    );
    expect(over.status, over.text).toBe(413);
    expect(over.json).toEqual({ detail: "file_too_large" });
    expect(await listDocs(thao, ws, col, folder.id), "no row for the rejected file").toEqual([]);

    const exact = Buffer.from(exactText(LIMIT_BYTES));
    expect(exact.length).toBe(LIMIT_BYTES);
    const accepted = await uploadRaw(thao, loc(folder), `${MARK}-exactly-50mb.txt`, exact);
    expect(accepted.status, accepted.text).toBe(201);
    const item = json<DocumentItem>(accepted);
    expect(item.size_bytes).toBe(LIMIT_BYTES);
    expect(item.status).toBe("queued");

    fileIdOf(item.id); // remember before the row is gone
    // Removed in whatever status it is (queued or processing): allowed in any status.
    const removed = await deleteDoc(thao, ws, col, item.id);
    expect(removed.status, removed.text).toBe(204);
    await sleep(10_000); // a worker that was still running must not bring rows back
    expect(await listDocs(thao, ws, col, folder.id)).toEqual([]);
    expect(chunkRows(item.id), "no chunks after the removal").toBe(0);
    expect(await waitStoredGone(DEMO_ORG, item.id, 60_000), "the original is deleted").toBe(true);
  },
);

test(
  "AC3 TC-3-3: a Content-Length of exactly the limit is not refused up front (the check is on the real size)",
  { tag: "@slow" },
  async () => {
    const folder = await makeFolder(linh, ws, col, "ac3-header");
    const answer = await rawUpload({
      loc: loc(folder),
      api: thao,
      name: `${MARK}-short-body.txt`,
      contentLength: LIMIT_BYTES,
      body: Buffer.from("only a few bytes while 50 MB were announced"),
    });
    // The server waits for the rest of the body (status 0: no answer yet): no 413 and no row.
    expect(answer.status, answer.text).not.toBe(413);
    expect(await listDocs(thao, ws, col, folder.id)).toEqual([]);
  },
);

test(
  "AC3 TC-3-4: when the Organization's originals would exceed 1 GB the API answers 413 storage_quota_exceeded and the UI shows the storage-full message",
  { tag: "@slow" },
  async ({ browser }) => {
    test.skip(!process.env.EA33_QUOTA, "set EA33_QUOTA=1 to upload about 1 GB");
    test.setTimeout(900_000);
    const folder = await makeFolder(linh, ws, col, "ac3-quota");
    const zeros = Buffer.alloc(LIMIT_BYTES, 0); // NUL bytes: the files fail fast, the originals stay
    let refused: string | null = null;
    for (let index = 0; index < 25 && refused === null; index++) {
      const result = await uploadRaw(thao, loc(folder), `${MARK}-quota-${index}.txt`, zeros);
      if (result.status === 201) continue;
      expect(result.status, result.text).toBe(413);
      refused = (result.json as { detail: string }).detail;
    }
    expect(refused).toBe("storage_quota_exceeded");
    // Fill the rest with 5 MB files, so that a 6 MB file from the UI cannot fit either.
    const small = Buffer.alloc(5 * 1024 * 1024, 0);
    for (let index = 0; index < 12; index++) {
      const result = await uploadRaw(thao, loc(folder), `${MARK}-quota-small-${index}.txt`, small);
      if (result.status !== 201) break;
    }
    await withSession(browser, thao, async (page) => {
      await openCollectionPage(page, ws, col);
      await selectFolder(page, folder.name);
      const name = `${MARK}-quota-ui.txt`;
      await chooseFiles(page, [tempFile(name, exactText(6 * 1024 * 1024))]);
      await expect(page.getByTestId("upload-rejection")).toHaveCount(1);
      expect(await rejectionLines(page)).toEqual([MSG.storageFull(name)]);
    });
  },
);
