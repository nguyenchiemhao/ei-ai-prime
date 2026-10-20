// EA-22 (FND-05) rate limit: 30 POST /auth/sign-in per minute per client IP, and 30 POST
// /auth/forgot-password per minute, counted separately. Tagged @slow because it waits for quiet minutes:
//   npm run e2e:full -- e2e/foundation/EA-22-sign-in-rate-limit*
// Locally every client shares one IP, so the test waits until the shared budget (see
// EA-22-admin-sign-in.spec.ts) has been quiet for a minute and books its own POSTs afterwards, so that
// later specs wait for the window to pass.
import { expect, test } from "@playwright/test";
import {
  ADMIN,
  ApiSession,
  DEMO_ORG,
  MSG,
  RUN,
  bookPosts,
  cleanup,
  expectDetail,
  inviteUser,
  newPassword,
  peopleOpsId,
  rows,
  secretValues,
  sha256Hex,
  waitForQuietWindow,
  withPage,
} from "../support/ea22";

test.describe.configure({ timeout: 360_000 });

test.afterAll(() => {
  cleanup();
});

test(
  "Rate limit: the 31st set-password POST within a minute is 429, keeps the token unused and does not block sign-in or forgot-password",
  { tag: "@slow" },
  async () => {
    const peopleOps = peopleOpsId();
    const user = inviteUser({ label: "rl-token", role: "builder", workspaceId: peopleOps });
    await waitForQuietWindow("set-password");
    await waitForQuietWindow("sign-in");
    await waitForQuietWindow("forgot");
    const api = new ApiSession();
    await api.ensureCsrf();
    const probe = { token: `${DEMO_ORG}.${"D".repeat(43)}`, password: "Qa22-limit-probe-1!" };
    secretValues.add(probe.password);

    // 30 guesses with an unknown token are answered, the 31st is throttled.
    const statuses: number[] = [];
    let last = await api.send("POST", "/api/auth/set-password", { json: probe });
    statuses.push(last.status);
    for (let count = 2; count <= 31; count++) {
      last = await api.send("POST", "/api/auth/set-password", { json: probe });
      statuses.push(last.status);
    }
    bookPosts("set-password", 31);
    expect(statuses.slice(0, 30)).toEqual(Array.from({ length: 30 }, () => 400));
    expect(statuses[30]).toBe(429);
    expectDetail(last, 429, "rate_limited");
    const retryAfter = Number(last.headers["retry-after"]);
    expect(Number.isInteger(retryAfter), `Retry-After "${last.headers["retry-after"]}"`).toBe(true);
    expect(retryAfter).toBeGreaterThan(0);
    expect(retryAfter).toBeLessThanOrEqual(60);
    expect(last.headers["cache-control"]).toContain("no-store");

    // While the bucket is full even the right token is refused and stays unused.
    const password = newPassword();
    const refused = await api.send("POST", "/api/auth/set-password", {
      json: { token: user.link.token, password },
    });
    bookPosts("set-password", 1);
    expectDetail(refused, 429, "rate_limited");
    expect(
      rows(
        `select token_hash from set_password_tokens where user_id = '${user.id}' and used_at is null`,
      ),
    ).toEqual([sha256Hex(user.link.secret)]);

    // The other two buckets are untouched.
    const signIn = await api.send("POST", "/api/auth/sign-in", {
      json: {
        email: `ratelimit.bucket.${RUN}@mekongdevworks.example`,
        password: "Wrong-password-0003",
      },
    });
    bookPosts("sign-in", 1);
    expectDetail(signIn, 401, "invalid_credentials");
    const forgot = await api.send("POST", "/api/auth/forgot-password", {
      json: { email: `ratelimit.bucket.${RUN}@mekongdevworks.example` },
    });
    bookPosts("forgot", 1);
    expect(forgot.status).toBe(202);

    // After the window the unused token works.
    await waitForQuietWindow("set-password");
    const accepted = await api.send("POST", "/api/auth/set-password", {
      json: { token: user.link.token, password },
    });
    bookPosts("set-password", 1);
    expect(accepted.status, accepted.text).toBe(204);
  },
);

test(
  "Rate limit: the 31st forgot-password POST within a minute is 429 and does not affect sign-in",
  { tag: "@slow" },
  async () => {
    await waitForQuietWindow("forgot");
    const api = new ApiSession();
    await api.ensureCsrf();
    const email = `ratelimit.forgot.${RUN}@mekongdevworks.example`;
    const statuses: number[] = [];
    let last = await api.send("POST", "/api/auth/forgot-password", { json: { email } });
    statuses.push(last.status);
    for (let count = 2; count <= 31; count++) {
      last = await api.send("POST", "/api/auth/forgot-password", { json: { email } });
      statuses.push(last.status);
    }
    bookPosts("forgot", 31);
    expect(statuses.slice(0, 30)).toEqual(Array.from({ length: 30 }, () => 202));
    expect(statuses[30]).toBe(429);
    expectDetail(last, 429, "rate_limited");
    expect(Number(last.headers["retry-after"])).toBeGreaterThan(0);
    expect(Number(last.headers["retry-after"])).toBeLessThanOrEqual(60);
  },
);

test(
  "Rate limit: the 31st sign-in POST within a minute is 429 rate_limited with Retry-After and the UI says so",
  { tag: "@slow" },
  async ({ browser }) => {
    await waitForQuietWindow("sign-in");
    const api = new ApiSession();
    await api.ensureCsrf();
    const email = `ratelimit.signin.${RUN}@mekongdevworks.example`;
    const statuses: number[] = [];
    let last = await api.send("POST", "/api/auth/sign-in", {
      json: { email, password: "Wrong-password-0001" },
    });
    statuses.push(last.status);
    for (let count = 2; count <= 31; count++) {
      last = await api.send("POST", "/api/auth/sign-in", {
        json: { email, password: "Wrong-password-0001" },
      });
      statuses.push(last.status);
    }
    bookPosts("sign-in", 31);

    // 30 answered normally (the forgot-password limit above does not count here), the 31st is limited.
    expect(statuses.slice(0, 30)).toEqual(Array.from({ length: 30 }, () => 401));
    expect(statuses[30]).toBe(429);
    expectDetail(last, 429, "rate_limited");
    const retryAfter = Number(last.headers["retry-after"]);
    expect(Number.isInteger(retryAfter), `Retry-After "${last.headers["retry-after"]}"`).toBe(true);
    expect(retryAfter).toBeGreaterThan(0);
    expect(retryAfter).toBeLessThanOrEqual(60);
    expect(last.headers["cache-control"]).toContain("no-store");

    // The browser shows the 429 message while the window is full.
    await withPage(browser, undefined, async (page) => {
      await page.goto("/sign-in");
      await page.getByLabel("Work email").fill(email);
      await page.getByLabel("Password", { exact: true }).fill("Wrong-password-0002");
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByTestId("sign-in-error")).toHaveText(MSG.tooMany);
      await expect(page).toHaveURL(`${ADMIN}/sign-in`);
      await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
    });
    bookPosts("sign-in", 1);
  },
);
