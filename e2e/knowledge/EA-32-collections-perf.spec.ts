// EA-32 (KB-01) NFR: a list of 100 collections loads in 1 s or less. Black-box, own Workspace, all data
// removed afterwards. Run: npm run e2e:perf -- e2e/knowledge/EA-32-collections-perf.spec.ts
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { createWorkspace, watch, type QaUser, type ApiSession } from "../support/ea22";
import { signedInApi, withSession } from "../support/ea23";
import {
  MARK,
  SCREENSHOTS_32,
  cleanupAll,
  collectionsPath,
  counts,
  createCollection,
  createMember,
  markerRows,
  withoutStatuses,
  type CollectionItem,
  type Counts,
} from "../support/ea32";

test.describe.configure({ mode: "serial", timeout: 300_000 });

const TOTAL = 100;
const LIMIT_MS = 1000;
let workspaceId = "";
let admin: QaUser;
let session: ApiSession;
let baseline: Counts | undefined;

test.beforeAll(async () => {
  test.setTimeout(420_000);
  await cleanupAll();
  fs.mkdirSync(SCREENSHOTS_32, { recursive: true });
  baseline = counts();
  workspaceId = createWorkspace(`QA22 ${MARK} Perf`);
  admin = await createMember({ label: "perfadmin", role: "workspace_admin", workspaceId });
  session = await signedInApi(admin);
  // 100 collections of mixed access levels, in batches of 10 (names sort in a known order).
  for (let batch = 0; batch < TOTAL / 10; batch++) {
    const results = await Promise.all(
      Array.from({ length: 10 }, (_, offset) => {
        const index = batch * 10 + offset;
        const label = String(index).padStart(3, "0");
        const kind = index % 3;
        return createCollection(session, workspaceId, {
          name: `Perf ${label} ${MARK}`,
          subtitle: index % 5 === 0 ? `Subtitle ${label}` : null,
          access_level: ["authenticated", "public", "restricted"][kind],
          groups: kind === 2 ? ["managers", `team-${label}`] : [],
          local_only: index % 7 === 0,
        });
      }),
    );
    for (const result of results) expect(result.status, result.text).toBe(201);
  }
});

test.afterAll(async () => {
  await cleanupAll();
  if (baseline) expect(counts(), "rows left behind").toEqual(baseline);
  expect(markerRows(), "rows with the EA-32 marker left behind").toEqual([]);
});

test(
  "NFR: the list API answers 100 collections in 1 s or less, ordered by name",
  { tag: "@perf" },
  async () => {
    const timings: number[] = [];
    let items: CollectionItem[] = [];
    for (let run = 0; run < 3; run++) {
      const started = Date.now();
      const result = await session.send("GET", collectionsPath(workspaceId));
      timings.push(Date.now() - started);
      expect(result.status, result.text).toBe(200);
      items = (result.json as { collections: CollectionItem[] }).collections;
    }
    expect(items).toHaveLength(TOTAL);
    expect(items.map((item) => item.name)).toEqual(
      Array.from({ length: TOTAL }, (_, index) => `Perf ${String(index).padStart(3, "0")} ${MARK}`),
    );
    const median = [...timings].sort((a, b) => a - b)[1] ?? Number.POSITIVE_INFINITY;
    test.info().annotations.push({ type: "list-api-ms", description: timings.join(", ") });
    expect(median, `GET list timings ${timings.join(", ")} ms`).toBeLessThanOrEqual(LIMIT_MS);
  },
);

test(
  "NFR: the Collections screen shows the 100th row within 1 s of navigation",
  { tag: "@perf" },
  async ({ browser }) => {
    await withSession(browser, session, async (page) => {
      const seen = watch(page);
      const timings: number[] = [];
      for (let run = 0; run < 3; run++) {
        const started = Date.now();
        await page.goto(`/w/${workspaceId}/knowledge`);
        await expect(page.getByTestId("collection-row")).toHaveCount(TOTAL, { timeout: 5000 });
        await expect(page.getByTestId("collection-row").nth(TOTAL - 1)).toBeVisible();
        timings.push(Date.now() - started);
      }
      test.info().annotations.push({ type: "list-ui-ms", description: timings.join(", ") });
      const median = [...timings].sort((a, b) => a - b)[1] ?? Number.POSITIVE_INFINITY;
      expect(median, `navigation to the 100th row: ${timings.join(", ")} ms`).toBeLessThanOrEqual(
        LIMIT_MS,
      );

      // Every row still has badge text (never colour alone) and the search keeps working at this size.
      const badges = page.getByTestId("collection-row").getByTestId("access-badge");
      expect(await badges.count()).toBe(TOTAL);
      for (const text of await badges.allTextContents()) {
        expect(text.trim()).toMatch(/^(Public|Authenticated|Restricted · .+)$/);
      }
      await page.getByRole("textbox", { name: "Search collections" }).fill("perf 042");
      await expect(page.getByTestId("collection-row")).toHaveCount(1);
      await page.getByRole("textbox", { name: "Search collections" }).fill("");
      await expect(page.getByTestId("collection-row")).toHaveCount(TOTAL);
      await page.screenshot({
        path: path.join(SCREENSHOTS_32, "nfr-100-collections.png"),
        fullPage: true,
      });
      expect(withoutStatuses(seen.problems, [])).toEqual([]);
    });
  },
);
