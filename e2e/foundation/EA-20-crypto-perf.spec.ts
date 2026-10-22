// EA-20 (FND-03) NFR1: encrypt / decrypt a 50 MB file in less than 1.5 s on the dev machine.
// Profile api, no browser. Needs the stack up and migrated (the benchmark runs in the backend-tools image):
//   npm run up && npm run migrate && npm run e2e:perf -- e2e/foundation/EA-20-crypto-perf*
// Black-box: only the benchmark command of the contract (`npm run backend -- bench-crypto`) and its output.
import { spawnSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { ROOT, sql } from "../support/ea22";

const LIMIT_MS = 1500;

// Contract: stdout contains exactly one line `file crypto 50 MiB: put_median_ms=<n.n> get_median_ms=<n.n> runs=5`.
const BENCH_LINE =
  /^file crypto 50 MiB: put_median_ms=(\d+\.\d) get_median_ms=(\d+\.\d) runs=5\r?$/gm;

test("NFR1: put and get of a 50 MiB file each take a median under 1.5 s", { tag: "@perf" }, () => {
  test.setTimeout(10 * 60_000);
  const tables = ["organizations", "organization_keys", "chunk_embeddings"];
  const counts = () => tables.map((table) => sql(`select count(*) from ${table}`));
  const before = counts();

  const run = spawnSync(process.execPath, ["scripts/backend.mjs", "bench-crypto"], {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  const output = `${run.stdout ?? ""}\n${run.stderr ?? ""}`;
  expect(run.status, output.slice(-3000)).toBe(0);
  expect(output).toMatch(/1 passed/);

  // put = encrypt + write, get = read + decrypt; each median is below the limit.
  const found = [...(run.stdout ?? "").matchAll(BENCH_LINE)];
  expect(found, `exactly one benchmark result line in:\n${output.slice(-2000)}`).toHaveLength(1);
  const put = Number(found[0]?.[1]);
  const get = Number(found[0]?.[2]);
  expect(put).toBeGreaterThan(0);
  expect(get).toBeGreaterThan(0);
  expect(put).toBeLessThan(LIMIT_MS);
  expect(get).toBeLessThan(LIMIT_MS);
  console.log(`bench-crypto: put_median_ms=${put} get_median_ms=${get}`);

  // The benchmark leaves no Organization, key or vector row behind.
  expect(counts()).toEqual(before);
});
