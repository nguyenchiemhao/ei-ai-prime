// EA-22 (FND-05): shared helpers of the admin sign-in and workspace-shell specs.
// Black-box only: the Platform Operator CLI (docker compose exec api ei-ai ...), psql as the database
// superuser, the admin origin (UI + /api proxy) and the API logs. Nothing here reads product source.
import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {
  expect,
  request as pwRequest,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { adminUrl } from "../../scripts/lib/admin-url.mjs";

export const ROOT = path.resolve(import.meta.dirname, "..", "..");
export const ADMIN = adminUrl(ROOT, process.env);
export const ADMIN_ORIGIN = new URL(ADMIN).origin;
export const DEMO_ORG = "0192a000-0000-7000-8000-00000000ea21";
export const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
export const SCREENSHOTS = path.join(ROOT, ".work", "EA-22", "screenshots");

export const MSG = {
  invalid: "Invalid email or password",
  tooMany: "Too many attempts. Wait a minute and try again.",
  unavailable: "The service is unavailable. Try again later.",
  linkInvalid: "This link is invalid or has expired. Ask your organization admin for a new link.",
  passwordSet: "Your password is set. Sign in to continue.",
  forgotConfirmation: "If an account exists for this email, a reset link has been sent.",
} as const;

/** Sidebar groups in the order of the contract: group heading, then [label, slug]. */
export const NAV_GROUPS: { group: string; items: [string, string][] }[] = [
  { group: "Overview", items: [["Dashboard", "dashboard"]] },
  {
    group: "Build",
    items: [
      ["Assistants", "assistants"],
      ["Knowledge", "knowledge"],
      ["Answer Scripts", "answer-scripts"],
      ["Glossary", "glossary"],
      ["Skills & Connectors", "skills"],
    ],
  },
  { group: "Deploy", items: [["Channels", "channels"]] },
  {
    group: "Review",
    items: [
      ["Conversations", "conversations"],
      ["Unanswered", "unanswered"],
    ],
  },
  {
    group: "Settings",
    items: [
      ["Members & roles", "members"],
      ["Organization", "organization"],
    ],
  },
];

// ---------------------------------------------------------------------------------------------
// Process helpers
// ---------------------------------------------------------------------------------------------

export type Run = { status: number | null; stdout: string; stderr: string };

function spawn(file: string, args: string[], input?: string): Run {
  const result = spawnSync(file, args, {
    cwd: ROOT,
    encoding: "utf8",
    input,
    maxBuffer: 64 * 1024 * 1024,
  });
  return { status: result.status, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
}

/** `docker compose exec -T api ei-ai <args>` */
export function cli(args: string[]): Run {
  return spawn("docker", ["compose", "exec", "-T", "api", "ei-ai", ...args]);
}

/** `docker compose <args>` in the repository root. */
export function compose(args: string[]): Run {
  return spawn("docker", ["compose", ...args]);
}

/** SQL as the database superuser (bypasses RLS); returns trimmed stdout. */
export function sql(statement: string): string {
  const result = spawn(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ei_ai", "-X", "-At", "-q"],
    statement,
  );
  expect(result.status, result.stderr).toBe(0);
  return result.stdout.trim();
}

export function rows(statement: string): string[] {
  const out = sql(statement);
  return out === "" ? [] : out.split("\n");
}

export function lines(text: string): string[] {
  return text.split(/\r?\n/).filter((line) => line.trim().length > 0);
}

export function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export function randomSuffix(): string {
  return randomBytes(4).toString("hex");
}

/** API log lines of the last `seconds` seconds (plus a margin for clock skew). */
export function apiLogsSince(seconds: number): string {
  return spawn("docker", [
    "compose",
    "logs",
    "--no-color",
    "--since",
    `${Math.ceil(seconds) + 5}s`,
    "api",
  ]).stdout;
}

export function apiLogs(): string {
  return spawn("docker", ["compose", "logs", "--no-color", "api"]).stdout;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// ---------------------------------------------------------------------------------------------
// Rate-limit budget: 30 sign-in POSTs per minute per client IP, shared by every spec and worker.
// The stamps live in a file so a restarted worker (after a failure) still knows the window.
// ---------------------------------------------------------------------------------------------

export type BudgetKind = "sign-in" | "forgot" | "set-password";
const BUDGET_FILE = path.join(ROOT, ".work", "EA-22", "rate-budget.json");
const WINDOW_MS = 63_000; // 60 s window plus a margin for clock skew between the host and the API
const CAP = 26; // 30 per minute minus room for exploratory clicks

function readStamps(): Record<BudgetKind, number[]> {
  try {
    const parsed = JSON.parse(fs.readFileSync(BUDGET_FILE, "utf8")) as Record<string, number[]>;
    return {
      "sign-in": parsed["sign-in"] ?? [],
      forgot: parsed.forgot ?? [],
      "set-password": parsed["set-password"] ?? [],
    };
  } catch {
    return { "sign-in": [], forgot: [], "set-password": [] };
  }
}

function writeStamps(stamps: Record<BudgetKind, number[]>): void {
  fs.mkdirSync(path.dirname(BUDGET_FILE), { recursive: true });
  fs.writeFileSync(BUDGET_FILE, JSON.stringify(stamps));
}

/** Waits until `count` more POSTs of this kind fit in the per-minute budget, then books them. */
export async function reserve(kind: BudgetKind, count = 1): Promise<void> {
  for (;;) {
    const now = Date.now();
    const stamps = readStamps();
    const live = stamps[kind].filter((stamp) => now - stamp < WINDOW_MS).sort((a, b) => a - b);
    if (live.length + count <= CAP) {
      stamps[kind] = [...live, ...Array.from({ length: count }, () => now)];
      writeStamps(stamps);
      return;
    }
    const oldest = live[0] ?? now;
    await sleep(Math.max(250, oldest + WINDOW_MS - now));
  }
}

/** Waits until no POST of this kind was made in the last minute (used before the rate-limit test). */
export async function waitForQuietWindow(kind: BudgetKind): Promise<void> {
  for (;;) {
    const now = Date.now();
    const live = readStamps()[kind].filter((stamp) => now - stamp < WINDOW_MS);
    if (live.length === 0) return;
    await sleep(Math.max(250, Math.max(...live) + WINDOW_MS - now));
  }
}

/** Books POSTs that were made outside `reserve` (the rate-limit test), so later specs wait. */
export function bookPosts(kind: BudgetKind, count: number): void {
  const stamps = readStamps();
  const now = Date.now();
  stamps[kind] = [...stamps[kind], ...Array.from({ length: count }, () => now)];
  writeStamps(stamps);
}

// ---------------------------------------------------------------------------------------------
// API client: explicit cookie jar and CSRF header, no hidden browser behaviour.
// ---------------------------------------------------------------------------------------------

export type ApiResult = {
  method: string;
  path: string;
  status: number;
  headers: Record<string, string>;
  setCookies: string[];
  text: string;
  json: unknown;
  /** Strings that were submitted (passwords, emails, token secrets, cookie values). */
  submitted: string[];
};

export type SendOptions = {
  json?: unknown;
  rawBody?: string;
  headers?: Record<string, string>;
  /** "jar" (default): X-CSRF-Token from the jar's ei_csrf; "none": no header; else a literal value. */
  csrf?: "jar" | "none" | string;
  /** Origin header; default the admin origin for non-GET; null sends none. */
  origin?: string | null;
  /** Replaces the jar cookies for this call. */
  cookies?: Record<string, string>;
};

const allResults: ApiResult[] = [];
/** Every API response seen by `ApiSession` in this worker (used by the leak sweep). */
export function recordedResults(): ApiResult[] {
  return allResults;
}

/** Secret values created by the tests: passwords, cookie values, one-time token secrets. */
export const secretValues = new Set<string>();
/** Emails of the test users (must not appear in the API logs or in error responses). */
export const testEmails = new Set<string>();
/** Token secrets that the API itself prints (the `Reset link` line after a forgot-password request). */
export const resetSecrets = new Set<string>();

export function parseSetCookie(line: string): { name: string; value: string; attrs: string[] } {
  const [pair = "", ...attrs] = line.split(";").map((part) => part.trim());
  const eq = pair.indexOf("=");
  return {
    name: eq < 0 ? pair : pair.slice(0, eq),
    value: eq < 0 ? "" : pair.slice(eq + 1),
    attrs,
  };
}

export class ApiSession {
  readonly jar = new Map<string, string>();

  static fromCookies(cookies: { name: string; value: string }[]): ApiSession {
    const session = new ApiSession();
    for (const cookie of cookies) session.jar.set(cookie.name, cookie.value);
    return session;
  }

  get sessionCookie(): string | undefined {
    return this.jar.get("ei_session");
  }

  get csrfCookie(): string | undefined {
    return this.jar.get("ei_csrf");
  }

  async send(method: string, apiPath: string, options: SendOptions = {}): Promise<ApiResult> {
    const headers: Record<string, string> = { ...options.headers };
    const cookies = options.cookies ?? Object.fromEntries(this.jar);
    if (Object.keys(cookies).length > 0) {
      headers.cookie = Object.entries(cookies)
        .map(([name, value]) => `${name}=${value}`)
        .join("; ");
    }
    const changesState = method !== "GET" && method !== "HEAD";
    if (changesState) {
      const csrf = options.csrf ?? "jar";
      if (csrf === "jar") {
        const token = this.jar.get("ei_csrf");
        if (token) headers["x-csrf-token"] = token;
      } else if (csrf !== "none") {
        headers["x-csrf-token"] = csrf;
      }
      const origin = options.origin === undefined ? ADMIN_ORIGIN : options.origin;
      if (origin !== null) headers.origin = origin;
    }
    let data: string | undefined;
    if (options.rawBody !== undefined) {
      data = options.rawBody;
      headers["content-type"] = "application/json";
    } else if (options.json !== undefined) {
      data = JSON.stringify(options.json);
      headers["content-type"] = "application/json";
    }

    const context = await pwRequest.newContext({ baseURL: ADMIN });
    try {
      const response = await context.fetch(`${ADMIN}${apiPath}`, {
        method,
        headers,
        data,
        maxRedirects: 0,
        failOnStatusCode: false,
      });
      const text = await response.text();
      let json: unknown = null;
      try {
        json = JSON.parse(text);
      } catch {
        json = null;
      }
      const setCookies = response
        .headersArray()
        .filter((header) => header.name.toLowerCase() === "set-cookie")
        .map((header) => header.value);
      const submitted: string[] = [];
      if (options.json && typeof options.json === "object") {
        for (const value of Object.values(options.json as Record<string, unknown>)) {
          if (typeof value !== "string" || value === "") continue;
          submitted.push(value);
          const dot = value.indexOf(".");
          if (dot > 0) submitted.push(value.slice(dot + 1)); // the secret part of a token
        }
      }
      for (const value of Object.values(cookies)) submitted.push(value);
      const result: ApiResult = {
        method,
        path: apiPath,
        status: response.status(),
        headers: response.headers(),
        setCookies,
        text,
        json,
        submitted,
      };
      for (const line of setCookies) {
        const cookie = parseSetCookie(line);
        const expired =
          cookie.attrs.some((attr) => /^max-age=0$/i.test(attr)) || cookie.value === "";
        if (expired) this.jar.delete(cookie.name);
        else {
          this.jar.set(cookie.name, cookie.value);
          if (cookie.name === "ei_session" || cookie.name === "ei_csrf") {
            secretValues.add(cookie.value);
          }
        }
      }
      allResults.push(result);
      return result;
    } finally {
      await context.dispose();
    }
  }

  /** GET /api/auth/csrf when the jar has no CSRF cookie yet. */
  async ensureCsrf(): Promise<void> {
    if (this.jar.has("ei_csrf")) return;
    const result = await this.send("GET", "/api/auth/csrf");
    expect(result.status).toBe(200);
  }

  /** Books one sign-in in the budget, then POST /api/auth/sign-in with a valid CSRF token. */
  async signIn(email: string, password: string): Promise<ApiResult> {
    await reserve("sign-in");
    await this.ensureCsrf();
    secretValues.add(password);
    testEmails.add(email);
    return this.send("POST", "/api/auth/sign-in", { json: { email, password } });
  }

  async forgotPassword(email: string): Promise<ApiResult> {
    await reserve("forgot");
    await this.ensureCsrf();
    testEmails.add(email);
    return this.send("POST", "/api/auth/forgot-password", { json: { email } });
  }

  async signOut(): Promise<ApiResult> {
    await this.ensureCsrf();
    return this.send("POST", "/api/auth/sign-out");
  }

  /** Books one POST in the set-password bucket (30 per minute per IP), then POST /auth/set-password. */
  async setPassword(token: string, password: string): Promise<ApiResult> {
    await reserve("set-password");
    await this.ensureCsrf();
    secretValues.add(password);
    const dot = token.indexOf(".");
    const secretPart = dot < 0 ? token : token.slice(dot + 1);
    if (/^[A-Za-z0-9_-]{43}$/.test(secretPart)) secretValues.add(secretPart);
    return this.send("POST", "/api/auth/set-password", { json: { token, password } });
  }

  session(): Promise<ApiResult> {
    return this.send("GET", "/api/auth/session");
  }

  workspace(id: string): Promise<ApiResult> {
    return this.send("GET", `/api/workspaces/${id}`);
  }
}

/** Header names of a response, lowercased and sorted, without the per-request ones. */
export function headerNames(result: ApiResult): string[] {
  return Object.keys(result.headers)
    .filter((name) => !["date", "set-cookie"].includes(name))
    .sort();
}

/** "Same answer": status, body and header names (a user must not tell which case it was). */
export function expectSameAnswer(actual: ApiResult, expected: ApiResult, label: string): void {
  expect(actual.status, `${label}: status`).toBe(expected.status);
  expect(actual.text, `${label}: body`).toBe(expected.text);
  expect(headerNames(actual), `${label}: header names`).toEqual(headerNames(expected));
}

export function expectDetail(result: ApiResult, status: number, detail: string): void {
  expect(result.status, `${result.method} ${result.path}: ${result.text}`).toBe(status);
  expect(result.json).toEqual({ detail });
}

// ---------------------------------------------------------------------------------------------
// Test data through the Platform Operator CLI
// ---------------------------------------------------------------------------------------------

const RUN_ID = randomSuffix();
export const RUN = RUN_ID;
const LINK_LINE = new RegExp(
  `^Set-password link \\(valid 24 h, shown once\\): ${escapeRegExp(ADMIN)}/set-password#token=(${UUID})\\.([A-Za-z0-9_-]{43})$`,
);

export type Link = { orgId: string; secret: string; token: string };

export function parseLink(line: string | undefined): Link {
  const match = LINK_LINE.exec(line ?? "");
  expect(match, `not a set-password link line: ${line}`).not.toBeNull();
  const orgId = match?.[1] as string;
  const secret = match?.[2] as string;
  secretValues.add(secret);
  return { orgId, secret, token: `${orgId}.${secret}` };
}

export type QaUser = {
  id: string;
  email: string;
  name: string;
  password: string;
  /** The newest unused set-password link. */
  link: Link;
};

export function newPassword(): string {
  return `Qa22-${randomBytes(9).toString("base64url")}!`;
}

export function peopleOpsId(): string {
  const id = rows(
    `select id from workspaces where org_id = '${DEMO_ORG}' and name = 'People Ops'`,
  )[0];
  expect(id, "precondition: the demo seed created Workspace People Ops").toBeTruthy();
  return id as string;
}

/** Invites a user (no password yet). Emails and names are unique to this run. */
export function inviteUser(options: {
  label: string;
  role: string;
  workspaceId?: string;
  name?: string;
}): QaUser {
  const email = `qa22.${options.label}.${RUN_ID}@mekongdevworks.example`;
  const name = options.name ?? `QA22 ${options.label} ${RUN_ID}`;
  const args = ["user", "invite", "--org", DEMO_ORG, "--email", email, "--role", options.role];
  if (options.workspaceId) args.push("--workspace", options.workspaceId);
  args.push("--name", name);
  const run = cli(args);
  expect(run.status, run.stderr).toBe(0);
  const out = lines(run.stdout);
  expect(out).toHaveLength(2);
  const match = new RegExp(`^User invited: (${UUID}) \\(.+\\) roles: .+$`).exec(out[0] as string);
  expect(match, out[0]).not.toBeNull();
  testEmails.add(email);
  return {
    id: match?.[1] as string,
    email,
    name,
    password: "",
    link: parseLink(out[1]),
  };
}

/** `ei-ai user link`: a new link; older unused links of the user stop working. */
export function issueLink(user: QaUser): Link {
  const run = cli(["user", "link", "--org", DEMO_ORG, "--email", user.email]);
  expect(run.status, run.stderr).toBe(0);
  const out = lines(run.stdout);
  expect(out).toHaveLength(1);
  user.link = parseLink(out[0]);
  return user.link;
}

/** Invite + set a password through the API (no sign-in, so no rate-limit budget). */
export async function createReadyUser(options: {
  label: string;
  role: string;
  workspaceId?: string;
  name?: string;
  password?: string;
}): Promise<QaUser> {
  const user = inviteUser(options);
  user.password = options.password ?? newPassword();
  const api = new ApiSession();
  const result = await api.setPassword(user.link.token, user.password);
  expect(result.status, result.text).toBe(204);
  return user;
}

export function createWorkspace(name: string): string {
  const run = cli(["workspace", "create", "--org", DEMO_ORG, "--name", name]);
  expect(run.status, run.stderr).toBe(0);
  const match = new RegExp(`^Workspace created: (${UUID}) \\(.+\\)$`).exec(
    lines(run.stdout)[0] as string,
  );
  expect(match, run.stdout).not.toBeNull();
  return match?.[1] as string;
}

export function addMember(workspaceId: string, user: QaUser, role: string): void {
  const run = cli([
    "workspace",
    "add-member",
    "--org",
    DEMO_ORG,
    "--workspace",
    workspaceId,
    "--email",
    user.email,
    "--role",
    role,
  ]);
  expect(run.status, run.stderr).toBe(0);
  expect(lines(run.stdout)).toEqual([
    expect.stringMatching(
      new RegExp(`^Workspace member added: ${user.id} \\(.+\\) role: ${role}$`),
    ),
  ]);
}

export type ForeignOrg = {
  orgId: string;
  workspaceId: string;
  workspaceName: string;
  ownerId: string;
  ownerEmail: string;
  link: Link;
  suffix: string;
};

/** A second Organization with its own Workspace and owner (for the cross-tenant attacks). */
export function createForeignOrg(): ForeignOrg {
  const suffix = RUN_ID;
  const workspaceName = `QA22 Foreign ${suffix}`;
  const ownerEmail = `owner.qa22.${suffix}@example.com`;
  const run = cli([
    "org",
    "create",
    "--name",
    `QA EA-22 ${suffix}`,
    "--owner",
    ownerEmail,
    "--workspace-name",
    workspaceName,
  ]);
  expect(run.status, run.stderr).toBe(0);
  const out = lines(run.stdout);
  expect(out).toHaveLength(4);
  const org = new RegExp(`^Organization created: (${UUID}) `).exec(out[0] as string);
  const workspace = new RegExp(`^Workspace created: (${UUID}) `).exec(out[1] as string);
  const owner = new RegExp(`^Org Owner created: (${UUID}) `).exec(out[2] as string);
  expect(org && workspace && owner, run.stdout).toBeTruthy();
  testEmails.add(ownerEmail);
  return {
    orgId: org?.[1] as string,
    workspaceId: workspace?.[1] as string,
    workspaceName,
    ownerId: owner?.[1] as string,
    ownerEmail,
    link: parseLink(out[3]),
    suffix,
  };
}

/** Removes everything this run created, as the superuser, children first (RLS is never altered). */
export function cleanup(): void {
  const quoted = (values: string[]) => values.map((value) => `'${value}'`).join(", ");
  const users = rows(
    `select id from users where org_id = '${DEMO_ORG}' and email like 'qa22.%@mekongdevworks.example'`,
  );
  const workspaces = rows(
    `select id from workspaces where org_id = '${DEMO_ORG}' and name like 'QA22 %'`,
  );
  const statements: string[] = [];
  if (users.length > 0) {
    const ids = quoted(users);
    const actors = quoted(users.map((id) => `user:${id}`));
    statements.push(
      `delete from admin_sessions where org_id = '${DEMO_ORG}' and user_id in (${ids});`,
      `delete from user_credentials where org_id = '${DEMO_ORG}' and user_id in (${ids});`,
      `delete from audit_events where org_id = '${DEMO_ORG}' and (target_id::text in (${ids}) or actor in (${actors}));`,
      `delete from set_password_tokens where org_id = '${DEMO_ORG}' and user_id in (${ids});`,
      `delete from workspace_memberships where org_id = '${DEMO_ORG}' and user_id in (${ids});`,
      `delete from memberships where org_id = '${DEMO_ORG}' and user_id in (${ids});`,
      `delete from users where org_id = '${DEMO_ORG}' and id in (${ids});`,
    );
  }
  if (workspaces.length > 0) {
    statements.push(
      `delete from audit_events where org_id = '${DEMO_ORG}' and target_id::text in (${quoted(workspaces)});`,
      `delete from workspaces where org_id = '${DEMO_ORG}' and id in (${quoted(workspaces)});`,
    );
  }
  if (statements.length > 0) sql(`begin; ${statements.join(" ")} commit;`);

  const tables = [
    "admin_sessions",
    "user_credentials",
    "audit_events",
    "set_password_tokens",
    "workspace_memberships",
    "memberships",
    "users",
    "workspaces",
  ];
  const orgs = rows(`select id from organizations where name like 'QA EA-22 %'`);
  for (const orgId of orgs) {
    const byOrg = tables.map((table) => `delete from ${table} where org_id = '${orgId}';`);
    sql(`begin; ${byOrg.join(" ")} delete from organizations where id = '${orgId}'; commit;`);
  }
}

// ---------------------------------------------------------------------------------------------
// Browser helpers
// ---------------------------------------------------------------------------------------------

export type StorageState = Awaited<ReturnType<BrowserContext["storageState"]>>;

export const DESKTOP = { width: 1440, height: 860 };

/** Runs `fn` in a fresh browser context (optionally signed in through a saved storage state). */
export async function withPage<T>(
  browser: Browser,
  state: StorageState | undefined,
  fn: (page: Page, context: BrowserContext) => Promise<T>,
): Promise<T> {
  const context = await browser.newContext({ viewport: DESKTOP, storageState: state });
  try {
    return await fn(await context.newPage(), context);
  } finally {
    await context.close();
  }
}

/** Fills the sign-in form and clicks `Sign in` (books one sign-in in the budget). */
export async function signInUi(page: Page, email: string, password: string): Promise<void> {
  await reserve("sign-in");
  testEmails.add(email);
  secretValues.add(password);
  await page.goto("/sign-in");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Console errors/warnings, page errors and failed or 4xx/5xx requests seen on a page. */
export function watch(page: Page) {
  const problems: string[] = [];
  const requests: { url: string; status: number; method: string }[] = [];
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
    requests.push({
      url: response.url(),
      status: response.status(),
      method: response.request().method(),
    });
    if (response.status() >= 400) problems.push(`http ${response.status()}: ${response.url()}`);
  });
  return { problems, requests };
}

/** Drops the 401 answers a signed-out visitor (or a wrong password) legitimately causes. */
export function withoutExpected401(problems: string[]): string[] {
  return problems.filter(
    (problem) =>
      !/status of 401|^http 401: /.test(problem) && !/\/api\/auth\/session/.test(problem),
  );
}

/** WCAG contrast ratio of the text colour of an element against its effective background. */
export async function contrastRatio(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return Number.NaN;
    const rgba = (css: string): number[] => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = "#000000";
      context.fillStyle = css;
      context.fillRect(0, 0, 1, 1);
      const data = context.getImageData(0, 0, 1, 1).data;
      return [data[0] ?? 0, data[1] ?? 0, data[2] ?? 0, (data[3] ?? 0) / 255];
    };
    const layers: number[][] = [];
    for (let node: Element | null = element; node; node = node.parentElement) {
      const colour = rgba(getComputedStyle(node).backgroundColor);
      if ((colour[3] ?? 0) > 0) {
        layers.push(colour);
        if ((colour[3] ?? 0) >= 1) break;
      }
    }
    let background = [255, 255, 255];
    for (const layer of layers.reverse()) {
      const alpha = layer[3] ?? 1;
      background = background.map(
        (value, index) => (layer[index] ?? 0) * alpha + value * (1 - alpha),
      );
    }
    const text = rgba(getComputedStyle(element).color);
    const textAlpha = text[3] ?? 1;
    const foreground = text
      .slice(0, 3)
      .map((value, index) => value * textAlpha + (background[index] ?? 0) * (1 - textAlpha));
    const luminance = (rgb: number[]) => {
      const [r = 0, g = 0, b = 0] = rgb.map((value) => {
        const scaled = value / 255;
        return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const light = Math.max(luminance(foreground), luminance(background));
    const dark = Math.min(luminance(foreground), luminance(background));
    return (light + 0.05) / (dark + 0.05);
  });
}

/** Height in CSS pixels of a visible element. */
export async function heightOf(locator: Locator): Promise<number> {
  const box = await locator.boundingBox();
  expect(box, "element is not rendered").not.toBeNull();
  return box?.height ?? 0;
}
