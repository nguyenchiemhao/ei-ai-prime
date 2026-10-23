// EA-35 (KB-04): slow and disruptive cases of the vector index (tagged @slow). Black-box, from
// .work/EA-35/contract.md only. Run with the full tier:
//   npm run e2e:full -- e2e/knowledge/EA-35-vector-index-slow.spec.ts
// Covers: access change while a large document is being indexed (Attack list), a sentinel string that must
// never reach the API logs or the CLI output (Attack list), and the embedding service being stopped
// (contract "Also check"). The last test stops `embedding` and always starts it again and waits for healthy.
// Data hygiene as in EA-35-vector-index.spec.ts: marker qa-EA35-<run>, own folders/collections, row counts
// equal before and after.
import { expect, test } from "@playwright/test";
import { compose, sleep } from "../support/ea22";
import type { Loc } from "../support/ea33";
import {
  DEMO_ORG as ORG,
  MARK,
  MODEL_REF,
  RUN,
  cleanupAll,
  counts,
  fingerprint,
  getDoc,
  indexSearch,
  indexStatus,
  isHitLine,
  leaveText,
  accessOf,
  makeCollection,
  makeFolder,
  markerRows,
  readyDoc,
  reindex,
  removeDoc,
  setAccess,
  setAccessDirect,
  setupContext,
  txt,
  uploadDoc,
  vectorCount,
  vectorRows,
  waitEmbeddingHealthy,
  waitIndexed,
  type Context,
  type Counts,
} from "../support/ea35";
import { waitStatus } from "../support/ea33";
import type { FolderItem } from "../support/ea32";

test.describe.configure({ mode: "serial", timeout: 600_000 });

let ctx: Context;
let baseline: Counts | undefined;

function loc(folder: FolderItem, collection = ctx.col): Loc {
  return { ws: ctx.ws, col: collection, folder: folder.id };
}

test.beforeAll(async () => {
  await cleanupAll();
  baseline = counts();
  ctx = await setupContext();
});

test.afterAll(async () => {
  // Never leave the shared stack without its embedding service.
  if (!/\(healthy\)/.test(compose(["ps", "embedding"]).stdout)) {
    compose(["start", "embedding"]);
    await waitEmbeddingHealthy().catch(() => undefined);
  }
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the EA-35 marker left behind").toEqual([]);
});

/** Every vector of the collection must carry the access the collection reports now. */
async function expectVectorsFollowCollection(
  collectionId: string,
  expectedCount: number,
): Promise<void> {
  const expected = await accessOf(ctx.linh, ctx.ws, collectionId);
  const vectors = vectorRows({ collectionId });
  expect(vectors).toHaveLength(expectedCount);
  for (const row of vectors) {
    expect(row.access_level, "level of the collection").toBe(expected.access_level);
    expect([...row.groups].sort(), "groups of the collection").toEqual(
      expected.groups.map((group) => group.toLowerCase()).sort(),
    );
  }
}

test(
  "AC3 TC-3-5: access changes through the admin origin while a large document is being indexed are answered (no gateway timeout) and leave no vector with the old level or groups",
  { tag: "@slow" },
  async () => {
    const mine = await makeCollection(ctx.linh, ctx.ws, "race", "public");
    const folder = await makeFolder(ctx.linh, ctx.ws, mine.id, "race-folder");
    const doc = await readyDoc(
      ctx.linh,
      loc(folder, mine.id),
      `${MARK}-race.txt`,
      txt(leaveText(150_000)),
    );

    // The document is Ready, indexing is running: change the access three times in a row.
    const answers: string[] = [];
    for (const [level, groups] of [
      ["restricted", ["Race-One"]],
      ["public", []],
      ["restricted", ["Final-Group"]],
    ] as const) {
      const started = Date.now();
      const result = await setAccess(ctx.linh, ctx.ws, mine.id, level, [...groups]);
      answers.push(`${result.status} in ${Date.now() - started} ms`);
    }
    test
      .info()
      .annotations.push({ type: "observation", description: `PUT answers: ${answers.join("; ")}` });
    const { status } = await waitIndexed(ORG, doc.id, 480_000);
    expect(status.vectors).toBeGreaterThan(20);
    await sleep(3000);
    await expectVectorsFollowCollection(mine.id, status.vectors);
    const settled = fingerprint(`collection_id = '${mine.id}'`);
    await sleep(8000);
    await expectVectorsFollowCollection(mine.id, status.vectors);
    expect(fingerprint(`collection_id = '${mine.id}'`), "nothing rewrites the vectors later").toBe(
      settled,
    );
    // Last, so that the consistency checks above still report: every change was answered as success.
    expect(
      answers.every((answer) => /^(200|204) /.test(answer)),
      answers.join("; "),
    ).toBe(true);
  },
);

