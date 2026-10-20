// EA-22 (FND-05) round 2: anti-framing and Referrer-Policy headers on every admin HTML response.
// Black-box specs from .work/EA-22/contract.md. Runs against a running stack:
//   npm run e2e -- e2e/foundation/EA-22-admin-hardening*
// No sign-in and no POST: nothing here touches the shared 30/minute budget.
import { expect, test } from "@playwright/test";
import { ADMIN, ApiSession, DEMO_ORG, peopleOpsId, sleep } from "../support/ea22";

test("Security headers: every admin HTML response refuses framing and sends no Referer", async () => {
  const workspace = peopleOpsId();
  const pages = [
    "/",
    "/sign-in",
    "/forgot-password",
    "/set-password",
    `/set-password#token=${DEMO_ORG}.${"A".repeat(43)}`,
    "/reset",
    "/no-workspace",
    `/w/${workspace}/dashboard`,
    `/w/${workspace}/skills`,
    "/w/not-a-uuid/dashboard",
    "/not-a-page",
    "/not-a-page/deeper/path",
  ];
  const api = new ApiSession();
  for (const page of pages) {
    const path = page.split("#")[0] as string; // a fragment is never sent to the server
    const result = await api.send("GET", path);
    const label = `${path} (status ${result.status})`;
    expect(result.headers["content-type"], label).toContain("text/html");
    expect(result.headers["x-frame-options"], label).toBe("DENY");
    expect(result.headers["content-security-policy"], label).toContain("frame-ancestors 'none'");
    expect(result.headers["referrer-policy"], label).toBe("no-referrer");
  }
});

test("Security headers: a third-party page cannot show the sign-in form in a frame", async ({
  page,
}) => {
  await page.goto("about:blank");
  await page.setContent(
    `<iframe id="victim" src="${ADMIN}/sign-in" width="800" height="700"></iframe>`,
  );
  await sleep(2500); // give an unprotected page time to render in the frame
  const child = page.frames().find((frame) => frame !== page.mainFrame());
  const formsInFrame = child ? await child.getByTestId("sign-in-form").count() : 0;
  expect(formsInFrame, "the sign-in form is rendered inside a foreign frame").toBe(0);
  expect(child?.url() ?? "").not.toContain("/sign-in");

  // Control: the same page loads normally as a top-level document.
  await page.goto(`${ADMIN}/sign-in`);
  await expect(page.getByTestId("sign-in-form")).toBeVisible();
});

test("Security headers: leaving the set-password page sends no Referer", async ({ page }) => {
  const referers: (string | null)[] = [];
  await page.route("http://qa22-referrer-probe.example/**", async (route) => {
    referers.push(route.request().headers().referer ?? null);
    await route.fulfill({ status: 200, contentType: "text/html", body: "<p>probe</p>" });
  });
  await page.goto(`${ADMIN}/set-password#token=${DEMO_ORG}.${"E".repeat(43)}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Set your password");
  await page.evaluate(() => {
    window.location.href = "http://qa22-referrer-probe.example/landing";
  });
  await page.waitForURL("http://qa22-referrer-probe.example/**");
  expect(referers).toEqual([null]);
});
