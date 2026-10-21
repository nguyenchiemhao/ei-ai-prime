// EA-22 (FND-05): admin sign-in, lockout, passwords, session, set/forgot password, CSRF and tenant attacks.
// Black-box specs written from .work/EA-22/contract.md only. Runs against a running, migrated and seeded
// stack:  npm run up -- --no-model && npm run seed && npm run e2e -- e2e/foundation/EA-22-admin-sign-in*
// Sign-in budget: the API allows 30 sign-in POSTs per minute per client IP, shared by every spec. This file
// signs in through the UI once for the shared user (`mainState`), books every real POST in `reserve()` (it
// waits when the minute is full) and mocks the 429/5xx/network UI states. The Workspace shell is in
// EA-22-admin-shell.spec.ts, time and rate limit in EA-22-sign-in-perf / EA-22-sign-in-rate-limit.
// Test data: fresh users `qa22.<label>.<run>@mekongdevworks.example` in the demo Organization and a second
// Organization `QA EA-22 <run>`; everything is removed as the database superuser in afterAll.
import { expect, test, type Browser, type Page, type Request, type Route } from "@playwright/test";
import {
  ADMIN,
  ApiSession,
  DEMO_ORG,
  MSG,
  RUN,
  apiLogs,
  cleanup,
  createForeignOrg,
  createReadyUser,
  expectDetail,
  expectSameAnswer,
  inviteUser,
  issueLink,
  newPassword,
  parseSetCookie,
  peopleOpsId,
  recordedResults,
  reserve,
  resetSecrets,
  rows,
  secretValues,
  sha256Hex,
  signInUi,
  sleep,
  sql,
  testEmails,
  watch,
  withPage,
  withoutExpected401,
  type ForeignOrg,
  type Link,
  type QaUser,
  type SendOptions,
  type StorageState,
} from "../support/ea22";

const IDENTITY_PARAMS = /[?&](user_?id|org_?id|groups?|tenant)=/i;

test.describe.configure({ mode: "serial", timeout: 240_000 });

let peopleOps = "";
let main: QaUser;
let foreign: ForeignOrg;
let mainState: StorageState | undefined;
/** The user of the set-password tests: the first invite link, and the password that was set. */
let setPw: { user: QaUser; firstLink: Link; password: string } | undefined;

function dashboardUrl(workspaceId: string, area = "dashboard"): string {
  return `${ADMIN}/w/${workspaceId}/${area}`;
}

/** Signs in `main` through the UI once and returns the reusable browser storage state. */
async function mainSession(browser: Browser): Promise<StorageState> {
  if (mainState) return mainState;
  return withPage(browser, undefined, async (page, context) => {
    await signInUi(page, main.email, main.password);
    await expect(page).toHaveURL(dashboardUrl(peopleOps));
    mainState = await context.storageState();
    return mainState;
  });
}

function apiFrom(state: StorageState): ApiSession {
  return ApiSession.fromCookies(state.cookies.filter((cookie) => cookie.name.startsWith("ei_")));
}

function dbCredentials(user: QaUser): string {
  return (
    rows(
      `select failed_attempts || '|' || coalesce(locked_until::text, 'none')
       from user_credentials where user_id = '${user.id}'`,
    )[0] ?? "no row"
  );
}

function auditCount(action: string, actor: string, targetId: string): number {
  return Number(
    sql(
      `select count(*) from audit_events where org_id = '${DEMO_ORG}' and action = '${action}'
       and actor = '${actor}' and target_type = 'user' and target_id::text = '${targetId}'`,
    ),
  );
}

/** Seconds between the locking failure (its `user.locked_out` event) and `locked_until`. */
function lockSeconds(user: QaUser): number {
  return Number(
    sql(
      `select extract(epoch from (c.locked_until - a.created_at)) from user_credentials c, audit_events a
       where c.user_id = '${user.id}' and a.org_id = '${DEMO_ORG}' and a.action = 'user.locked_out'
       and a.target_id::text = '${user.id}'`,
    ),
  );
}

function sessionCount(user: QaUser): number {
  return Number(sql(`select count(*) from admin_sessions where user_id = '${user.id}'`));
}

function tokenHashes(user: QaUser): string[] {
  return rows(
    `select token_hash from set_password_tokens where user_id = '${user.id}' and used_at is null`,
  );
}

async function fillSignIn(page: Page, email: string, password: string): Promise<void> {
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Mocks POST /api/auth/sign-in on a page; the counter says how many requests reached the mock. */
async function mockSignIn(page: Page, handler: (route: Route) => Promise<void>) {
  const hits = { count: 0 };
  await page.route("**/api/auth/sign-in", async (route) => {
    hits.count += 1;
    await handler(route);
  });
  return hits;
}

/** Fills and submits a set-password / reset form. */
async function submitNewPassword(page: Page, password: string, confirm = password): Promise<void> {
  await reserve("set-password"); // every submit may reach POST /auth/set-password (30 per minute)
  await page.getByLabel("New password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(confirm);
  await page.getByRole("button", { name: "Set password" }).click();
}

/** The invalid-link alert may appear when the page loads or after the submit; both are accepted. */
async function expectInvalidLinkAlert(page: Page): Promise<void> {
  const alert = page.getByTestId("set-password-error");
  const onLoad = await alert
    .waitFor({ state: "visible", timeout: 1500 })
    .then(() => true)
    .catch(() => false);
  if (!onLoad) await submitNewPassword(page, newPassword());
  await expect(alert).toHaveText(MSG.linkInvalid);
  await expect(alert).toHaveAttribute("role", "alert");
}

const RESET_LINE =
  /Reset link \(valid 24 h, shown once\): \S*\/reset#token=([0-9a-f-]{36})\.([A-Za-z0-9_-]{43})/g;

function resetLinesInLogs(): RegExpMatchArray[] {
  return [...apiLogs().matchAll(RESET_LINE)];
}

test.beforeAll(async () => {
  cleanup(); // leftovers of a crashed earlier run of this ticket
  peopleOps = peopleOpsId();
  main = await createReadyUser({
    label: "main",
    role: "builder",
    workspaceId: peopleOps,
    name: `Trần Thị Mai ${RUN}`,
  });
  foreign = createForeignOrg();
});

test.afterAll(() => {
  cleanup();
});

// ---------------------------------------------------------------------------------------------
// AC1 sign in
// ---------------------------------------------------------------------------------------------

test("AC1: a valid user signs in and the Dashboard of the default workspace opens", async ({
  browser,
}) => {
  await withPage(browser, undefined, async (page, context) => {
    const seen = watch(page);
    const signInPosts: Request[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith("/api/auth/sign-in")) {
        signInPosts.push(request);
      }
    });

    await page.goto("/");
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
    await reserve("sign-in");
    secretValues.add(main.password);
    await page.getByLabel("Work email").fill(main.email);
    await page.getByLabel("Password", { exact: true }).fill(main.password);
    const clicked = Date.now();
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(dashboardUrl(peopleOps));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
    test.info().annotations.push({ type: "sign-in-ms", description: String(Date.now() - clicked) });
    await expect(page.getByTestId("area-page")).toHaveAttribute("data-area", "dashboard");
    await expect(page).toHaveTitle("Dashboard · ei-ai");

    // The form posts once, with the CSRF header equal to the ei_csrf cookie it sent.
    expect(signInPosts).toHaveLength(1);
    const headers = await signInPosts[0]?.allHeaders();
    const sentCookie = /(?:^|;\s*)ei_csrf=([^;]+)/.exec(headers?.cookie ?? "")?.[1];
    expect(sentCookie, "the browser sent an ei_csrf cookie").toBeTruthy();
    expect(headers?.["x-csrf-token"]).toBe(sentCookie);
    expect(signInPosts[0]?.postData() ?? "").not.toMatch(/org_?id|tenant/i);

    // The API agrees about the default Workspace (earliest membership) and the caller.
    const state = await context.storageState();
    const session = await apiFrom(state).session();
    expect(session.status).toBe(200);
    const body = session.json as {
      user: { id: string; display_name: string; email: string };
      organization: { id: string; name: string };
      workspaces: { id: string; name: string; role: string }[];
      default_workspace_id: string;
    };
    expect(body.default_workspace_id).toBe(peopleOps);
    expect(body.user).toEqual({ id: main.id, display_name: main.name, email: main.email });
    expect(body.organization).toEqual({ id: DEMO_ORG, name: "Mekong Devworks" });
    expect(body.workspaces).toHaveLength(1);
    expect(body.workspaces[0]).toMatchObject({ id: peopleOps, name: "People Ops" });
    expect(body.workspaces[0]?.role).toMatch(/builder/i);

    expect(seen.requests.filter((request) => IDENTITY_PARAMS.test(request.url))).toEqual([]);
    expect(withoutExpected401(seen.problems)).toEqual([]);
    mainState = state;
  });
});

