// EA-94 (FND-14) NFR: the seed of a fresh database takes 10 s or less on a local machine.
// Black-box: both demo Organizations are purged (children first, as the EA-21 spec does), then
// `npm run seed` is timed as a whole (docker compose exec included). The run leaves the demo seeded.
// Run: npm run e2e:perf -- e2e/foundation/EA-94-seed-perf.spec.ts
import { expect, test } from "@playwright/test";
import { cleanup, rows } from "../support/ea22";
import {
  EXPECTED_ROWS,
  ORGS,
  ORG_IDS,
  normalizeOutput,
  orgCounts,
  otherCounts,
  purgeDemoOrgs,
  FRESH_OUTPUT,
  removeRunTraces,
  repeatOutput,
  seed,
} from "../support/ea94";

test.describe.configure({ mode: "serial", timeout: 180_000 });

const LIMIT_MS = 10_000;
let outsideBefore: Record<string, number>;

test.beforeAll(() => {
  cleanup();
  const warmUp = seed("perf warm-up seed");
  expect(warmUp.status, warmUp.stderr).toBe(0);
  outsideBefore = otherCounts();
});

test.afterAll(() => {
  removeRunTraces();
  expect(orgCounts(ORGS.mekong.id)).toEqual(EXPECTED_ROWS.mekong);
  expect(orgCounts(ORGS.songhan.id)).toEqual(EXPECTED_ROWS.songhan);
  expect(otherCounts()).toEqual(outsideBefore);
});

test("NFR: a fresh seed of both Organizations takes at most 10 s", { tag: "@perf" }, async () => {
  purgeDemoOrgs();
  expect(
    rows(
      `select count(*) from organizations where id in (${ORG_IDS.map((id) => `'${id}'`).join(", ")})`,
    ),
  ).toEqual(["0"]);

  const fresh = seed("perf fresh seed");
  expect(fresh.status, fresh.stderr).toBe(0);
  expect(normalizeOutput(fresh.stdout)).toEqual(FRESH_OUTPUT);
  test.info().annotations.push({ type: "fresh seed ms", description: String(fresh.ms) });
  expect(fresh.ms, `fresh seed took ${fresh.ms} ms`).toBeLessThanOrEqual(LIMIT_MS);

  // A repeat run that creates nothing is not slower than the budget either.
  const repeat = seed("perf repeat seed");
  expect(repeat.status, repeat.stderr).toBe(0);
  expect(normalizeOutput(repeat.stdout)).toEqual(repeatOutput());
  test.info().annotations.push({ type: "repeat seed ms", description: String(repeat.ms) });
  expect(repeat.ms, `repeat seed took ${repeat.ms} ms`).toBeLessThanOrEqual(LIMIT_MS);
});
