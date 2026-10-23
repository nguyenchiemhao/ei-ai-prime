// EA-35 (KB-04): AC1 time limit (tagged @perf): a 50-page text PDF has its vectors within 120 s of Ready.
// Black-box, from .work/EA-35/contract.md only. Run with:
//   npm run e2e:perf -- e2e/knowledge/EA-35-vector-index-perf.spec.ts
// Data hygiene as in EA-35-vector-index.spec.ts: marker qa-EA35-<run>, own folder, row counts equal before
// and after.
import { expect, test } from "@playwright/test";
import { buildPdf, chunksOf, filler, waitStatus } from "../support/ea33";
import {
  DEMO_ORG as ORG,
  INDEX_DEADLINE_MS,
  MARK,
  MODEL_REF,
  cleanupAll,
  counts,
  getDoc,
  makeFolder,
  markerRows,
  readyCountOf,
  setupContext,
  uploadDoc,
  vectorCount,
  waitIndexed,
  type Context,
  type Counts,
} from "../support/ea35";

test.describe.configure({ mode: "serial", timeout: 600_000 });

let ctx: Context;
let baseline: Counts | undefined;

test.beforeAll(async () => {
  await cleanupAll();
  baseline = counts();
  ctx = await setupContext();
});

test.afterAll(async () => {
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the EA-35 marker left behind").toEqual([]);
});

test(
  "AC1 TC-1-7: a 50-page text PDF is indexed within 120 s of Ready and stays Ready",
  { tag: "@perf" },
  async () => {
    const readyBefore = await readyCountOf(ctx.linh, ctx.ws, ctx.col);
    const folder = await makeFolder(ctx.linh, ctx.ws, ctx.col, "perf50");
    const pages = Array.from({ length: 50 }, (_, index) => filler(`zqpg${index + 1}`, 2500));
    const queued = await uploadDoc(
      ctx.thao,
      { ws: ctx.ws, col: ctx.col, folder: folder.id },
      `${MARK}-perf50.pdf`,
      buildPdf(pages),
    );
    const ready = await waitStatus(
      ctx.thao,
      ctx.ws,
      ctx.col,
      queued.id,
      ["ready", "failed"],
      300_000,
    );
    expect(ready.status).toBe("ready");

    const { status, elapsedMs } = await waitIndexed(ORG, ready.id, INDEX_DEADLINE_MS, async () => {
      expect((await getDoc(ctx.thao, ctx.ws, ctx.col, ready.id))?.status, "stays ready").toBe(
        "ready",
      );
    });
    const chunks = await chunksOf(ctx.thao, ctx.ws, ctx.col, ready.id);
    test.info().annotations.push({
      type: "timing",
      description: `Ready to indexed: ${(elapsedMs / 1000).toFixed(1)} s for ${chunks.length} chunks`,
    });
    expect(elapsedMs, "indexed within 120 s of Ready").toBeLessThanOrEqual(INDEX_DEADLINE_MS);
    expect(chunks.length).toBeGreaterThan(50);
    expect(status).toMatchObject({ indexed: 1, not_indexed: 0, stale: 0, model: MODEL_REF });
    expect(status.vectors).toBe(chunks.length);
    expect(vectorCount(ready.id)).toBe(chunks.length);
    expect(await readyCountOf(ctx.linh, ctx.ws, ctx.col), "collection counts it as ready").toBe(
      readyBefore + 1,
    );
  },
);
