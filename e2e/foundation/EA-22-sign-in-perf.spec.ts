// EA-22 (FND-05) AC1 performance: from the click on `Sign in` to the Dashboard heading is <= 2 s
// (median of 5 sign-ins). Tagged @perf: `npm run e2e:perf -- e2e/foundation/EA-22-sign-in-perf*`.
// The 5 sign-ins are booked in the shared 30/minute budget (see EA-22-admin-sign-in.spec.ts).
import { expect, test } from "@playwright/test";
import {
  ADMIN,
  RUN,
  cleanup,
  createReadyUser,
  peopleOpsId,
  reserve,
  secretValues,
  testEmails,
  withPage,
  type QaUser,
} from "../support/ea22";

test.describe.configure({ timeout: 240_000 });

let user: QaUser;
let peopleOps = "";

test.beforeAll(async () => {
  cleanup();
  peopleOps = peopleOpsId();
  user = await createReadyUser({
    label: "perf",
    role: "builder",
    workspaceId: peopleOps,
    name: `QA22 Perf ${RUN}`,
  });
});

test.afterAll(() => {
  cleanup();
});

test(
  "AC1 TC-1-P: sign-in to Dashboard heading takes at most 2 s (median of 5)",
  { tag: "@perf" },
  async ({ browser }) => {
    const samples: number[] = [];
    secretValues.add(user.password);
    testEmails.add(user.email);
    for (let run = 0; run < 5; run++) {
      await reserve("sign-in");
      await withPage(browser, undefined, async (page) => {
        await page.goto("/sign-in");
        await page.getByLabel("Work email").fill(user.email);
        await page.getByLabel("Password", { exact: true }).fill(user.password);
        const started = Date.now();
        await page.getByRole("button", { name: "Sign in" }).click();
        await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
        samples.push(Date.now() - started);
        await expect(page).toHaveURL(`${ADMIN}/w/${peopleOps}/dashboard`);
      });
    }
    const sorted = [...samples].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)] ?? Number.POSITIVE_INFINITY;
    test.info().annotations.push({
      type: "sign-in-ms",
      description: `samples ${samples.join(", ")}; median ${median}`,
    });
    expect(median, `sign-in samples (ms): ${samples.join(", ")}`).toBeLessThanOrEqual(2000);
  },
);