test("AC1 TC-1-2: signed-in visitors of / and /sign-in land on their Dashboard; signed-out visitors on /sign-in", async ({
  browser,
}) => {
  const state = await mainSession(browser);
  await withPage(browser, state, async (page) => {
    await page.goto("/");
    await expect(page).toHaveURL(dashboardUrl(peopleOps));
    await page.goto("/sign-in");
    await expect(page).toHaveURL(dashboardUrl(peopleOps));
  });
  await withPage(browser, undefined, async (page) => {
    await page.goto("/");
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
    await page.goto(`/w/${peopleOps}/dashboard`);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
    await page.goto(`/w/${peopleOps}/glossary`);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
  });
});

test("AC1 TC-1-3: a user without a Workspace lands on /no-workspace and can sign out", async ({
  browser,
}) => {
  // EA-23: an Org Admin sees every Workspace, so the "no Workspace" user is an ordinary member whose
  // only Workspace membership was removed.
  const user = await createReadyUser({ label: "nows", role: "builder", workspaceId: peopleOps });
  sql(`delete from workspace_memberships where org_id = '${DEMO_ORG}' and user_id = '${user.id}'`);
  await withPage(browser, undefined, async (page, context) => {
    await signInUi(page, user.email, user.password);
    await expect(page).toHaveURL(`${ADMIN}/no-workspace`);
    const panel = page.getByTestId("no-workspace");
    await expect(panel.getByRole("heading", { level: 1 })).toHaveText("No Workspace yet");
    await expect(panel).toContainText(
      "You are not a member of any Workspace yet. Ask your organization admin.",
    );

    const session = await apiFrom(await context.storageState()).session();
    expect(session.status).toBe(200);
    expect(session.json).toMatchObject({ workspaces: [], default_workspace_id: null });

    // The Workspace of another member is not found for this user.
    await page.goto(`/w/${peopleOps}/dashboard`);
    await expect(page.getByTestId("not-found")).toBeVisible();
    await page.goto("/");
    await expect(page).toHaveURL(`${ADMIN}/no-workspace`);

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
  });
});

test("AC1 TC-1-4 (EA-23): an Org Admin without a Workspace role lands on a Workspace and sees all of them with role null", async ({
  browser,
}) => {
  const user = await createReadyUser({ label: "orgadm", role: "org_admin" });
  const all = rows(`select id from workspaces where org_id = '${DEMO_ORG}'`).sort();
  const first = rows(
    `select id from workspaces where org_id = '${DEMO_ORG}' order by created_at, id limit 1`,
  )[0];
  await withPage(browser, undefined, async (page, context) => {
    await signInUi(page, user.email, user.password);
    await expect(page).toHaveURL(dashboardUrl(first as string));
    const session = await apiFrom(await context.storageState()).session();
    const body = session.json as {
      org_role: string | null;
      workspaces: { id: string; role: string | null }[];
      default_workspace_id: string;
    };
    expect(body.org_role).toBe("org_admin");
    expect(body.default_workspace_id).toBe(first);
    expect(body.workspaces.map((workspace) => workspace.id).sort()).toEqual(all);
    expect(body.workspaces.every((workspace) => workspace.role === null)).toBe(true);
    await expect(page.getByTestId("user-menu")).toContainText("Org Admin");
  });
});

// ---------------------------------------------------------------------------------------------
// AC2 wrong credentials
// ---------------------------------------------------------------------------------------------

test("AC2: a wrong password and an unknown email show the same generic message", async ({
  browser,
}) => {
  const noPassword = inviteUser({ label: "nopw", role: "builder", workspaceId: peopleOps });
  const unknown = `nobody.${RUN}@mekongdevworks.example`;
  const wrong = `${newPassword()}x`;

  await withPage(browser, undefined, async (page) => {
    const alert = page.getByTestId("sign-in-error");
    for (const email of [main.email, unknown, noPassword.email]) {
      await signInUi(page, email, wrong);
      await expect(alert).toHaveText(MSG.invalid);
      await expect(alert).toHaveAttribute("role", "alert");
      await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
      await expect(page).toHaveURL(`${ADMIN}/sign-in`);
    }
    // The message never says which part was wrong.
    await expect(alert).not.toContainText(/exist|unknown|not found|locked|password is/i);
  });

  // The API answers identically for an existing user, an unknown email and a user without password.
  const api = new ApiSession();
  const existing = await api.signIn(main.email, wrong);
  expectDetail(existing, 401, "invalid_credentials");
  expectSameAnswer(await api.signIn(unknown, wrong), existing, "unknown email");
  expectSameAnswer(await api.signIn(noPassword.email, wrong), existing, "user without password");
  expect(existing.setCookies.filter((line) => line.startsWith("ei_session="))).toEqual([]);
  expect(existing.headers["cache-control"]).toContain("no-store");
});

test("AC2 TC-2-2: empty fields are reported under the field and send no request", async ({
  page,
}) => {
  const hits = await mockSignIn(page, (route) => route.abort());
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter your email")).toBeVisible();
  await expect(page.getByText("Enter your password")).toBeVisible();

  await page.getByLabel("Work email").fill("someone@mekongdevworks.example");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter your password")).toBeVisible();
  await expect(page.getByText("Enter your email")).toHaveCount(0);
  expect(hits.count).toBe(0);
});