test(
  "AC3 TC-3-6: concurrent access changes straight at the API while a large document is being indexed end consistent with the collection",
  { tag: "@slow" },
  async () => {
    const mine = await makeCollection(ctx.linh, ctx.ws, "race2", "public");
    const folder = await makeFolder(ctx.linh, ctx.ws, mine.id, "race2-folder");
    const doc = await readyDoc(
      ctx.linh,
      loc(folder, mine.id),
      `${MARK}-race2.txt`,
      txt(leaveText(120_000)),
    );
    const changes = [
      setAccessDirect(ctx.linh, ctx.ws, mine.id, "restricted", ["Race-One"]),
      sleep(1500).then(() => setAccessDirect(ctx.linh, ctx.ws, mine.id, "public", [])),
      sleep(3000).then(() =>
        setAccessDirect(ctx.linh, ctx.ws, mine.id, "restricted", ["Final-Group"]),
      ),
    ];
    const results = await Promise.all(changes);
    test.info().annotations.push({
      type: "observation",
      description: `direct PUT answers: ${results.map((entry) => `${entry.status} in ${entry.ms} ms`).join("; ")}`,
    });
    for (const entry of results) expect([200, 204], entry.text).toContain(entry.status);
    const { status } = await waitIndexed(ORG, doc.id, 480_000);
    await sleep(3000);
    await expectVectorsFollowCollection(mine.id, status.vectors);
  },
);

test(
  "AC4 TC-4-9: a sentinel string in a document never appears in the CLI output or in the API logs",
  { tag: "@slow" },
  async () => {
    const sentinel = `zqsentinel${RUN.replace(/[^a-z0-9]/gi, "")}`;
    const phrase = "kiểm định lô hàng đặc biệt xyz";
    const folder = await makeFolder(ctx.linh, ctx.ws, ctx.col, "sentinel");
    const body = `${leaveText(2500)}\n\nMã nội bộ ${sentinel}: ${phrase}.`;
    const doc = await readyDoc(ctx.thao, loc(folder), `${MARK}-sentinel.txt`, txt(body));
    await waitIndexed(ORG, doc.id);

    const search = indexSearch(ORG, sentinel, { k: 5 });
    const again = reindex(ORG, doc.id);
    const status = indexCliText();
    expect(search.run.status, search.run.stderr).toBe(0);
    expect(again.run.status, again.run.stderr).toBe(0);
    for (const line of search.run.stdout.split(/\r?\n/).filter((entry) => entry.trim() !== "")) {
      expect(isHitLine(line), `only ids and numbers: ${line}`).toBe(true);
    }
    for (const text of [
      search.run.stdout,
      search.run.stderr,
      again.run.stdout,
      again.run.stderr,
      status,
    ]) {
      expect(text).not.toContain(sentinel);
      expect(text).not.toContain(phrase);
    }
    const apiLogs = compose(["logs", "--no-color", "api"]).stdout;
    expect(apiLogs, "API logs").not.toContain(sentinel);
    expect(apiLogs, "API logs").not.toContain(phrase);
    expect(apiLogs, "API logs").not.toContain("Đơn xin nghỉ phép năm");
    // Not part of the contract: note whether the embedding service logs request text.
    const embeddingLogs = compose(["logs", "--no-color", "embedding"]).stdout;
    test.info().annotations.push({
      type: "observation",
      description: `embedding service logs contain the sentinel: ${embeddingLogs.includes(sentinel)}`,
    });
  },
);

