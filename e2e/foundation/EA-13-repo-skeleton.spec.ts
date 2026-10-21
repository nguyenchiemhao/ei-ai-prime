// EA-13 (SET-03): repo skeleton, one-command local environment and CI pipeline.
// Run against a running stack:  npm run up && npm run seed && npx playwright test e2e/foundation/EA-13-*
// AC3, AC4 and AC5 are pipeline criteria and are verified with commands (no browser).
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { adminUrl } from "../../scripts/lib/admin-url.mjs";

const WIDGET_URL = process.env.WIDGET_URL ?? "http://localhost:3001";
const API_URL = process.env.API_URL ?? "http://localhost:8000";
const ROOT = path.resolve(import.meta.dirname, "..", "..");
// ADMIN_URL, else ADMIN_PORT from the shell or .env (default 3000), like compose.yaml.
const ADMIN_URL = adminUrl(ROOT, process.env);
const SCREENSHOTS = path.join(ROOT, ".work", "EA-13", "screenshots");

const TEXT_PRIMARY = "rgb(22, 24, 29)"; // #16181D  color.text.primary
const BRAND_DEFAULT = "rgb(14, 124, 107)"; // #0E7C6B  color.brand.default

/** Console errors/warnings, page errors and failed or 4xx/5xx requests seen on a page. */
function watch(page: Page) {
  const problems: string[] = [];
  const requests: { url: string; status: number }[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      problems.push(`console.${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("requestfailed", (request) =>
    problems.push(`requestfailed: ${request.url()} ${request.failure()?.errorText ?? ""}`),
  );
  page.on("response", (response) => {
    requests.push({ url: response.url(), status: response.status() });
    if (response.status() >= 400) problems.push(`http ${response.status()}: ${response.url()}`);
  });
  return { problems, requests };
}

type PsRow = { Service: string; State: string; Health: string };

/** `docker compose ps --format json`: a JSON array (Compose 2.20.x) or one object per line (newer). */
function parseComposePs(text: string): PsRow[] {
  const trimmed = text.trim();
  if (trimmed.startsWith("[")) return JSON.parse(trimmed) as PsRow[];
  return trimmed
    .split("\n")
    .filter((line) => line.trim().startsWith("{"))
    .map((line) => JSON.parse(line) as PsRow);
}

function run(file: string, args: string[], env: Record<string, string> = {}) {
  return spawnSync(file, args, {
    cwd: ROOT,
    encoding: "utf8",
    env: { ...process.env, ...env },
    maxBuffer: 64 * 1024 * 1024,
  });
}

test.describe("EA-13 repo skeleton", () => {
  test("AC1: one command starts backend, admin, widget, DB and model; /healthz returns 200", async ({
    request,
  }) => {
    const health = await request.get(`${API_URL}/healthz`);
    expect(health.status()).toBe(200);
    expect(await health.json()).toEqual({ status: "ok" });

    const ready = await request.get(`${API_URL}/readyz`);
    expect(ready.status()).toBe(200);
    expect(await ready.json()).toEqual({
      status: "ok",
      checks: { database: "ok", valkey: "ok" },
    });

    expect((await request.get(ADMIN_URL)).status()).toBe(200);
    expect((await request.get(WIDGET_URL)).status()).toBe(200);
    // The admin nginx proxies /api/ to the API: same-origin call from the browser.
    const proxied = await request.get(`${ADMIN_URL}/api/healthz`);
    expect(proxied.status()).toBe(200);
    expect(await proxied.json()).toEqual({ status: "ok" });

    // db, valkey, model, api, admin and widget are all running and healthy.
    const ps = execFileSync(
      "docker",
      ["compose", "--profile", "core", "--profile", "model", "ps", "--format", "json"],
      { cwd: ROOT, encoding: "utf8" },
    );
    const containers = parseComposePs(ps);
    expect(containers.length).toBeGreaterThanOrEqual(6);
    const byService = Object.fromEntries(containers.map((c) => [c.Service, c]));
    for (const service of ["db", "valkey", "model", "api", "admin", "widget"]) {
      expect(byService[service], `${service} is missing from docker compose ps`).toBeDefined();
      expect(byService[service]?.State).toBe("running");
      expect(byService[service]?.Health).toBe("healthy");
    }

    // The model is really loaded: /v1/models of the (unpublished) model server lists the alias. EA-24: the
    // served id is the alias plus @sha256- and the first 12 hex of the checked file's sha256.
    const models = execFileSync(
      "docker",
      ["compose", "exec", "-T", "model", "curl", "-fsS", "http://localhost:8080/v1/models"],
      { cwd: ROOT, encoding: "utf8" },
    );
    expect(models).toContain('"id":"qwen3-4b-instruct-2507@sha256-3605803b982c"');
  });

  test("AC2: seed runs twice and the admin UI is reachable at http://localhost:3000", async ({
    page,
  }) => {
    // EA-21: the seed now writes rows. A warm-up run makes sure the demo data exists, so the two
    // measured runs below create nothing and print byte-identical output (no one-time links).
    const warmUp = run(process.execPath, ["scripts/dev.mjs", "seed"]);
    expect(warmUp.status, warmUp.stderr).toBe(0);
    const first = run(process.execPath, ["scripts/dev.mjs", "seed"]);
    const second = run(process.execPath, ["scripts/dev.mjs", "seed"]);
    expect(first.status).toBe(0);
    expect(second.status).toBe(0);
    expect(second.stdout).toBe(first.stdout);
    expect(first.stdout).toContain("Mekong Devworks");
    expect(first.stdout).toContain("People Ops");
    expect(first.stdout).toContain("Members: 6");
    // The dry-run note of EA-13 is gone: the seed is real now.
    expect(first.stdout).not.toContain("FND-04");

    // The seed refuses outside local/test environments.
    const production = run("docker", [
      "compose",
      "exec",
      "-T",
      "-e",
      "EI_AI_ENV=production",
      "api",
      "ei-ai",
      "seed",
      "demo",
    ]);
    expect(production.status).toBe(2);

    const seen = watch(page);
    const identityParams = /[?&](user_?id|org_?id|groups?|tenant)=/i;
    // EA-22: the admin root no longer shows the skeleton page (h1 "ei-ai", "API: OK", Language select).
    // In a fresh browser it redirects to the sign-in page; the admin is English only.
    await page.goto(ADMIN_URL);
    await expect(page).toHaveURL(`${ADMIN_URL}/sign-in`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in");
    await expect(page.getByText("Use and manage your organization's assistants.")).toBeVisible();
    await expect(page.getByLabel("Language")).toHaveCount(0);
    await expect(page.getByLabel("Ngôn ngữ")).toHaveCount(0);
    await expect(page.getByText(/API:/)).toHaveCount(0);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await page.screenshot({ path: path.join(SCREENSHOTS, "admin-en.png"), fullPage: true });

    // The admin nginx still proxies /api/ to the API (same origin): healthz answers 200.
    const proxied = await page.request.get(`${ADMIN_URL}/api/healthz`);
    expect(proxied.status()).toBe(200);
    expect(await proxied.json()).toEqual({ status: "ok" });

    expect(seen.requests.filter((r) => identityParams.test(r.url))).toEqual([]);
    // A signed-out visitor is told "unauthenticated" by GET /api/auth/session (401): expected, not a defect.
    expect(
      seen.problems.filter(
        (problem) =>
          !/status of 401/.test(problem) && !/^http 401: .*\/api\/auth\/session$/.test(problem),
      ),
    ).toEqual([]);
  });

  // EA-22: "admin shows API unavailable when the API call fails" is gone with the API status of the
  // skeleton page; the sign-in page shows no API status and reports an unreachable service on sign-in.

  test("AC2: widget greets in Vietnamese or English by browser language", async ({ browser }) => {
    const vi = await browser.newContext({ locale: "vi-VN" });
    const viPage = await vi.newPage();
    const viSeen = watch(viPage);
    await viPage.goto(WIDGET_URL);
    await expect(viPage.getByText("Xin chào! Tôi có thể giúp gì cho bạn hôm nay?")).toBeVisible();
    await expect(viPage.getByRole("log", { name: "Cuộc trò chuyện" })).toHaveAttribute(
      "aria-live",
      "polite",
    );
    await expect(viPage.locator("html")).toHaveAttribute("lang", "vi");
    await viPage.screenshot({ path: path.join(SCREENSHOTS, "widget-vi.png") });
    expect(viSeen.problems).toEqual([]);
    await vi.close();

    const en = await browser.newContext({ locale: "en-US" });
    const enPage = await en.newPage();
    const enSeen = watch(enPage);
    await enPage.goto(WIDGET_URL);
    await expect(enPage.getByText("Hello! How can I help you today?")).toBeVisible();
    await expect(enPage.getByRole("heading", { level: 1 })).toHaveText("ei-ai");
    await expect(enPage.getByRole("log", { name: "Conversation" })).toBeVisible();
    await enPage.screenshot({ path: path.join(SCREENSHOTS, "widget-en.png") });
    expect(enSeen.problems).toEqual([]);
    await en.close();

    // Other languages fall back to English.
    const fr = await browser.newContext({ locale: "fr-FR" });
    const frPage = await fr.newPage();
    await frPage.goto(WIDGET_URL);
    await expect(frPage.getByText("Hello! How can I help you today?")).toBeVisible();
    await fr.close();
  });

  test(
    "AC3: lint, type-check and unit tests of frontend and backend pass and fail the task when broken",
    { tag: "@slow" },
    () => {
      const tasks = [
        "frontend:lint",
        "frontend:typecheck",
        "frontend:test",
        "backend:lint",
        "backend:format",
        "backend:typecheck",
        "backend:test",
      ];
      test.setTimeout(10 * 60_000);
      for (const task of tasks) {
        const result = run(process.execPath, ["scripts/task.mjs", task]);
        expect(result.status, `${task}\n${result.stdout}\n${result.stderr}`.slice(-3000)).toBe(0);
      }
      // An unknown task fails (the runner does not silently succeed).
      expect(
        run(process.execPath, ["scripts/task.mjs", "frontend:does-not-exist"]).status,
      ).not.toBe(0);

      // The workflow calls only these tasks, on pull requests, with no continue-on-error.
      const workflow = fs.readFileSync(path.join(ROOT, ".github/workflows/ci.yml"), "utf8");
      expect(workflow).toMatch(/^on:\s*\n\s+push:/m); // every branch push since 7be5db6
      expect(workflow).not.toContain("continue-on-error");
      for (const task of tasks) {
        const short = task.replace("backend:", "");
        const present = task.startsWith("backend:")
          ? workflow.includes(`npm run backend -- ${short} --native`)
          : workflow.includes(`scripts/task.mjs ${task}`);
        expect(present, `${task} is not called by ci.yml`).toBe(true);
      }
    },
  );

  test("AC4: every CI job is limited to 10 minutes and the jobs run in parallel", () => {
    const workflow = fs.readFileSync(path.join(ROOT, ".github/workflows/ci.yml"), "utf8");
    const jobsSection = workflow.slice(workflow.indexOf("\njobs:"));
    const jobs = [...jobsSection.matchAll(/^ {2}([a-z-]+):\n/gm)].map((m) => m[1]);
    expect(jobs).toEqual(["frontend", "backend", "checks", "tenant-isolation", "stack"]);
    const limits = [...workflow.matchAll(/timeout-minutes:\s*(\d+)/g)].map((m) => Number(m[1]));
    // five jobs plus the 5-minute cap on the tenant-isolation suite step (EA-19)
    expect(limits).toHaveLength(6);
    for (const limit of limits) expect(limit).toBeLessThanOrEqual(10);
    expect(workflow).not.toMatch(/^\s+needs:/m); // parallel
    expect(workflow).toMatch(/cancel-in-progress:\s*true/);
    expect(workflow).toMatch(/cache:\s*npm/);
    expect(workflow).toMatch(/cache:\s*pip/);
  });

  test("AC5: no real secret in the repo and the secret scan fails on a fake token", () => {
    const files = run("git", ["ls-files", "-co", "--exclude-standard"]).stdout.split("\n");
    const envFiles = files.filter((file) => /(^|\/)\.env/.test(file));
    expect(envFiles).toEqual([".env.example"]);

    const compose = fs.readFileSync(path.join(ROOT, "compose.yaml"), "utf8");
    for (const line of compose.split("\n").filter((l) => /PASSWORD\s*[:=]/.test(l))) {
      if (line.trim().startsWith("#")) continue;
      expect(line, "literal password in compose.yaml").toMatch(/\$\{[A-Z_]+:\?/);
    }

    const tests = run(process.execPath, [
      "--test",
      "scripts/checks/secret-scan.test.mjs",
      "scripts/checks/env-example.test.mjs",
    ]);
    expect(tests.status, tests.stdout.slice(-3000)).toBe(0);

    const history = run(process.execPath, ["scripts/task.mjs", "repo:secret-scan"]);
    expect(history.status, `${history.stdout}\n${history.stderr}`.slice(-3000)).toBe(0);

    const workflow = fs.readFileSync(path.join(ROOT, ".github/workflows/ci.yml"), "utf8");
    expect(workflow).toContain("repo:secret-scan");
    expect(workflow).toMatch(/fetch-depth:\s*0/);
  });

  test("AC6: the URLs documented in the README answer and the required sections exist", async ({
    request,
  }) => {
    const readme = fs.readFileSync(path.join(ROOT, "README.md"), "utf8");
    for (const heading of [
      "Prerequisites",
      "Quick start",
      "Seed data",
      "Running tests and checks",
      "Folder structure",
      "Verify acceptance criteria locally",
      "CI",
    ]) {
      expect(readme).toMatch(new RegExp(`^## ${heading}`, "m"));
    }
    // The README documents the default URLs; the requests go to the configured ones.
    for (const [documented, actual] of [
      ["http://localhost:3000", ADMIN_URL],
      ["http://localhost:3001", WIDGET_URL],
    ] as const) {
      expect(readme).toContain(documented);
      expect((await request.get(actual)).status()).toBe(200);
    }
    expect(readme).toContain("http://localhost:8000/healthz");
    expect((await request.get(`${API_URL}/healthz`)).status()).toBe(200);
  });

  test("AC7: admin and widget render with token colours", async ({ page, browser }) => {
    const adminSeen = watch(page);
    await page.goto(ADMIN_URL);
    // EA-22: the root redirects a signed-out visitor to the sign-in page, which uses the same tokens.
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in");
    const admin = await page.evaluate(() => ({
      color: getComputedStyle(document.body).color,
      surface: getComputedStyle(document.documentElement)
        .getPropertyValue("--ei-color-surface-page")
        .trim(),
      token: getComputedStyle(document.documentElement)
        .getPropertyValue("--ei-color-text-primary")
        .trim(),
      font: getComputedStyle(document.body).fontFamily,
    }));
    expect(admin.color).toBe(TEXT_PRIMARY);
    expect(admin.surface.toLowerCase()).toBe("#f7f7f8");
    expect(admin.token.toLowerCase()).toBe("#16181d");
    expect(admin.font).toContain("IBM Plex Sans");
    // IBM Plex Sans is self-hosted and actually loaded (Vietnamese glyphs included).
    await page.evaluate(() => document.fonts.ready);
    expect(
      await page.evaluate(() => document.fonts.check('16px "IBM Plex Sans"', "Tiếng Việt Hà Vũ")),
    ).toBe(true);
    const externalAdmin = adminSeen.requests.filter((r) => !r.url.startsWith(ADMIN_URL));
    expect(externalAdmin).toEqual([]);
    expect(
      adminSeen.requests.filter((r) => /\.(woff2?|css)(\?|$)/.test(r.url)).length,
    ).toBeGreaterThan(0);
    // The signed-out session probe (401 on /api/auth/session) is expected on the sign-in page.
    expect(
      adminSeen.problems.filter(
        (problem) =>
          !/status of 401/.test(problem) && !/^http 401: .*\/api\/auth\/session$/.test(problem),
      ),
    ).toEqual([]);

    const widgetContext = await browser.newContext();
    const widgetPage = await widgetContext.newPage();
    const widgetSeen = watch(widgetPage);
    await widgetPage.goto(WIDGET_URL);
    await expect(widgetPage.getByRole("heading", { level: 1 })).toBeVisible();
    const widget = await widgetPage.evaluate(() => {
      const header = document.querySelector("header");
      return {
        header: header ? getComputedStyle(header).backgroundColor : null,
        token: getComputedStyle(document.documentElement)
          .getPropertyValue("--ei-color-brand-default")
          .trim(),
        color: getComputedStyle(document.body).color,
      };
    });
    expect(widget.header).toBe(BRAND_DEFAULT);
    expect(widget.token.toLowerCase()).toBe("#0e7c6b");
    expect(widget.color).toBe(TEXT_PRIMARY);
    await widgetPage.evaluate(() => document.fonts.ready);
    expect(widgetSeen.requests.filter((r) => !r.url.startsWith(WIDGET_URL))).toEqual([]);
    expect(widgetSeen.problems).toEqual([]);
    await widgetContext.close();

    // No hard-coded colour in the app sources: the check from the runner bites on the real tree.
    const noHex = run(process.execPath, ["scripts/checks/no-hex-colours.mjs"]);
    expect(noHex.status, noHex.stdout + noHex.stderr).toBe(0);
  });
});