test("AC2 TC-2-3: 429, 5xx and network failures show their own messages and clear the password", async ({
  page,
}) => {
  const cases: { name: string; message: string; respond: (route: Route) => Promise<void> }[] = [
    {
      name: "429",
      message: MSG.tooMany,
      respond: (route) =>
        route.fulfill({
          status: 429,
          contentType: "application/json",
          headers: { "Retry-After": "30" },
          body: JSON.stringify({ detail: "rate_limited" }),
        }),
    },
    {
      name: "503",
      message: MSG.unavailable,
      respond: (route) => route.fulfill({ status: 503, contentType: "text/plain", body: "down" }),
    },
    {
      name: "500",
      message: MSG.unavailable,
      respond: (route) =>
        route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "internal_error" }),
        }),
    },
    { name: "network", message: MSG.unavailable, respond: (route) => route.abort("failed") },
  ];
  for (const item of cases) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    const hits = await mockSignIn(page, item.respond);
    await page.goto("/sign-in");
    await fillSignIn(page, "someone@mekongdevworks.example", "Some-secret-1234");
    const alert = page.getByTestId("sign-in-error");
    await expect(alert, item.name).toHaveText(item.message);
    await expect(alert).toHaveAttribute("role", "alert");
    await expect(page.getByLabel("Password", { exact: true }), item.name).toHaveValue("");
    expect(hits.count, item.name).toBe(1);
  }
});

// ---------------------------------------------------------------------------------------------
// AC3 lockout
// ---------------------------------------------------------------------------------------------

test("AC3: 5 failures lock the account for 15 minutes, write one audit event and the lock is not extended", async ({
  browser,
}) => {
  const user = await createReadyUser({ label: "lock", role: "builder", workspaceId: peopleOps });
  const wrong = `${user.password}-wrong`;
  const api = new ApiSession();

  for (let attempt = 1; attempt <= 4; attempt++) {
    expectDetail(await api.signIn(user.email, wrong), 401, "invalid_credentials");
    expect(dbCredentials(user), `after failure ${attempt}`).toBe(`${attempt}|none`);
  }
  expect(auditCount("user.locked_out", "system", user.id)).toBe(0);

  const fifth = await api.signIn(user.email, wrong); // the 5th failure locks
  expectDetail(fifth, 401, "invalid_credentials");
  const lockedUntil = rows(
    `select locked_until::text from user_credentials where user_id = '${user.id}'`,
  )[0];
  expect(lockedUntil, "locked_until is set after the 5th failure").toBeTruthy();
  const remaining = Number(
    sql(
      `select round(extract(epoch from (locked_until - now()))) from user_credentials where user_id = '${user.id}'`,
    ),
  );
  expect(remaining).toBeGreaterThan(14 * 60 - 20);
  expect(remaining).toBeLessThanOrEqual(15 * 60);
  expect(auditCount("user.locked_out", "system", user.id)).toBe(1);
  // The lock lasts exactly 15 minutes from the locking failure (the time of its audit event).
  expect(Math.abs(lockSeconds(user) - 15 * 60)).toBeLessThan(2);

  // 6th attempt with the right password: the same generic message in the UI.
  await withPage(browser, undefined, async (page) => {
    await signInUi(page, user.email, user.password);
    await expect(page.getByTestId("sign-in-error")).toHaveText(MSG.invalid);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
  });
  // The locked answer is identical to a wrong password (status, body, header names).
  const rightWhileLocked = await api.signIn(user.email, user.password);
  expectSameAnswer(rightWhileLocked, fifth, "right password while locked");
  expect(rightWhileLocked.setCookies.filter((line) => line.startsWith("ei_session="))).toEqual([]);
  // Attempts while locked are not counted, do not extend the lock and write no second event.
  expect(
    rows(`select locked_until::text from user_credentials where user_id = '${user.id}'`)[0],
  ).toBe(lockedUntil);
  expect(auditCount("user.locked_out", "system", user.id)).toBe(1);
  expect(sessionCount(user)).toBe(0);

  // After the lock has passed (moved to the past as the superuser) the right password works.
  sql(
    `update user_credentials set locked_until = now() - interval '1 minute' where user_id = '${user.id}'`,
  );
  await withPage(browser, undefined, async (page) => {
    await signInUi(page, user.email, user.password);
    await expect(page).toHaveURL(dashboardUrl(peopleOps));
  });
  expect(dbCredentials(user).startsWith("0|")).toBe(true);
  expect(auditCount("user.signed_in", `user:${user.id}`, user.id)).toBeGreaterThanOrEqual(1);
});

test(
  "AC3 TC-3-2: 5 failures spread over more than 15 minutes do not lock; a success resets the count",
  { tag: "@slow" },
  async () => {
    const user = await createReadyUser({
      label: "spread",
      role: "builder",
      workspaceId: peopleOps,
    });
    const wrong = `${user.password}-wrong`;
    const api = new ApiSession();

    for (let attempt = 1; attempt <= 4; attempt++) {
      expectDetail(await api.signIn(user.email, wrong), 401, "invalid_credentials");
    }
    expect((await api.signIn(user.email, user.password)).status).toBe(200); // success resets
    expect(dbCredentials(user)).toBe("0|none");

    for (let attempt = 1; attempt <= 4; attempt++) {
      expectDetail(await api.signIn(user.email, wrong), 401, "invalid_credentials");
    }
    expect(dbCredentials(user)).toBe("4|none");
    // The 15-minute window of the first failure has passed (moved back as the superuser).
    sql(
      `update user_credentials set failure_window_started_at = now() - interval '16 minutes' where user_id = '${user.id}'`,
    );
    expectDetail(await api.signIn(user.email, wrong), 401, "invalid_credentials");
    expect(dbCredentials(user).endsWith("|none")).toBe(true);
    expect(auditCount("user.locked_out", "system", user.id)).toBe(0);
    expect((await api.signIn(user.email, user.password)).status).toBe(200);
  },
);

test(
  "AC3 TC-3-3: setting a password through a new link clears the lock and ends all sessions",
  { tag: "@slow" },
  async () => {
    const user = await createReadyUser({
      label: "unlock",
      role: "builder",
      workspaceId: peopleOps,
    });
    const session = new ApiSession();
    expect((await session.signIn(user.email, user.password)).status).toBe(200);
    expect((await session.session()).status).toBe(200);

    const attacker = new ApiSession();
    for (let attempt = 1; attempt <= 5; attempt++) {
      await attacker.signIn(user.email, `${user.password}-wrong`);
    }
    expect(dbCredentials(user).endsWith("|none")).toBe(false);

    const link = issueLink(user);
    const fresh = newPassword();
    const set = await new ApiSession().setPassword(link.token, fresh);
    expect(set.status, set.text).toBe(204);
    expect(dbCredentials(user)).toBe("0|none");
    expectDetail(await session.session(), 401, "unauthenticated");
    expect((await new ApiSession().signIn(user.email, fresh)).status).toBe(200);
    expect(sessionCount(user)).toBe(1);
  },
);