function indexCliText(): string {
  const run = compose(["exec", "-T", "api", "ei-ai", "index", "status", "--org", ORG]);
  return run.stdout + run.stderr;
}

test(
  "AC1 TC-1-8: with the embedding service stopped an upload still becomes Ready (not indexed), the CLI reports model errors, and a reindex after the restart indexes it",
  { tag: "@slow" },
  async () => {
    const folder = await makeFolder(ctx.linh, ctx.ws, ctx.col, "embed-down");
    const indexed = await readyDoc(
      ctx.thao,
      loc(folder),
      `${MARK}-embed-a.txt`,
      txt(leaveText(2500)),
    );
    await waitIndexed(ORG, indexed.id);
    const vectorsOfA = vectorCount(indexed.id);
    expect(vectorsOfA).toBeGreaterThan(0);

    let stopped = false;
    let late: { id: string } | undefined;
    try {
      expect(compose(["stop", "embedding"]).status).toBe(0);
      stopped = true;
      const queued = await uploadDoc(
        ctx.thao,
        loc(folder),
        `${MARK}-embed-b.txt`,
        txt(leaveText(2500, "b")),
      );
      late = queued;
      const ready = await waitStatus(ctx.thao, ctx.ws, ctx.col, queued.id);
      expect(ready.status, "the document becomes Ready without the embedding service").toBe(
        "ready",
      );
      await sleep(10_000);
      expect((await getDoc(ctx.thao, ctx.ws, ctx.col, queued.id))?.status).toBe("ready");
      expect(indexStatus(ORG, queued.id)).toMatchObject({
        indexed: 0,
        not_indexed: 1,
        vectors: 0,
      });
      expect(vectorCount(queued.id)).toBe(0);

      // Commands that need the model fail with a documented error and exit code 1; no stack trace.
      const failed = reindex(ORG, queued.id);
      expect(failed.run.status, `${failed.run.stdout} ${failed.run.stderr}`).toBe(1);
      expect(failed.run.stdout + failed.run.stderr).toMatch(
        /^(failed: \S+ \(.+\)|error: \S+: .+)$/m,
      );
      expect(failed.run.stdout + failed.run.stderr).not.toContain("Traceback");
      expect(vectorCount(queued.id), "a failed reindex leaves nothing half written").toBe(0);

      const search = indexSearch(ORG, "nghỉ phép năm");
      expect(search.run.status, search.run.stdout).toBe(1);
      expect(search.hits).toEqual([]);
      expect(search.run.stderr).toMatch(/^error: \S+: .+/m);
      expect(search.run.stderr).not.toContain("Traceback");

      // Observation (the contract is silent): does a failed reindex keep the old vectors of an indexed document?
      const failedA = reindex(ORG, indexed.id);
      expect(failedA.run.status).toBe(1);
      test.info().annotations.push({
        type: "observation",
        description: `vectors of an indexed document after a failed reindex: ${vectorCount(indexed.id)} (before: ${vectorsOfA})`,
      });
    } finally {
      if (stopped) {
        compose(["start", "embedding"]);
        await waitEmbeddingHealthy();
      }
    }

    expect(late, "the second document was uploaded").toBeTruthy();
    const id = (late as { id: string }).id;
    const result = reindex(ORG, id);
    expect(result.run.status, `${result.run.stdout} ${result.run.stderr}`).toBe(0);
    expect(result.indexed.map((entry) => entry.id)).toEqual([id]);
    const { status } = await waitIndexed(ORG, id, 60_000);
    expect(status).toMatchObject({ indexed: 1, not_indexed: 0, model: MODEL_REF });
    expect((await getDoc(ctx.thao, ctx.ws, ctx.col, id))?.status).toBe("ready");
    expect(await removeDoc(ctx.thao, loc(folder), id)).toBe(204);
    expect(vectorCount(id)).toBe(0);
  },
);
