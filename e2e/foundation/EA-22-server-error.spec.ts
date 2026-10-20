// EA-22 (FND-05) round 2: an unexpected server error on the auth action routes answers 500 {"detail":"internal_error"}
// with Cache-Control: no-store and leaves no Traceback or password in the API logs. The failure is
// provoked from outside by stopping the database container for a few seconds (restored in `finally`).
// Tagged @slow because it restarts the database:
//   npm run e2e:full -- e2e/foundation/EA-22-server-error*
import { expect, test } from "@playwright/test";
import {
  ApiSession,
  DEMO_ORG,
  MSG,
  apiLogsSince,
  cleanup,
  compose,
  createReadyUser,
  expectDetail,
  newPassword,
  peopleOpsId,
  reserve,
  signInUi,
  sleep,
  withPage,
} from "../support/ea22";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

test.describe.configure({ timeout: 360_000 });

test.afterAll(() => {
  compose(["start", "db"]); // idempotent safety net
  cleanup();
});

async function waitForApiReady(): Promise<void> {
  const deadline = Date.now() + 120_000;
  for (;;) {
    try {
      if ((await fetch(`${API_URL}/readyz`)).status === 200) return;
    } catch {
      // the API may be restarting its pool; retry
    }
    if (Date.now() > deadline)
      throw new Error("the API did not become ready after the database restart");
    await sleep(1000);
  }
}

test(
  "Server error shape: auth actions answer 500 internal_error with no-store, session checks fail closed (401) and the logs stay clean",
  { tag: "@slow" },
  async ({ browser }) => {
    const workspace = peopleOpsId(); // read before the database is stopped
    const user = await createReadyUser({
      label: "server-error",
      role: "builder",
      workspaceId: workspace,
    });
    const api = new ApiSession();
    await api.ensureCsrf();
    // A live session that must survive the outage.
    const live = new ApiSession();
    expect((await live.signIn(user.email, user.password)).status).toBe(200);
    await reserve("sign-in", 2); // one API call and one UI submit during the outage
    await reserve("forgot");
    await reserve("set-password");
    const started = Date.now();

    const stopped = compose(["stop", "db"]);
    expect(stopped.status, stopped.stderr).toBe(0);
    try {
      // Auth action routes: an unexpected error answers 500 internal_error.
      const actions = [
        await api.send("POST", "/api/auth/sign-in", {
          json: { email: user.email, password: user.password },
        }),
        await api.send("POST", "/api/auth/forgot-password", { json: { email: user.email } }),
        await api.send("POST", "/api/auth/set-password", {
          json: { token: `${DEMO_ORG}.${"F".repeat(43)}`, password: newPassword() },
        }),
        await live.signOut(),
      ];
      for (const call of actions) {
        expectDetail(call, 500, "internal_error");
        expect(call.headers["cache-control"], call.path).toContain("no-store");
        expect(call.text).not.toMatch(/Traceback|postgres|sqlalchemy|psycopg|asyncpg|File "/i);
      }

      // Lead ruling (Q2-1): routes that verify the session fail closed with 401 unauthenticated.
      const sessionChecks = [
        await live.session(),
        await live.workspace(workspace),
        await new ApiSession().send("GET", "/api/auth/session", {
          cookies: { ei_session: `${DEMO_ORG}.${"A".repeat(43)}` },
        }),
      ];
      for (const call of sessionChecks) {
        expectDetail(call, 401, "unauthenticated");
        expect(call.text).not.toMatch(/Traceback|postgres|sqlalchemy|psycopg|asyncpg|File "/i);
      }

      // The browser reports a real 5xx as an unavailable service.
      await withPage(browser, undefined, async (page) => {
        await signInUi(page, user.email, user.password);
        await expect(page.getByTestId("sign-in-error")).toHaveText(MSG.unavailable);
      });
    } finally {
      const restarted = compose(["start", "db"]);
      expect(restarted.status, restarted.stderr).toBe(0);
      await waitForApiReady();
    }

    // The outage did not end the session: it works again once the database is back.
    const after = await live.session();
    expect(after.status, after.text).toBe(200);
    expect(after.json).toMatchObject({ user: { id: user.id } });

    const logs = apiLogsSince((Date.now() - started) / 1000);
    expect(logs).not.toMatch(/Traceback|ei_ai_migrator|password/i);
    expect(logs.toLowerCase()).not.toContain(user.email.toLowerCase());
    expect(logs).not.toContain(user.password);
  },
);