// ---------------------------------------------------------------------------------------------
// AC4 passwords, set password via one-time link
// ---------------------------------------------------------------------------------------------

test("AC4: a password under 12 characters is refused (token stays usable), 12 characters succeed, the hash is Argon2id", async ({
  browser,
}) => {
  const user = inviteUser({ label: "setpw", role: "builder", workspaceId: peopleOps });
  const firstLink = user.link;
  const link = issueLink(user); // only the newest link of a user works
  user.password = newPassword();
  secretValues.add(user.password);
  const api = new ApiSession();

  // The older link is dead as soon as a newer one exists.
  expectDetail(await api.setPassword(firstLink.token, user.password), 400, "invalid_token");

  // API: length is checked before the token; the token stays usable after a 422.
  const short = "Short-pw-11"; // 11 characters
  expect(short).toHaveLength(11);
  expectDetail(await api.setPassword(link.token, short), 422, "password_too_short");
  expectDetail(await api.setPassword(link.token, "x".repeat(129)), 422, "password_too_long");
  expectDetail(
    await api.setPassword(`${DEMO_ORG}.${"A".repeat(43)}`, short),
    422,
    "password_too_short",
  );
  expect(tokenHashes(user)).toEqual([sha256Hex(link.secret)]);

  await withPage(browser, undefined, async (page) => {
    await page.goto(`${ADMIN}/set-password#token=${link.token}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Set your password");
    await expect(page).toHaveTitle("Set your password · ei-ai");
    await expect.poll(() => page.url()).not.toContain("token");
    expect(page.url()).not.toContain(link.secret);
    await expect(page.getByText("At least 12 characters.")).toBeVisible();
    await expect(page.getByLabel("New password", { exact: true })).toHaveAttribute(
      "autocomplete",
      "new-password",
    );

    await submitNewPassword(page, short);
    await expect(page.getByText("Use at least 12 characters.")).toBeVisible();
    await submitNewPassword(page, "x".repeat(129));
    await expect(page.getByText("Use at most 128 characters.")).toBeVisible();
    await submitNewPassword(page, user.password, `${user.password}-other`);
    await expect(page.getByText("The passwords do not match.")).toBeVisible();

    await submitNewPassword(page, user.password);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
    await expect(page.getByTestId("sign-in-notice")).toHaveText(MSG.passwordSet);
    await expect(page.getByTestId("sign-in-notice")).toHaveAttribute("role", "status");
  });

  // Argon2id, never the plain text; one audit event of the user; the token is used up.
  const hash = rows(`select password_hash from user_credentials where user_id = '${user.id}'`)[0];
  expect(hash?.startsWith("$argon2id$")).toBe(true);
  expect(hash).not.toContain(user.password);
  expect(
    rows(
      `select (password_set_at is not null)::text from user_credentials where user_id = '${user.id}'`,
    ),
  ).toEqual(["true"]);
  expect(auditCount("user.password_set", `user:${user.id}`, user.id)).toBe(1);
  expect(tokenHashes(user)).toEqual([]);
  setPw = { user, firstLink, password: user.password };
});

test("AC4 TC-4-2: exactly 12 and exactly 128 characters are accepted, Vietnamese passwords work", async () => {
  const twelve = "Qa22-abcdef!";
  expect(twelve).toHaveLength(12);
  const longest = "Qa22-".padEnd(128, "x");
  expect(longest).toHaveLength(128);
  const diacritics = "Mật-khẩu-Việt-2026";

  const users: QaUser[] = [];
  for (const [label, password] of [
    ["pw12", twelve],
    ["pw128", longest],
    ["pwvi", diacritics],
  ] as const) {
    const user = await createReadyUser({
      label,
      role: "builder",
      workspaceId: peopleOps,
      password,
    });
    const hash = rows(`select password_hash from user_credentials where user_id = '${user.id}'`)[0];
    expect(hash?.startsWith("$argon2id$"), label).toBe(true);
    expect(hash).not.toContain(password);
    users.push(user);
  }
  // The Vietnamese password really signs in.
  const vi = users[2] as QaUser;
  const result = await new ApiSession().signIn(vi.email, vi.password);
  expect(result.status, result.text).toBe(200);
});

test("AC4 TC-4-3: unknown, expired, malformed and foreign-Organization tokens are rejected with invalid_token", async ({
  browser,
}) => {
  const user = inviteUser({ label: "badtoken", role: "builder", workspaceId: peopleOps });
  const api = new ApiSession();
  const good = newPassword();
  const secret = user.link.secret;
  const tokens = [
    `${DEMO_ORG}.${"B".repeat(43)}`, // unknown secret
    secret, // no organization part
    "", // empty
    `${DEMO_ORG}.abc`, // too short
    `${foreign.orgId}.${secret}`, // another Organization's id with a valid-looking secret
    `not-a-uuid.${secret}`,
  ];
  for (const token of tokens) {
    expectDetail(await api.setPassword(token, good), 400, "invalid_token");
  }
  // Expired (moved to the past as the superuser).
  sql(
    `update set_password_tokens set expires_at = now() - interval '1 minute' where user_id = '${user.id}' and used_at is null`,
  );
  expectDetail(await api.setPassword(user.link.token, good), 400, "invalid_token");
  expect(rows(`select 1 from user_credentials where user_id = '${user.id}'`)).toEqual([]);

  // The page shows the same message for an expired, a malformed and a missing token.
  await withPage(browser, undefined, async (page) => {
    for (const fragment of [`#token=${user.link.token}`, "#token=garbage", ""]) {
      await page.goto(`${ADMIN}/set-password${fragment}`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Set your password");
      await expectInvalidLinkAlert(page);
    }
  });
});

// ---------------------------------------------------------------------------------------------
// Set password via link, forgot password
// ---------------------------------------------------------------------------------------------

test("Set password via link: the new password signs in; the same link again shows the invalid-link alert", async ({
  browser,
}) => {
  expect(setPw, "the AC4 test must run first (serial)").toBeDefined();
  const { user, firstLink, password } = setPw as NonNullable<typeof setPw>;
  await withPage(browser, undefined, async (page) => {
    await signInUi(page, user.email, password);
    await expect(page).toHaveURL(dashboardUrl(peopleOps));
  });
  // The used link and the older one are both dead.
  const api = new ApiSession();
  expectDetail(await api.setPassword(user.link.token, newPassword()), 400, "invalid_token");
  expectDetail(await api.setPassword(firstLink.token, newPassword()), 400, "invalid_token");
  await withPage(browser, undefined, async (page) => {
    await page.goto(`${ADMIN}/set-password#token=${user.link.token}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Set your password");
    await expectInvalidLinkAlert(page);
    await expect(page).not.toHaveURL(`${ADMIN}/sign-in`);
  });
  // The original password still works (the second attempt changed nothing).
  expect((await new ApiSession().signIn(user.email, password)).status).toBe(200);
});

test("Forgot password: the confirmation is identical for any email; a reset link is printed only for a real account", async ({
  browser,
}) => {
  const user = inviteUser({ label: "forgot", role: "builder", workspaceId: peopleOps });
  const unknown = `nobody.forgot.${RUN}@mekongdevworks.example`;
  const before = resetLinesInLogs().length;

  // API: identical answer for a known and an unknown email, empty body.
  const api = new ApiSession();
  const known = await api.forgotPassword(user.email);
  expect(known.status).toBe(202);
  expect(known.text).toBe("");
  await expect.poll(() => resetLinesInLogs().length, { timeout: 15_000 }).toBe(before + 1);
  expectSameAnswer(await api.forgotPassword(unknown), known, "unknown email");
  await sleep(1500);
  expect(resetLinesInLogs().length, "an unknown email prints nothing").toBe(before + 1);
  expect(tokenHashes(user)).toHaveLength(1);
  // The invite link was replaced by the forgot-password link.
  expectDetail(await api.setPassword(user.link.token, newPassword()), 400, "invalid_token");

  await withPage(browser, undefined, async (page) => {
    await page.goto("/sign-in");
    await page.getByRole("link", { name: "Forgot password?" }).click();
    await expect(page).toHaveURL(`${ADMIN}/forgot-password`);
    await expect(page).toHaveTitle("Forgot password · ei-ai");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Forgot password");
    await expect(
      page.getByText("Enter your work email. We will send you a link to set a new password."),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to sign in" })).toBeVisible();

    // Unknown email: the confirmation, no new line.
    await reserve("forgot");
    await page.getByLabel("Work email").fill(unknown);
    await page.getByRole("button", { name: "Send reset link" }).click();
    await expect(page.getByTestId("forgot-password-confirmation")).toHaveText(
      MSG.forgotConfirmation,
    );
    await sleep(1500);
    expect(resetLinesInLogs().length).toBe(before + 1);

    // Known email: the same confirmation and a Reset link line whose secret belongs to this user.
    await page.goto("/forgot-password");
    await reserve("forgot");
    await page.getByLabel("Work email").fill(user.email);
    await page.getByRole("button", { name: "Send reset link" }).click();
    await expect(page.getByTestId("forgot-password-confirmation")).toHaveText(
      MSG.forgotConfirmation,
    );
    await expect.poll(() => resetLinesInLogs().length, { timeout: 15_000 }).toBe(before + 2);
    const hashes = new Set(tokenHashes(user));
    expect(hashes.size).toBe(1);
    const mine = resetLinesInLogs().find((match) => hashes.has(sha256Hex(match[2] as string)));
    expect(mine, "a Reset link line for this user's current token").toBeDefined();
    expect(mine?.[1]).toBe(DEMO_ORG);
    const token = `${mine?.[1]}.${mine?.[2]}`;
    resetSecrets.add(mine?.[2] as string);

    // The reset page sets a new password and the user can sign in with it.
    const fresh = newPassword();
    await page.goto(`${ADMIN}/reset#token=${token}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Reset your password");
    await expect(page).toHaveTitle("Reset your password · ei-ai");
    await expect.poll(() => page.url()).not.toContain("token");
    await submitNewPassword(page, fresh);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
    await expect(page.getByTestId("sign-in-notice")).toHaveText(MSG.passwordSet);
    await signInUi(page, user.email, fresh);
    await expect(page).toHaveURL(dashboardUrl(peopleOps));
  });
  expect(auditCount("user.set_password_link_issued", "system", user.id)).toBeGreaterThanOrEqual(1);
  expect(auditCount("user.password_set", `user:${user.id}`, user.id)).toBe(1);
});

// ---------------------------------------------------------------------------------------------
// AC5 session
// ---------------------------------------------------------------------------------------------

test("AC5: cookie flags, session expiry after 12 h idle, sign-out destroys the session server-side", async ({
  browser,
}) => {
  const user = await createReadyUser({ label: "session", role: "builder", workspaceId: peopleOps });

  // (a) Cookie A through the API: exact attributes on the wire.
  const apiA = new ApiSession();
  const signedIn = await apiA.signIn(user.email, user.password);
  expect(signedIn.status, signedIn.text).toBe(200);
  expect(signedIn.json).toEqual({ default_workspace_id: peopleOps });
  expect(signedIn.headers["cache-control"]).toContain("no-store");
  const sessionLine = signedIn.setCookies.find((line) => line.startsWith("ei_session="));
  const csrfLine = signedIn.setCookies.find((line) => line.startsWith("ei_csrf="));
  expect(sessionLine, "Set-Cookie ei_session").toBeDefined();
  expect(csrfLine, "Set-Cookie ei_csrf").toBeDefined();
  const sessionAttrs = parseSetCookie(sessionLine ?? "").attrs.map((attr) => attr.toLowerCase());
  expect(sessionAttrs).toEqual(
    expect.arrayContaining(["httponly", "secure", "samesite=lax", "path=/"]),
  );
  expect(sessionAttrs.filter((attr) => /^(expires|max-age)=/.test(attr))).toEqual([]);
  const csrfAttrs = parseSetCookie(csrfLine ?? "").attrs.map((attr) => attr.toLowerCase());
  expect(csrfAttrs).toEqual(expect.arrayContaining(["secure", "samesite=strict", "path=/"]));
  expect(csrfAttrs).not.toContain("httponly");
  expect(sessionCount(user)).toBe(1);
  const cookieA = apiA.sessionCookie as string;
  const storedHash = rows(`select token_hash from admin_sessions where user_id = '${user.id}'`)[0];
  expect(storedHash).toMatch(/^[0-9a-f]{64}$/);
  expect(storedHash).not.toContain(cookieA);
  expect((await apiA.session()).status).toBe(200);

  // (b) Cookie B through the browser: flags as the browser sees them, hidden from scripts.
  await withPage(browser, undefined, async (page, context) => {
    await signInUi(page, user.email, user.password);
    await expect(page).toHaveURL(dashboardUrl(peopleOps));
    const cookies = await context.cookies();
    const session = cookies.find((cookie) => cookie.name === "ei_session");
    const csrf = cookies.find((cookie) => cookie.name === "ei_csrf");
    expect(session).toMatchObject({ httpOnly: true, secure: true, sameSite: "Lax", path: "/" });
    expect(session?.expires, "a session cookie has no expiry").toBe(-1);
    expect(csrf).toMatchObject({ secure: true, sameSite: "Strict", path: "/", httpOnly: false });
    const visible = await page.evaluate(() => document.cookie);
    expect(visible).not.toContain("ei_session");
    expect(visible).toContain("ei_csrf");
    expect(sessionCount(user), "a new session on every sign-in").toBe(2);
    const cookieB = session?.value as string;
    secretValues.add(cookieB);
    expect(cookieB).not.toBe(cookieA);

    // Sign out from the user menu: back on /sign-in, the old cookie is dead server-side.
    await page.getByTestId("user-menu").click();
    await page.getByText("Sign out", { exact: true }).click();
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
    expect(sessionCount(user), "the signed-out session is deleted, the other one is not").toBe(1);
    const replay = ApiSession.fromCookies([{ name: "ei_session", value: cookieB }]);
    expectDetail(await replay.session(), 401, "unauthenticated");
    expectDetail(await replay.workspace(peopleOps), 401, "unauthenticated");
    await page.goto(`/w/${peopleOps}/dashboard`);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
  });
  expect((await apiA.session()).status, "signing out B leaves A valid").toBe(200);
  expect(auditCount("user.signed_out", `user:${user.id}`, user.id)).toBe(1);
  expect(auditCount("user.signed_in", `user:${user.id}`, user.id)).toBeGreaterThanOrEqual(2);

  // (c) Inactivity: 11 h 59 min is still valid (and counts as use), 12 h 1 min is not.
  sql(
    `update admin_sessions set last_seen_at = now() - interval '11 hours 59 minutes' where user_id = '${user.id}'`,
  );
  expect((await apiA.session()).status).toBe(200);
  sql(
    `update admin_sessions set last_seen_at = now() - interval '12 hours 1 minute' where user_id = '${user.id}'`,
  );
  await withPage(browser, undefined, async (page, context) => {
    await context.addCookies([
      {
        name: "ei_session",
        value: cookieA,
        url: ADMIN,
        httpOnly: true,
        secure: true,
        sameSite: "Lax",
      },
    ]);
    await page.goto(`/w/${peopleOps}/dashboard`);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
  });
  expectDetail(await apiA.session(), 401, "unauthenticated");
});

test("AC5 TC-5-2: a missing, malformed or forged session cookie is unauthenticated and the SPA lands on /sign-in", async ({
  browser,
}) => {
  const forged = [
    "",
    "garbage",
    `${DEMO_ORG}.${"A".repeat(43)}`,
    `${foreign.orgId}.${"A".repeat(43)}`,
    "A".repeat(43),
    "x".repeat(2048),
  ];
  for (const value of forged) {
    const api = ApiSession.fromCookies(value === "" ? [] : [{ name: "ei_session", value }]);
    expectDetail(await api.session(), 401, "unauthenticated");
    expectDetail(await api.workspace(peopleOps), 401, "unauthenticated");
  }
  await withPage(browser, undefined, async (page, context) => {
    await context.addCookies([
      {
        name: "ei_session",
        value: `${DEMO_ORG}.${"A".repeat(43)}`,
        url: ADMIN,
        httpOnly: true,
        secure: true,
        sameSite: "Lax",
      },
    ]);
    await page.goto(`/w/${peopleOps}/dashboard`);
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
  });
});

// ---------------------------------------------------------------------------------------------
// CSRF, validation, tenant attacks
// ---------------------------------------------------------------------------------------------

test("CSRF: state-changing requests need a matching X-CSRF-Token and the admin Origin", async () => {
  const user = await createReadyUser({ label: "csrf", role: "builder", workspaceId: peopleOps });

  // GET /auth/csrf hands out the token as cookie and body.
  const api = new ApiSession();
  const issued = await api.send("GET", "/api/auth/csrf");
  expect(issued.status).toBe(200);
  const token = (issued.json as { csrf_token: string }).csrf_token;
  expect(token).toBeTruthy();
  expect(api.csrfCookie).toBe(token);
  expect(issued.headers["cache-control"]).toContain("no-store");
  const csrfAttrs = parseSetCookie(
    issued.setCookies.find((line) => line.startsWith("ei_csrf=")) ?? "",
  ).attrs.map((attr) => attr.toLowerCase());
  expect(csrfAttrs).toEqual(expect.arrayContaining(["secure", "samesite=strict", "path=/"]));
  expect(csrfAttrs).not.toContain("httponly");

  // Sign-in with correct credentials is still refused: no session is created.
  secretValues.add(user.password);
  testEmails.add(user.email);
  const attempts: [string, SendOptions][] = [
    ["no header", { csrf: "none" }],
    ["wrong header", { csrf: "not-the-token-1234567890" }],
    ["foreign origin", { origin: "https://evil.example" }],
    ["header without cookie", { cookies: {} }],
  ];
  for (const [label, options] of attempts) {
    await reserve("sign-in");
    const result = await api.send("POST", "/api/auth/sign-in", {
      json: { email: user.email, password: user.password },
      ...options,
    });
    expectDetail(result, 403, "csrf_failed");
    expect(
      result.setCookies.filter((line) => line.startsWith("ei_session=")),
      label,
    ).toEqual([]);
  }
  expect(sessionCount(user)).toBe(0);

  // Origin is checked only when sent: no Origin plus a valid token signs in.
  await reserve("sign-in");
  const ok = await api.send("POST", "/api/auth/sign-in", {
    json: { email: user.email, password: user.password },
    origin: null,
  });
  expect(ok.status, ok.text).toBe(200);
  expect((await api.session()).status).toBe(200);

  // Every state-changing request that carries the session needs the token and the Origin.
  expectDetail(await api.send("POST", "/api/auth/sign-out", { csrf: "none" }), 403, "csrf_failed");
  expectDetail(
    await api.send("POST", "/api/auth/sign-out", { origin: "https://evil.example" }),
    403,
    "csrf_failed",
  );
  expectDetail(
    await api.send("DELETE", `/api/workspaces/${peopleOps}`, { csrf: "none" }),
    403,
    "csrf_failed",
  );
  expectDetail(
    await api.send("PATCH", `/api/workspaces/${peopleOps}`, { csrf: "wrong", json: {} }),
    403,
    "csrf_failed",
  );
  expect((await api.session()).status, "the refused sign-outs did not end the session").toBe(200);
  const out = await api.signOut();
  expect(out.status).toBe(204);
  expect(out.setCookies.some((line) => /^ei_session=;|max-age=0/i.test(line))).toBe(true);
  expectDetail(await api.session(), 401, "unauthenticated");
  expect((await api.signOut()).status, "sign-out without a session is 204").toBe(204);

  // forgot-password and set-password are protected too; a refused set-password keeps the token.
  const anon = new ApiSession();
  await anon.ensureCsrf();
  await reserve("forgot");
  expectDetail(
    await anon.send("POST", "/api/auth/forgot-password", {
      json: { email: user.email },
      csrf: "none",
    }),
    403,
    "csrf_failed",
  );
  const invited = inviteUser({ label: "csrf2", role: "builder", workspaceId: peopleOps });
  const password = newPassword();
  await reserve("set-password");
  expectDetail(
    await anon.send("POST", "/api/auth/set-password", {
      json: { token: invited.link.token, password },
      csrf: "none",
    }),
    403,
    "csrf_failed",
  );
  expect(tokenHashes(invited)).toEqual([sha256Hex(invited.link.secret)]);
  expect((await anon.setPassword(invited.link.token, password)).status).toBe(204);
});

test("API validation: a malformed body is 422 invalid_request and never echoes the submitted values", async () => {
  await reserve("sign-in", 4);
  await reserve("forgot");
  const api = new ApiSession();
  await api.ensureCsrf();
  const secret = "Echo-probe-Secret-4242";
  const bodies: SendOptions[] = [
    { json: { email: 123, password: secret } },
    { json: { email: `echo.${RUN}@mekongdevworks.example` } },
    { json: {} },
    { rawBody: `{"email": "${secret}", "password":` },
  ];
  for (const options of bodies) {
    const result = await api.send("POST", "/api/auth/sign-in", options);
    expectDetail(result, 422, "invalid_request");
    expect(result.text).not.toContain(secret);
    expect(result.text).not.toContain("echo.");
  }
  expectDetail(
    await api.send("POST", "/api/auth/forgot-password", { json: { email: 5 } }),
    422,
    "invalid_request",
  );
  await reserve("set-password");
  expectDetail(
    await api.send("POST", "/api/auth/set-password", { json: { token: 5, password: secret } }),
    422,
    "invalid_request",
  );
});

test("Attack: org_id and tenant headers or parameters are ignored; a foreign Organization cannot read the demo Workspaces", async ({
  browser,
}) => {
  const state = await mainSession(browser);
  const api = apiFrom(state);
  const probes: SendOptions[] = [
    { headers: { "X-Org-Id": foreign.orgId, "X-Tenant-Id": foreign.orgId } },
    { headers: { "X-Organization-Id": foreign.orgId, "X-User-Id": foreign.ownerId } },
  ];
  for (const options of probes) {
    const result = await api.send("GET", "/api/auth/session", options);
    expect(result.status).toBe(200);
    expect(result.json).toMatchObject({
      user: { id: main.id },
      organization: { id: DEMO_ORG },
    });
    expect(result.text).not.toContain(foreign.workspaceId);
  }
  const withQuery = await api.send(
    "GET",
    `/api/auth/session?org_id=${foreign.orgId}&tenant_id=${foreign.orgId}&user_id=${foreign.ownerId}`,
  );
  expect(withQuery.json).toMatchObject({ organization: { id: DEMO_ORG }, user: { id: main.id } });
  const asked = await api.send("GET", `/api/workspaces/${peopleOps}`, {
    headers: { "X-Org-Id": foreign.orgId },
  });
  expect(asked.status).toBe(200);
  expect(asked.json).toMatchObject({ id: peopleOps });

  // The owner of the other Organization sees only their own Workspace; the demo ones are not found.
  const owner = new ApiSession();
  const foreignPassword = newPassword();
  const set = await owner.setPassword(foreign.link.token, foreignPassword);
  expect(set.status, set.text).toBe(204);
  const signedIn = await owner.signIn(foreign.ownerEmail, foreignPassword);
  expect(signedIn.status, signedIn.text).toBe(200);
  expect(signedIn.json).toEqual({ default_workspace_id: foreign.workspaceId });
  const session = await owner.session();
  expect(session.json).toMatchObject({
    user: { id: foreign.ownerId },
    organization: { id: foreign.orgId },
    default_workspace_id: foreign.workspaceId,
  });
  expect((session.json as { workspaces: { id: string }[] }).workspaces.map((w) => w.id)).toEqual([
    foreign.workspaceId,
  ]);
  const randomAnswer = await owner.workspace("0192a000-0000-7000-8000-000000000bad");
  expectDetail(randomAnswer, 404, "not_found");
  expectSameAnswer(await owner.workspace(peopleOps), randomAnswer, "demo Workspace from org B");
  expect((await owner.workspace(foreign.workspaceId)).status).toBe(200);
  // ... and the tenant context cannot be switched with a header.
  const forgedHeader = await owner.send("GET", `/api/workspaces/${peopleOps}`, {
    headers: { "X-Org-Id": DEMO_ORG, "X-Tenant-Id": DEMO_ORG },
  });
  expectSameAnswer(forgedHeader, randomAnswer, "demo Workspace with a forged tenant header");
});

// ---------------------------------------------------------------------------------------------
// AC4 (logs) and secret hygiene: keep this test last, it inspects everything the file produced
// ---------------------------------------------------------------------------------------------

// ---------------------------------------------------------------------------------------------
// Round 2: set-password check order, second link in the same tab, parallel lockout
// ---------------------------------------------------------------------------------------------

test("AC4 TC-4-6: set-password checks the length first, then a malformed token, then the token itself", async () => {
  const user = inviteUser({ label: "order", role: "builder", workspaceId: peopleOps });
  const api = new ApiSession();
  const valid = newPassword();
  const short = "Short-pw-11";
  const malformed = ["not-a-token", DEMO_ORG, `not-a-uuid.${user.link.secret}`, ""];

  for (const token of malformed) {
    expectDetail(await api.setPassword(token, short), 422, "password_too_short");
    expectDetail(await api.setPassword(token, "x".repeat(129)), 422, "password_too_long");
    expectDetail(await api.setPassword(token, valid), 400, "invalid_token");
  }
  // A well-formed but unknown token is the last check.
  expectDetail(await api.setPassword(`${DEMO_ORG}.${"C".repeat(43)}`, valid), 400, "invalid_token");
  // A used token: valid password -> invalid_token; short password -> still the length error first.
  expect((await api.setPassword(user.link.token, valid)).status).toBe(204);
  expectDetail(await api.setPassword(user.link.token, newPassword()), 400, "invalid_token");
  expectDetail(await api.setPassword(user.link.token, short), 422, "password_too_short");
});

for (const route of ["set-password", "reset"] as const) {
  test(`Second link in the same tab (/${route}): the form is cleared, the fragment removed and the new link token is used`, async ({
    browser,
  }) => {
    const a = inviteUser({ label: `tab-a-${route}`, role: "builder", workspaceId: peopleOps });
    const b = inviteUser({ label: `tab-b-${route}`, role: "builder", workspaceId: peopleOps });
    const heading = route === "reset" ? "Reset your password" : "Set your password";
    const password = newPassword();

    await withPage(browser, undefined, async (page) => {
      await page.goto(`${ADMIN}/${route}#token=${a.link.token}`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
      await expect.poll(() => page.url()).toBe(`${ADMIN}/${route}`);
      const newField = page.getByLabel("New password", { exact: true });
      const confirm = page.getByLabel("Confirm password", { exact: true });

      // Leave a field error and typed values behind, then open link B in the same tab.
      await submitNewPassword(page, "Short-pw-11");
      await expect(page.getByText("Use at least 12 characters.")).toBeVisible();
      await newField.fill("typed-before-the-switch-1");
      await confirm.fill("typed-before-the-switch-1");
      await page.goto(`${ADMIN}/${route}#token=${b.link.token}`);

      await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
      await expect(newField).toHaveValue("");
      await expect(confirm).toHaveValue("");
      await expect(page.getByText("Use at least 12 characters.")).toHaveCount(0);
      await expect(page.getByTestId("set-password-error")).toHaveCount(0);
      await expect.poll(() => page.url()).toBe(`${ADMIN}/${route}`);

      await submitNewPassword(page, password);
      await expect(page).toHaveURL(`${ADMIN}/sign-in`);
      await expect(page.getByTestId("sign-in-notice")).toHaveText(MSG.passwordSet);
    });

    // Link B was used; link A was never submitted and still works.
    const credentials = (user: QaUser) =>
      rows(`select 1 from user_credentials where user_id = '${user.id}'`).length;
    expect(credentials(b), "the new link's user has a password").toBe(1);
    expect(credentials(a), "the first link's user has none").toBe(0);
    const api = new ApiSession();
    expectDetail(await api.setPassword(b.link.token, newPassword()), 400, "invalid_token");
    expect((await api.setPassword(a.link.token, newPassword())).status).toBe(204);
  });
}

test("Second link in the same tab: the invalid-link alert of a dead link is cleared by a valid link", async ({
  browser,
}) => {
  const dead = inviteUser({ label: "tab-dead", role: "builder", workspaceId: peopleOps });
  const deadLink = dead.link;
  issueLink(dead); // the invite link is replaced, so deadLink no longer works
  const good = inviteUser({ label: "tab-good", role: "builder", workspaceId: peopleOps });

  await withPage(browser, undefined, async (page) => {
    await page.goto(`${ADMIN}/set-password#token=${deadLink.token}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Set your password");
    await expectInvalidLinkAlert(page);

    await page.goto(`${ADMIN}/set-password#token=${good.link.token}`);
    await expect(page.getByTestId("set-password-error")).toHaveCount(0);
    await expect(page.getByLabel("New password", { exact: true })).toHaveValue("");
    await expect(page.getByLabel("Confirm password", { exact: true })).toHaveValue("");
    await expect.poll(() => page.url()).toBe(`${ADMIN}/set-password`);
    await submitNewPassword(page, newPassword());
    await expect(page).toHaveURL(`${ADMIN}/sign-in`);
  });
  expect(rows(`select 1 from user_credentials where user_id = '${good.id}'`)).toHaveLength(1);
  expect(rows(`select 1 from user_credentials where user_id = '${dead.id}'`)).toHaveLength(0);
});

for (const rightAt of [0, 10]) {
  test(
    `AC3 TC-3-4: 10 wrong and 1 right attempt in parallel after 4 failures: at most one check beyond the 4th failure, a lock only after a 5th failure (right password at position ${rightAt})`,
    { tag: "@slow" },
    async () => {
      const user = await createReadyUser({
        label: `race${rightAt}`,
        role: "builder",
        workspaceId: peopleOps,
      });
      const wrong = `${user.password}-wrong`;
      const api = new ApiSession();
      for (let attempt = 1; attempt <= 4; attempt++) {
        expectDetail(await api.signIn(user.email, wrong), 401, "invalid_credentials");
      }
      expect(dbCredentials(user)).toBe("4|none");

      await reserve("sign-in", 11);
      secretValues.add(user.password);
      testEmails.add(user.email);
      await api.ensureCsrf();
      const results = await Promise.all(
        Array.from({ length: 11 }, (_, index) =>
          api.send("POST", "/api/auth/sign-in", {
            json: { email: user.email, password: index === rightAt ? user.password : wrong },
          }),
        ),
      );
      // Lead ruling: the attempt that takes the 5th slot is still a password check. A lock exists only after
      // a 5th failure; every attempt after the 5th slot answers the generic 401 and at most one check is made
      // beyond the 4 recorded failures. So: at most one success, and only the right-password attempt.
      const successes = results.filter((result) => result.status === 200);
      expect(successes.length, "at most one attempt signs in").toBeLessThanOrEqual(1);
      for (const [index, result] of results.entries()) {
        if (result.status === 200) {
          expect(index, "only the correct password can sign in").toBe(rightAt);
          continue;
        }
        expectDetail(result, 401, "invalid_credentials");
        expect(result.setCookies.filter((line) => line.startsWith("ei_session="))).toEqual([]);
      }
      const locks = auditCount("user.locked_out", "system", user.id);
      const signedIn = auditCount("user.signed_in", `user:${user.id}`, user.id);
      if (successes.length === 1) {
        // The correct attempt took the 5th slot: no lock, one session, one event.
        expect(locks, "no lock when the 5th check was the correct password").toBe(0);
        expect(signedIn).toBe(1);
        expect(sessionCount(user)).toBe(1);
        test
          .info()
          .annotations.push({ type: "race", description: "correct password took the 5th slot" });
      } else {
        // A 5th failure locked the account exactly once; the correct password never got in.
        expect(locks, "locked exactly once").toBe(1);
        expect(signedIn).toBe(0);
        expect(sessionCount(user)).toBe(0);
        expect(Math.abs(lockSeconds(user) - 15 * 60)).toBeLessThan(2);
        // Still locked afterwards: the right password is refused, no new lock event.
        expectDetail(await api.signIn(user.email, user.password), 401, "invalid_credentials");
        expect(auditCount("user.locked_out", "system", user.id)).toBe(1);
        expect(sessionCount(user)).toBe(0);
        test.info().annotations.push({
          type: "race",
          description: "a wrong attempt took the 5th slot and locked",
        });
      }
    },
  );
}

test("AC4 TC-4-4: submitted passwords, emails, cookie values and token secrets are in no API log line and no error response", async () => {
  const logs = apiLogs();
  expect(logs.length, "the API container has logs").toBeGreaterThan(0);
  const lowered = logs.toLowerCase();

  for (const value of secretValues) {
    if (value.length < 8 || resetSecrets.has(value)) continue;
    expect(logs.includes(value), "a secret value of the tests appears in the API logs").toBe(false);
  }
  for (const email of testEmails) {
    expect(
      lowered.includes(email.toLowerCase()),
      "a test user's email appears in the API logs",
    ).toBe(false);
  }
  // The only secret in the logs is the Reset link line after a forgot-password request.
  for (const secret of resetSecrets) {
    const carrying = logs.split("\n").filter((line) => line.includes(secret));
    expect(carrying.length).toBeGreaterThan(0);
    for (const line of carrying) expect(line).toContain("Reset link");
  }
  expect(logs).not.toMatch(/Traceback|ei_ai_migrator|password/i);
  expect(logs).not.toContain("$argon2");

  // Responses: error bodies never echo submitted values; no header carries a secret or a hash.
  for (const result of recordedResults()) {
    const label = `${result.method} ${result.path} -> ${result.status}`;
    if (result.status >= 400) {
      for (const value of result.submitted) {
        if (value.length < 8) continue;
        expect(result.text.includes(value), `${label} echoes a submitted value`).toBe(false);
      }
    }
    expect(result.text, label).not.toContain("$argon2");
    const headerText = Object.entries(result.headers)
      .filter(([name]) => name !== "set-cookie")
      .map(([, value]) => value)
      .join("\n");
    for (const value of secretValues) {
      if (value.length < 8) continue;
      expect(headerText.includes(value), `${label} header leaks a secret`).toBe(false);
    }
    expect(headerText, label).not.toContain("$argon2");
  }
});
