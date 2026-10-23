// EA-33 (KB-02) NFR: a 50-page text PDF is processed in 2 minutes or less on the dev machine
// (excluding embedding). Measured from the 201 of the upload to status `ready`.
// Black-box, own folder, all data removed afterwards.
// Run: npm run e2e:perf -- e2e/knowledge/EA-33-upload-process-documents-perf.spec.ts
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { peopleOpsId, sleep, type ApiSession } from "../support/ea22";
import { collectionsPath, json, type CollectionItem } from "../support/ea32";
import {
  MARK,
  SCREENSHOTS_33,
  apiOf,
  buildPdf,
  chunksOf,
  cleanupAll,
  counts,
  expectChunkInvariants,
  filler,
  getDoc,
  makeFolder,
  markerRows,
  textOf,
  uploadRaw,
  type Counts,
  type DocumentItem,
} from "../support/ea33";

test.describe.configure({ mode: "serial", timeout: 300_000 });

const LIMIT_MS = 120_000;
let ws = "";
let col = "";
let baseline: Counts | undefined;
let linh: ApiSession;
let thao: ApiSession;

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
  "NFR: a 50-page text PDF is Ready within 120 s of the upload and its chunks cover every page",
  { tag: "@perf" },
  async () => {
    const folder = await makeFolder(linh, ws, col, "perf50");
    const pages = Array.from({ length: 50 }, (_, index) => filler(`zqpg${index + 1}`, 2500));
    const bytes = buildPdf(pages);
    const at = { ws, col, folder: folder.id };
    const accepted = await uploadRaw(thao, at, `${MARK}-fifty-pages.pdf`, bytes);
    expect(accepted.status, accepted.text).toBe(201);
    const item = json<DocumentItem>(accepted);
    const started = Date.now();
    let status = item.status;
    while (status !== "ready" && status !== "failed" && status !== "not_supported") {
      if (Date.now() - started > LIMIT_MS + 30_000) break;
      await sleep(500);
      status = (await getDoc(thao, ws, col, item.id))?.status ?? status;
    }
    const elapsed = Date.now() - started;
    test.info().annotations.push({ type: "processing-ms", description: String(elapsed) });
    expect(status).toBe("ready");
    expect(elapsed, `processing took ${elapsed} ms`).toBeLessThanOrEqual(LIMIT_MS);
    const done = await getDoc(thao, ws, col, item.id);
    expect(done?.page_count).toBe(50);
    const chunks = await chunksOf(thao, ws, col, item.id);
    expectChunkInvariants(chunks, (await textOf(thao, ws, col, item.id)).text);
    expect(new Set(chunks.map((chunk) => chunk.page)).size).toBe(50);
  },
);
