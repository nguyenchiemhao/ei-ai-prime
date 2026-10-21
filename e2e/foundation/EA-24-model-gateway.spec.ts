// EA-24 (FND-07): OpenAI-compatible Model Gateway with a version-pinned model catalog. Profile api, no browser.
// The outside surface is the Platform Operator CLI (`ei-ai model add`, `ei-ai model try`) run in the api
// container, the database (psql in the db container) and the model server. Runs against a running, migrated
// and seeded stack WITH the model (no --no-model):
//   npm run up && npm run seed && npx playwright test e2e/foundation/EA-24-*
// Every test that creates Organizations uses a unique suffix in the names and deletes its rows afterwards
// as the database superuser, children first (RLS is never altered).
import { spawn as spawnAsync, spawnSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const DEMO_ORG = "0192a000-0000-7000-8000-00000000ea21";
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const LOCAL_REF = "qwen3-4b-instruct-2507@2026.10";
const EMBEDDING_REF = "bge-m3@2026.10";
const RERANK_REF = "bge-reranker-v2-m3@2026.10";
const CLOUD_REF = "gpt-4.1-2025-04-14@2025.04";
const CHAT_DIGEST = "sha256:3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597";
const CHAT_SOURCE =
  "unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf";
const SERVED_ID = "qwen3-4b-instruct-2507@sha256-3605803b982c";
const LEAKS = /Key \(|Traceback|SELECT|INSERT|postgresql:\/\/|https?:\/\//;
const DEAD_LOCAL = "http://127.0.0.1:9/v1";
const DEAD_PROXY = "http://127.0.0.1:9";

// Same regex as the contract (plan section 6).
const DONE =
  /^done: model=(\S+)@(\S+) digest=(sha256:[0-9a-f]{12}|none) prompt_tokens=([1-9]\d*) completion_tokens=([1-9]\d*) attempts=([12]) first_token_ms=(\d+) total_ms=(\d+)$/;

const MESSAGES = {
  notFound: (ref: string) =>
    `error: MODEL_NOT_FOUND: no chat model ${ref} in this Organization's catalog`,
  retired: (ref: string) => `error: MODEL_RETIRED: model ${ref} is retired`,
  pinned: (ref: string) => `error: PINNED_VERSION_UNAVAILABLE: pinned version unavailable: ${ref}`,
  unavailable: (ref: string) => `error: MODEL_UNAVAILABLE: model ${ref} is unavailable`,
  cloudDisabled: "error: CLOUD_DISABLED: cloud models are off for this Organization",
  cloudNotConfigured: "error: CLOUD_NOT_CONFIGURED: cloud model calls are not configured",
  orgId: "error: --org must be an Organization id (UUID)",
  modelRef: "error: --model must be <model_id>@<version>",
  orgNotFound: "error: Organization not found",
  unknownModel: (ref: string) =>
    `error: unknown model ${ref}; known: bge-m3@2026.10, bge-reranker-v2-m3@2026.10, qwen3-4b-instruct-2507@2026.10`,
};

const COLUMNS = [
  "id",
  "org_id",
  "kind",
  "display_name",
  "model_id",
  "version",
  "digest",
  "source_revision",
  "deployment",
  "provider",
  "vietnamese_quality",
  "vietnamese_quality_measured",
  "tool_use",
  "context_window",
  "speed",
  "status",
  "retirement_date",
  "created_at",
];

// Children first (model_catalog and audit_events reference organizations).
const PURGE_TABLES = [
  "audit_events",
  "model_catalog",
  "admin_sessions",
  "user_credentials",
  "set_password_tokens",
  "workspace_memberships",
  "memberships",
  "users",
  "workspaces",
];

function findRoot(): string {
  let dir = import.meta.dirname;
  while (!fs.existsSync(path.join(dir, "compose.yaml"))) {
    const parent = path.dirname(dir);
    if (parent === dir) throw new Error("repository root (compose.yaml) not found");
    dir = parent;
  }
  return dir;
}

const ROOT = findRoot();

type Run = { status: number | null; stdout: string; stderr: string };

function spawn(file: string, args: string[], input?: string): Run {
  const result = spawnSync(file, args, {
    cwd: ROOT,
    encoding: "utf8",
    input,
    maxBuffer: 64 * 1024 * 1024,
  });
  return { status: result.status, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
}

function envArgs(env: Record<string, string>): string[] {
  return Object.entries(env).flatMap(([key, value]) => ["-e", `${key}=${value}`]);
}

/** `docker compose exec -T api ei-ai <args>`; `env` entries become `-e KEY=VALUE`. */
function cli(args: string[], env: Record<string, string> = {}): Run {
  return spawn("docker", ["compose", "exec", "-T", ...envArgs(env), "api", "ei-ai", ...args]);
}

/** `npm run seed` without npm: the same script the EA-13 spec uses. */
function seed(): Run {
  return spawn(process.execPath, ["scripts/dev.mjs", "seed"]);
}

/** SQL through psql in the db container as `role`; never asserts the exit code. */
function psql(role: string, statement: string, extra: string[] = []): Run {
  return spawn(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", role, "-d", "ei_ai", "-X", "-At", ...extra],
    statement,
  );
}

/** Read-only, setup or cleanup SQL as the database superuser (bypasses RLS); returns trimmed stdout. */
function sql(statement: string): string {
  const result = spawn(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ei_ai", "-X", "-At", "-q"],
    statement,
  );
  expect(result.status, result.stderr).toBe(0);
  return result.stdout.trim();
}

function rows(statement: string): string[] {
  const out = sql(statement);
  return out === "" ? [] : out.split("\n");
}

function lines(text: string): string[] {
  return text.split(/\r?\n/).filter((line) => line.trim().length > 0);
}

function suffix(): string {
  return randomBytes(4).toString("hex");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function purgeOrg(orgId: string): void {
  expect(orgId).toMatch(new RegExp(`^${UUID}$`));
  const byOrg = PURGE_TABLES.map((table) => `delete from ${table} where org_id = '${orgId}';`);
  sql(`begin; ${byOrg.join(" ")} delete from organizations where id = '${orgId}'; commit;`);
}

function purgeBySuffix(sfx: string): void {
  const ids = rows(`select id from organizations where position('${sfx}' in lower(name)) > 0`);
  for (const id of ids) purgeOrg(id);
}

/** Creates a fresh Organization with `ei-ai org create`; returns its id. */
function createOrg(sfx: string, label = ""): string {
  const run = cli([
    "org",
    "create",
    "--name",
    `QA EA-24 ${label}${sfx}`,
    "--owner",
    `owner.${label}${sfx}@example.com`,
  ]);
  expect(run.status, run.stderr).toBe(0);
  const match = new RegExp(`^Organization created: (${UUID}) `).exec(lines(run.stdout)[0] ?? "");
  expect(match, run.stdout).not.toBeNull();
  return match?.[1] as string;
}

function modelAdd(orgId: string, ref: string): Run {
  return cli(["model", "add", "--org", orgId, "--model", ref]);
}

function modelTry(
  orgId: string,
  ref: string,
  extra: string[] = [],
  env: Record<string, string> = {},
): Run {
  return cli(["model", "try", "--org", orgId, "--model", ref, ...extra], env);
}

/** Inserts a cloud chat row as postgres (the CLI adds only manifest models); returns its id. */
function insertCloudRow(orgId: string, ref = CLOUD_REF): string {
  const [modelId, version] = ref.split("@") as [string, string];
  const id = sql(
    `insert into model_catalog (org_id, kind, display_name, model_id, version, deployment, provider)
     values ('${orgId}', 'chat', 'QA cloud', '${modelId}', '${version}', 'cloud', 'openai') returning id;`,
  );
  expect(id).toMatch(new RegExp(`^${UUID}$`));
  return id;
}

function setAllowCloud(orgId: string, allow: boolean): void {
  sql(`update organizations set allow_cloud_models = ${allow} where id = '${orgId}';`);
}

function modelEvents(orgId: string): string[] {
  return rows(
    `select actor || '|' || action || '|' || target_type || '|' || target_id
     from audit_events where org_id = '${orgId}' and action like 'model.%' order by action, target_id`,
  );
}

function catalogRefs(orgId: string): string[] {
  return rows(
    `select model_id || '@' || version from model_catalog where org_id = '${orgId}' order by 1`,
  );
}

function expectCliError(result: Run, message: string, status = 1): void {
  expect(result.stdout.trim(), "stdout of a failed command").toBe("");
  expect(lines(result.stderr)).toEqual([message]);
  expect(result.status).toBe(status);
  expect(result.stderr).not.toMatch(LEAKS);
}

/** Usage-style error (exit 2): the exact message is on stderr, stdout is empty, nothing leaks. */
function expectArgError(result: Run, message: string): void {
  expect(result.status).toBe(2);
  expect(result.stdout.trim()).toBe("");
  expect(lines(result.stderr)).toContain(message);
  expect(result.stderr).not.toMatch(/Traceback|SELECT|INSERT|postgresql:\/\//);
}

type Done = {
  model: string;
  version: string;
  digest: string;
  promptTokens: number;
  completionTokens: number;
  attempts: number;
  firstTokenMs: number;
  totalMs: number;
};

/** Checks a successful `model try` and returns the streamed text and the parsed `done:` line. */
function expectTrySuccess(run: Run): { text: string; done: Done } {
  expect(run.status, run.stderr).toBe(0);
  expect(run.stderr, "stderr of a successful call (no log line, no traceback)").toBe("");
  const out = run.stdout.replace(/\r\n/g, "\n").replace(/\n+$/, "").split("\n");
  const last = out[out.length - 1] ?? "";
  const match = DONE.exec(last);
  expect(match, `last line is not a done: line: ${last}`).not.toBeNull();
  const g = match as RegExpExecArray;
  const done: Done = {
    model: g[1] as string,
    version: g[2] as string,
    digest: g[3] as string,
    promptTokens: Number(g[4]),
    completionTokens: Number(g[5]),
    attempts: Number(g[6]),
    firstTokenMs: Number(g[7]),
    totalMs: Number(g[8]),
  };
  expect(done.firstTokenMs).toBeLessThanOrEqual(done.totalMs);
  return { text: out.slice(0, -1).join("\n"), done };
}

test.describe("EA-24 Model Gateway and version-pinned model catalog", () => {
  test.setTimeout(180_000);

  // ---------------------------------------------------------------------------------------------
  // AC1 Local call
  // ---------------------------------------------------------------------------------------------

  test("AC1: a streaming chat call to the local model prints the answer and a done line with usage", async () => {
    const run = modelTry(DEMO_ORG, LOCAL_REF, ["--max-tokens", "16"]);
    const { text, done } = expectTrySuccess(run);
    expect(
      text.trim().length,
      "at least one character of streamed text before the done line",
    ).toBeGreaterThan(0);
    expect(`${done.model}@${done.version}`).toBe(LOCAL_REF);
    expect(done.digest).toBe("sha256:3605803b982c");
    expect(done.promptTokens).toBeGreaterThan(0);
    expect(done.completionTokens).toBeGreaterThan(0);
    expect(done.completionTokens).toBeLessThanOrEqual(16);
  });

  test("AC1 TC-1-2: the answer streams: text reaches stdout in several chunks before the done line", async () => {
    const chunks: { at: number; text: string }[] = [];
    const started = Date.now();
    const child = spawnAsync(
      "docker",
      [
        "compose",
        "exec",
        "-T",
        "api",
        "ei-ai",
        "model",
        "try",
        "--org",
        DEMO_ORG,
        "--model",
        LOCAL_REF,
        "--max-tokens",
        "48",
        "--prompt",
        "Hãy đếm từ một đến hai mươi bằng tiếng Việt.",
      ],
      { cwd: ROOT },
    );
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (text: string) => chunks.push({ at: Date.now() - started, text }));
    child.stderr.on("data", (text: string) => {
      stderr += text;
    });
    const code = await new Promise<number | null>((resolve) => child.on("close", resolve));
    const closedAt = Date.now() - started;
    expect(code, stderr).toBe(0);
    expect(stderr).toBe("");
    expect(chunks.length, "stdout arrived in more than one chunk").toBeGreaterThan(1);
    const first = chunks[0] as { at: number; text: string };
    expect(first.text).not.toContain("done:");
    expect(first.at, "first text arrived before the process exited").toBeLessThan(closedAt);
    const all = chunks.map((chunk) => chunk.text).join("");
    expect(lines(all).pop()).toMatch(DONE);
  });

  test("AC1 TC-1-3: a Vietnamese prompt with diacritics works and --max-tokens caps the completion", async () => {
    const run = modelTry(DEMO_ORG, LOCAL_REF, [
      "--prompt",
      "Chào bạn, hãy trả lời bằng một câu: Việt Nam có bao nhiêu tỉnh thành?",
      "--max-tokens",
      "1",
    ]);
    const { done } = expectTrySuccess(run);
    expect(done.completionTokens).toBeLessThanOrEqual(1);
    expect(done.promptTokens).toBeGreaterThan(0);
  });

  test("AC1 TC-1-4: the default prompt and default max tokens (64) work", async () => {
    const run = modelTry(DEMO_ORG, LOCAL_REF);
    const { text, done } = expectTrySuccess(run);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(done.completionTokens).toBeLessThanOrEqual(64);
  });

  test("AC1 TC-1-5: model try is for chat models: an embedding or rerank ref is MODEL_NOT_FOUND", async () => {
    for (const ref of [EMBEDDING_REF, RERANK_REF]) {
      expectCliError(modelTry(DEMO_ORG, ref), MESSAGES.notFound(ref));
    }
  });

  test("AC1 TC-1-6: argument and Organization errors of model try", async () => {
    const ghost = randomUUID();
    expectArgError(modelTry("not-a-uuid", LOCAL_REF), MESSAGES.orgId);
    expectArgError(modelTry(DEMO_ORG, "no-at-sign"), MESSAGES.modelRef);
    expectArgError(modelTry(DEMO_ORG, "@2026.10"), MESSAGES.modelRef);
    expectArgError(modelTry(DEMO_ORG, "qwen3-4b-instruct-2507@"), MESSAGES.modelRef);
    expectCliError(modelTry(ghost, LOCAL_REF), MESSAGES.orgNotFound);
    const missing = cli(["model", "try", "--org", DEMO_ORG]);
    expect(missing.status).toBe(2);
    expect(missing.stdout.trim()).toBe("");
    expect(missing.stderr).toContain("--model");
    const nothing = cli(["model"]);
    expect(nothing.status).toBe(2);
    expect(nothing.stdout.trim()).toBe("");
  });

  test("AC1 TC-1-7: the prompt and the answer never reach stderr or the api log", async () => {
    const sentinel = `QA24SENTINEL${suffix()}`;
    const ok = modelTry(DEMO_ORG, LOCAL_REF, [
      "--prompt",
      `Lặp lại đúng một từ này: ${sentinel}`,
      "--max-tokens",
      "16",
    ]);
    expectTrySuccess(ok);
    const failed = modelTry(DEMO_ORG, LOCAL_REF, ["--prompt", `Xin chào ${sentinel}`], {
      MODEL_LOCAL_BASE_URL: DEAD_LOCAL,
    });
    expectCliError(failed, MESSAGES.unavailable(LOCAL_REF));
    expect(failed.stderr).not.toContain(sentinel);
    const apiLogs = spawn("docker", ["compose", "logs", "--no-color", "api"]).stdout;
    expect(apiLogs).not.toContain(sentinel);
  });

  // ---------------------------------------------------------------------------------------------
  // AC2 Pinned version
  // ---------------------------------------------------------------------------------------------

  test("AC2: a catalog row with the same model id and another digest is PINNED_VERSION_UNAVAILABLE; the pinned one works; the digest cannot be edited", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      const added = modelAdd(org, LOCAL_REF);
      expect(added.status, added.stderr).toBe(0);
      const newerId = sql(
        `insert into model_catalog (org_id, kind, display_name, model_id, version, digest, deployment, provider)
         values ('${org}', 'chat', 'QA newer build', 'qwen3-4b-instruct-2507', 'qa-newer',
                 'sha256:' || repeat('a', 64), 'local', 'local-chat') returning id;`,
      );

      // 1. The newer build is not what the server runs: no silent use of another version.
      expectCliError(
        modelTry(org, "qwen3-4b-instruct-2507@qa-newer", ["--max-tokens", "8"]),
        MESSAGES.pinned("qwen3-4b-instruct-2507@qa-newer"),
      );

      // 2. The pinned one still works.
      const { done } = expectTrySuccess(modelTry(org, LOCAL_REF, ["--max-tokens", "8"]));
      expect(done.digest).toBe("sha256:3605803b982c");

      // 3. The running server lists exactly one id, derived from the real file hash.
      const listing = spawn("docker", [
        "compose",
        "exec",
        "-T",
        "model",
        "curl",
        "-fsS",
        "http://localhost:8080/v1/models",
      ]);
      expect(listing.status, listing.stderr).toBe(0);
      const parsed = JSON.parse(listing.stdout) as { data: { id: string }[] };
      expect(parsed.data.map((entry) => entry.id)).toEqual([SERVED_ID]);

      // 4. The pin cannot be edited in place, even by the superuser; the row is unchanged.
      const before = rows(`select digest from model_catalog where id = '${newerId}'`);
      const update = psql(
        "postgres",
        `update model_catalog set digest = 'sha256:' || repeat('b', 64) where id = '${newerId}';`,
        ["-v", "ON_ERROR_STOP=1"],
      );
      expect(update.status).not.toBe(0);
      expect(update.stderr).toContain("pin columns are immutable");
      expect(rows(`select digest from model_catalog where id = '${newerId}'`)).toEqual(before);
      expect(before).toEqual([`sha256:${"a".repeat(64)}`]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-2: every pin column is immutable for ei_ai_app and postgres; status, retirement date and labels can change", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      expect(modelAdd(org, LOCAL_REF).status).toBe(0);
      const id = sql(`select id from model_catalog where org_id = '${org}'`);
      const pinUpdates = [
        "kind = 'embedding'",
        "model_id = 'qa-other'",
        "version = 'v2'",
        "digest = 'sha256:' || repeat('b', 64)",
        "source_revision = 'x'",
        "deployment = 'cloud'",
        "provider = 'openai'",
      ];
      const snapshot = () =>
        rows(
          `select kind, model_id, version, digest, source_revision, deployment, provider
           from model_catalog where id = '${id}'`,
        );
      const original = snapshot();

      for (const role of ["ei_ai_app", "postgres"]) {
        // Session-level tenant context so that each statement runs on its own (a failed statement would
        // abort a surrounding transaction).
        const script = [
          `select set_config('app.current_org', '${org}', false);`,
          ...pinUpdates.map((set) => `update model_catalog set ${set} where id = '${id}';`),
        ].join("\n");
        const result = psql(role, script, ["-v", "ON_ERROR_STOP=0"]);
        const count = (result.stderr.match(/pin columns are immutable/g) ?? []).length;
        expect(count, `${role}: ${result.stderr}`).toBe(pinUpdates.length);
        expect(result.stdout).not.toContain("UPDATE 1");
        expect(snapshot()).toEqual(original);
      }

      // A no-change update of a pin column is not a change.
      const same = psql(
        "postgres",
        `update model_catalog set digest = digest, model_id = model_id where id = '${id}';`,
      );
      expect(same.stderr).toBe("");

      // Non-pin columns can change (the retirement flow of D18).
      const allowed = psql(
        "ei_ai_app",
        [
          `select set_config('app.current_org', '${org}', false);`,
          `update model_catalog set display_name = 'Renamed Mô hình' where id = '${id}';`,
          `update model_catalog set status = 'retiring', retirement_date = current_date + 30 where id = '${id}';`,
        ].join("\n"),
        ["-v", "ON_ERROR_STOP=0"],
      );
      expect(allowed.stderr).toBe("");
      expect(allowed.stdout.match(/UPDATE 1/g) ?? []).toHaveLength(2);
      expect(
        rows(`select display_name || '|' || status from model_catalog where id = '${id}'`),
      ).toEqual(["Renamed Mô hình|retiring"]);
      expect(snapshot()).toEqual(original);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-3: a ref that exists only in another Organization is MODEL_NOT_FOUND and never borrowed", async () => {
    const sfx = suffix();
    try {
      const orgA = createOrg(sfx, "a");
      const orgB = createOrg(sfx, "b");
      expect(modelAdd(orgA, LOCAL_REF).status).toBe(0);
      const cloudA = insertCloudRow(orgA);
      // B has nothing: neither the local nor the cloud ref of A resolves.
      expectCliError(modelTry(orgB, LOCAL_REF), MESSAGES.notFound(LOCAL_REF));
      expectCliError(modelTry(orgB, CLOUD_REF), MESSAGES.notFound(CLOUD_REF));
      expect(catalogRefs(orgB)).toEqual([]);
      expect(modelEvents(orgB)).toEqual([]);
      // A still works, and nothing was written for the cloud row of A.
      expectTrySuccess(modelTry(orgA, LOCAL_REF, ["--max-tokens", "4"]));
      expect(modelEvents(orgA).filter((event) => event.includes(cloudA))).toEqual([]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-4: the same ref in two Organizations with different digests resolves each to its own digest", async () => {
    const sfx = suffix();
    try {
      const orgA = createOrg(sfx, "a");
      const orgB = createOrg(sfx, "b");
      expect(modelAdd(orgA, LOCAL_REF).status).toBe(0);
      // B pins the same name and version label to a different build (as postgres).
      sql(
        `insert into model_catalog (org_id, kind, display_name, model_id, version, digest, deployment, provider)
         values ('${orgB}', 'chat', 'QA other build', 'qwen3-4b-instruct-2507', '2026.10',
                 'sha256:' || repeat('d', 64), 'local', 'local-chat');`,
      );
      // A resolves its own (served) digest; B resolves its own digest, which the server does not run.
      const a = expectTrySuccess(modelTry(orgA, LOCAL_REF, ["--max-tokens", "4"]));
      expect(a.done.digest).toBe("sha256:3605803b982c");
      expectCliError(modelTry(orgB, LOCAL_REF), MESSAGES.pinned(LOCAL_REF));
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-5: a retired model, or a retirement date today or earlier, is MODEL_RETIRED; a future date still works", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      expect(modelAdd(org, LOCAL_REF).status).toBe(0);
      const set = (assignments: string) =>
        sql(`update model_catalog set ${assignments} where org_id = '${org}';`);

      set("status = 'retired'");
      expectCliError(modelTry(org, LOCAL_REF), MESSAGES.retired(LOCAL_REF));

      set("status = 'retiring', retirement_date = current_date");
      expectCliError(modelTry(org, LOCAL_REF), MESSAGES.retired(LOCAL_REF));

      set("status = 'retiring', retirement_date = current_date - 10");
      expectCliError(modelTry(org, LOCAL_REF), MESSAGES.retired(LOCAL_REF));

      // Not retired yet: still callable, and the row is still the same one (no substitution).
      set("status = 'retiring', retirement_date = current_date + 30");
      expectTrySuccess(modelTry(org, LOCAL_REF, ["--max-tokens", "4"]));
      expect(catalogRefs(org)).toEqual([LOCAL_REF]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test(
    "AC2 TC-2-6: the model server refuses to start when the file sha256 differs from LLM_MODEL_SHA256",
    { tag: "@slow" },
    async () => {
      test.setTimeout(300_000);
      const wrong = "0".repeat(64);
      // A one-off container of the model service (the running one is untouched): hashing the file
      // takes seconds; the server must not start.
      const run = spawn("docker", [
        "compose",
        "--profile",
        "model",
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "-e",
        `LLM_MODEL_SHA256=${wrong}`,
        "model",
      ]);
      expect(run.status).toBe(1);
      expect(run.stderr).toContain(
        `model file sha256 mismatch: expected ${wrong}, got 3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`,
      );
      expect(run.stdout + run.stderr).not.toMatch(/listening|server is listening/i);
      // The running model server is still the checked one.
      const listing = spawn("docker", [
        "compose",
        "exec",
        "-T",
        "model",
        "curl",
        "-fsS",
        "http://localhost:8080/v1/models",
      ]);
      expect(listing.stdout).toContain(`"id":"${SERVED_ID}"`);
    },
  );

  // ---------------------------------------------------------------------------------------------
  // AC3 Retry
  // ---------------------------------------------------------------------------------------------

  test("AC3: an unreachable model server gives MODEL_UNAVAILABLE, exit 1, quickly, with no traceback", async () => {
    const started = Date.now();
    const run = modelTry(DEMO_ORG, LOCAL_REF, [], { MODEL_LOCAL_BASE_URL: DEAD_LOCAL });
    const elapsed = Date.now() - started;
    expectCliError(run, MESSAGES.unavailable(LOCAL_REF));
    expect(elapsed, "answered within 15 s").toBeLessThan(15_000);
  });

  test("AC3 TC-3-2: a server that accepts but never answers is tried exactly twice (one retry), then MODEL_UNAVAILABLE", async () => {
    test.setTimeout(120_000);
    const port = 9777;
    const program = [
      "import socket,time",
      "s=socket.socket()",
      "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)",
      `s.bind(('127.0.0.1',${port}))`,
      "s.listen(16)",
      "s.settimeout(0.2)",
      "n=0",
      "keep=[]",
      "end=time.time()+14",
      "while time.time()<end:",
      "    try:",
      "        c,_=s.accept()",
      "        keep.append(c)",
      "        n+=1",
      "    except socket.timeout:",
      "        pass",
      "print(n,flush=True)",
    ].join("\n");
    const payload = Buffer.from(program, "utf8").toString("base64");
    const hanging = spawnAsync(
      "docker",
      [
        "compose",
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        `import base64;exec(base64.b64decode('${payload}'))`,
      ],
      { cwd: ROOT },
    );
    let connections = "";
    hanging.stdout.setEncoding("utf8");
    hanging.stdout.on("data", (text: string) => {
      connections += text;
    });
    const finished = new Promise<number | null>((resolve) => hanging.on("close", resolve));
    try {
      await sleep(3_000);
      const started = Date.now();
      const run = modelTry(DEMO_ORG, LOCAL_REF, [], {
        MODEL_LOCAL_BASE_URL: `http://127.0.0.1:${port}/v1`,
        MODEL_READ_TIMEOUT_SECONDS: "1",
        MODEL_RETRY_DELAY_SECONDS: "0",
      });
      const elapsed = Date.now() - started;
      expectCliError(run, MESSAGES.unavailable(LOCAL_REF));
      expect(elapsed, "at least two read timeouts passed (one retry)").toBeGreaterThanOrEqual(
        1_800,
      );
      expect(elapsed).toBeLessThan(30_000);
      expect(await finished).toBe(0);
      // One TCP connection per attempt: exactly 2, never 3 (no hidden SDK retry).
      expect(connections.trim()).toBe("2");
    } finally {
      hanging.kill();
    }
  });

  // ---------------------------------------------------------------------------------------------
  // AC4 No cloud fallback
  // ---------------------------------------------------------------------------------------------

  test("AC4: when the local model fails and the Organization allows cloud with a cloud model, the result is the local MODEL_UNAVAILABLE and no cloud call is made", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      expect(modelAdd(org, LOCAL_REF).status).toBe(0);
      insertCloudRow(org);
      setAllowCloud(org, true);
      const before = rows(`select count(*) from audit_events where org_id = '${org}'`);

      const run = modelTry(org, LOCAL_REF, [], {
        MODEL_LOCAL_BASE_URL: DEAD_LOCAL,
        EGRESS_PROXY_URL: DEAD_PROXY,
      });
      expectCliError(run, MESSAGES.unavailable(LOCAL_REF));
      expect(run.stderr).not.toMatch(/CLOUD_|gpt-4\.1|openai/i);

      // The only model audit row is the catalog entry added by the setup: no block, nothing else.
      expect(modelEvents(org).map((event) => event.split("|")[1])).toEqual([
        "model.catalog_entry_added",
      ]);
      expect(rows(`select count(*) from audit_events where org_id = '${org}'`)).toEqual(before);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC4 TC-4-2: the same holds with a working cloud setup in the environment (proxy set) and a hung local server", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      expect(modelAdd(org, LOCAL_REF).status).toBe(0);
      insertCloudRow(org);
      setAllowCloud(org, true);
      // Environment proxies must not be used as a way to reach the cloud either.
      const run = modelTry(org, LOCAL_REF, [], {
        MODEL_LOCAL_BASE_URL: DEAD_LOCAL,
        EGRESS_PROXY_URL: DEAD_PROXY,
        HTTPS_PROXY: DEAD_PROXY,
        HTTP_PROXY: DEAD_PROXY,
        NO_PROXY: "*",
      });
      expectCliError(run, MESSAGES.unavailable(LOCAL_REF));
      expect(modelEvents(org).map((event) => event.split("|")[1])).toEqual([
        "model.catalog_entry_added",
      ]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  // ---------------------------------------------------------------------------------------------
  // AC5 Cloud disabled
  // ---------------------------------------------------------------------------------------------

  test("AC5: a cloud model with Allow cloud models off is blocked with CLOUD_DISABLED and audited once", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      const other = createOrg(sfx, "other");
      const cloudId = insertCloudRow(org);
      expect(rows(`select allow_cloud_models from organizations where id = '${org}'`)).toEqual([
        "f",
      ]);
      const demoBlocksBefore = sql(
        `select count(*) from audit_events where org_id = '${DEMO_ORG}' and action = 'model.cloud_call_blocked'`,
      );

      expectCliError(modelTry(org, CLOUD_REF), MESSAGES.cloudDisabled);

      expect(modelEvents(org)).toEqual([
        `platform-operator|model.cloud_call_blocked|model|${cloudId}`,
      ]);
      expect(
        rows(
          `select count(*) from audit_events where action = 'model.cloud_call_blocked' and target_id = '${cloudId}'`,
        ),
      ).toEqual(["1"]);
      // No such row in any other Organization.
      expect(modelEvents(other)).toEqual([]);
      expect(
        sql(
          `select count(*) from audit_events where org_id = '${DEMO_ORG}' and action = 'model.cloud_call_blocked'`,
        ),
      ).toBe(demoBlocksBefore);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC5 TC-5-2: each blocked call is audited; the switch is read live on every call", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      const cloudId = insertCloudRow(org);
      const blocked = () =>
        modelEvents(org).filter((event) => event.includes("cloud_call_blocked"));

      expectCliError(modelTry(org, CLOUD_REF), MESSAGES.cloudDisabled);
      expectCliError(modelTry(org, CLOUD_REF), MESSAGES.cloudDisabled);
      expect(blocked()).toHaveLength(2);

      // Switched on: no block, no new audit row (no key and no proxy, so the call fails closed).
      setAllowCloud(org, true);
      expectCliError(modelTry(org, CLOUD_REF), MESSAGES.cloudNotConfigured);
      expect(blocked()).toHaveLength(2);

      // Switched off again: blocked again straight away (no cached switch).
      setAllowCloud(org, false);
      expectCliError(modelTry(org, CLOUD_REF), MESSAGES.cloudDisabled);
      expect(blocked()).toHaveLength(3);
      for (const event of blocked()) {
        expect(event).toBe(`platform-operator|model.cloud_call_blocked|model|${cloudId}`);
      }
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC5 TC-5-3: the cloud switch cannot be overridden by an argument or the environment", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      insertCloudRow(org);
      for (const flag of ["--allow-cloud", "--allow-cloud-models", "--cloud"]) {
        const run = modelTry(org, CLOUD_REF, [flag]);
        expect(run.status, flag).toBe(2);
        expect(run.stdout.trim()).toBe("");
        expect(run.stderr).toContain("unrecognized arguments");
      }
      expect(modelEvents(org)).toEqual([]);
      const env = {
        ALLOW_CLOUD_MODELS: "true",
        MODEL_ALLOW_CLOUD: "1",
        ALLOW_CLOUD: "true",
        EGRESS_PROXY_URL: DEAD_PROXY,
      };
      expectCliError(modelTry(org, CLOUD_REF, [], env), MESSAGES.cloudDisabled);
      expect(rows(`select allow_cloud_models from organizations where id = '${org}'`)).toEqual([
        "f",
      ]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC5 TC-5-4: a cloud ref of another Organization is MODEL_NOT_FOUND and writes no audit row anywhere", async () => {
    const sfx = suffix();
    try {
      const orgA = createOrg(sfx, "a");
      const orgB = createOrg(sfx, "b");
      const cloudA = insertCloudRow(orgA);
      expectCliError(modelTry(orgB, CLOUD_REF), MESSAGES.notFound(CLOUD_REF));
      expect(modelEvents(orgA)).toEqual([]);
      expect(modelEvents(orgB)).toEqual([]);
      expect(rows(`select count(*) from audit_events where target_id = '${cloudA}'`)).toEqual([
        "0",
      ]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  // ---------------------------------------------------------------------------------------------
  // AC6 Through the proxy
  // ---------------------------------------------------------------------------------------------

  test("AC6: with cloud allowed but no egress proxy configured, a cloud call is refused with CLOUD_NOT_CONFIGURED (no direct connection)", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      insertCloudRow(org);
      setAllowCloud(org, true);

      // The api container has no egress proxy configured (contract of the stack).
      const env = spawn("docker", ["compose", "exec", "-T", "api", "env"]).stdout;
      expect(env).not.toMatch(/^EGRESS_PROXY_URL=./m);

      // 1. No proxy in the environment.
      const started = Date.now();
      expectCliError(modelTry(org, CLOUD_REF), MESSAGES.cloudNotConfigured);
      expect(Date.now() - started, "refused before any network access").toBeLessThan(15_000);

      // 2. Environment proxies are ignored, whatever they say.
      expectCliError(
        modelTry(org, CLOUD_REF, [], { HTTPS_PROXY: DEAD_PROXY, NO_PROXY: "*" }),
        MESSAGES.cloudNotConfigured,
      );
      expectCliError(
        modelTry(org, CLOUD_REF, [], {
          HTTP_PROXY: DEAD_PROXY,
          HTTPS_PROXY: DEAD_PROXY,
          ALL_PROXY: DEAD_PROXY,
          NO_PROXY: "*",
        }),
        MESSAGES.cloudNotConfigured,
      );

      // The call was allowed (switch on), so it is not a block.
      expect(modelEvents(org).filter((event) => event.includes("cloud_call_blocked"))).toEqual([]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC6 TC-6-2: with a proxy configured but no key, a cloud call still fails closed (CLOUD_NOT_CONFIGURED), never a direct call", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      insertCloudRow(org);
      setAllowCloud(org, true);
      const started = Date.now();
      expectCliError(
        modelTry(org, CLOUD_REF, [], { EGRESS_PROXY_URL: DEAD_PROXY }),
        MESSAGES.cloudNotConfigured,
      );
      expect(Date.now() - started).toBeLessThan(15_000);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC6 TC-6-3: a malformed EGRESS_PROXY_URL is a configuration error that names the variable, not the value", async () => {
    const run = modelTry(DEMO_ORG, LOCAL_REF, [], {
      EGRESS_PROXY_URL: "ftp://user:Sup3rS3cretPw@proxy.example.test:21",
    });
    expect(run.status).not.toBe(0);
    expect(run.stdout.trim()).toBe("");
    expect(run.stderr).toContain("EGRESS_PROXY_URL");
    expect(run.stderr).not.toContain("Sup3rS3cretPw");
    expect(run.stderr).not.toMatch(/Traceback/);
  });

  // ---------------------------------------------------------------------------------------------
  // AC7 Catalog fields (+ model add, seed, RLS)
  // ---------------------------------------------------------------------------------------------

  test("AC7: the catalog table has exactly the contract columns, forced RLS, and organizations has the cloud switch (default off)", async () => {
    expect(
      rows(
        `select column_name from information_schema.columns
         where table_schema = 'public' and table_name = 'model_catalog' order by ordinal_position`,
      ),
    ).toEqual(COLUMNS);
    expect(
      rows(
        `select relrowsecurity::text || '|' || relforcerowsecurity::text from pg_class
         where relname = 'model_catalog' and relnamespace = 'public'::regnamespace`,
      ),
    ).toEqual(["true|true"]);
    expect(
      rows(
        `select data_type || '|' || is_nullable || '|' || coalesce(column_default, '') from information_schema.columns
         where table_schema = 'public' and table_name = 'organizations' and column_name = 'allow_cloud_models'`,
      ),
    ).toEqual(["boolean|NO|false"]);
    // No endpoint URL, key or secret column: builders never enter model endpoint URLs (SSRF).
    expect(COLUMNS.join(",")).not.toMatch(/url|endpoint|key|secret|token/);
    expect(rows(`select version_num from alembic_version`)).toEqual(["0005"]);
  });

  test("AC7 TC-7-2: the demo Organization has the three manifest models with the contract values", async () => {
    const warmUp = seed();
    expect(warmUp.status, warmUp.stderr).toBe(0);
    const fetchRow = (modelId: string) => {
      const out = rows(
        `select row_to_json(t)::text from (
           select kind, display_name, model_id, version, digest, source_revision, deployment, provider,
                  vietnamese_quality, vietnamese_quality_measured, tool_use, context_window, speed,
                  status, retirement_date
           from model_catalog where org_id = '${DEMO_ORG}' and model_id = '${modelId}'
         ) t`,
      );
      expect(out, modelId).toHaveLength(1);
      return JSON.parse(out[0] as string) as Record<string, unknown>;
    };
    expect(
      rows(
        `select model_id || '@' || version from model_catalog where org_id = '${DEMO_ORG}' order by 1`,
      ),
    ).toEqual([RERANK_REF, EMBEDDING_REF, LOCAL_REF].sort());

    expect(fetchRow("qwen3-4b-instruct-2507")).toEqual({
      kind: "chat",
      display_name: "Qwen3 4B Instruct 2507",
      model_id: "qwen3-4b-instruct-2507",
      version: "2026.10",
      digest: CHAT_DIGEST,
      source_revision: CHAT_SOURCE,
      deployment: "local",
      provider: "local-chat",
      vietnamese_quality: null,
      vietnamese_quality_measured: false,
      tool_use: true,
      context_window: 8192,
      speed: null,
      status: "available",
      retirement_date: null,
    });

    const embedding = fetchRow("bge-m3");
    expect(embedding).toMatchObject({
      kind: "embedding",
      version: "2026.10",
      deployment: "local",
      provider: "local-embedding",
      tool_use: false,
      context_window: 8192,
      status: "available",
    });
    const rerank = fetchRow("bge-reranker-v2-m3");
    expect(rerank).toMatchObject({
      kind: "rerank",
      version: "2026.10",
      deployment: "local",
      provider: "local-rerank",
      tool_use: false,
      status: "available",
    });
    const digests = [CHAT_DIGEST, embedding.digest, rerank.digest] as string[];
    for (const digest of digests) expect(digest).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(new Set(digests).size, "three different artefacts").toBe(3);
    for (const entry of [embedding, rerank]) {
      expect(String(entry.source_revision)).toMatch(/[0-9a-f]{40}/);
      expect(String(entry.display_name).length).toBeGreaterThan(0);
    }
    expect(rows(`select allow_cloud_models from organizations where id = '${DEMO_ORG}'`)).toEqual([
      "f",
    ]);
    // The seed writes no audit events for the models.
    expect(
      sql(
        `select count(*) from audit_events where org_id = '${DEMO_ORG}' and action like 'model.%'`,
      ),
    ).toBe("0");
  });

  test("AC7 TC-7-3: running the seed again adds no catalog row and no audit event", async () => {
    const warmUp = seed();
    expect(warmUp.status, warmUp.stderr).toBe(0);
    const snapshot = () =>
      sql(
        `select (select count(*) from model_catalog) || '|' ||
                (select count(*) from model_catalog where org_id = '${DEMO_ORG}') || '|' ||
                (select count(*) from audit_events where org_id = '${DEMO_ORG}')`,
      );
    const before = snapshot();
    const first = seed();
    const second = seed();
    expect(first.status, first.stderr).toBe(0);
    expect(second.stdout).toBe(first.stdout);
    expect(first.stdout).toContain("Audit events written: 0");
    expect(snapshot()).toBe(before);
    expect(before.split("|")[1]).toBe("3");
  });

  test("AC7 TC-7-4: CHECK constraints and uniqueness reject bad catalog rows; good rows (Vietnamese labels, cloud without digest) are accepted", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      const base: Record<string, string> = {
        org_id: `'${org}'`,
        kind: "'chat'",
        display_name: "'QA row'",
        model_id: "'qa-model'",
        version: "'v1'",
        digest: `'sha256:${"c".repeat(64)}'`,
        deployment: "'local'",
        provider: "'local-chat'",
      };
      const insert = (overrides: Record<string, string | null>) => {
        const merged: Record<string, string> = { ...base };
        for (const [key, value] of Object.entries(overrides)) {
          if (value === null) delete merged[key];
          else merged[key] = value;
        }
        const columns = Object.keys(merged).join(", ");
        const values = Object.values(merged).join(", ");
        return psql("postgres", `insert into model_catalog (${columns}) values (${values});`, [
          "-v",
          "ON_ERROR_STOP=1",
        ]);
      };
      const lit = (text: string) => `'${text}'`;

      // Accepted rows.
      expect(insert({}).status).toBe(0);
      expect(
        insert({ version: "'v2'", display_name: "'Mô hình ngôn ngữ tiếng Việt'" }).status,
      ).toBe(0);
      expect(
        insert({
          version: "'v3'",
          deployment: "'cloud'",
          provider: "'openai'",
          digest: null,
          vietnamese_quality: "'fair'",
          vietnamese_quality_measured: "true",
          speed: "'faster'",
          context_window: "32768",
        }).status,
      ).toBe(0);
      expect(
        insert({ version: "'v4'", status: "'retiring'", retirement_date: "current_date + 30" })
          .status,
      ).toBe(0);
      expect(
        rows(`select display_name from model_catalog where org_id = '${org}' and version = 'v2'`),
      ).toEqual(["Mô hình ngôn ngữ tiếng Việt"]);

      const rejected: [string, Record<string, string | null>][] = [
        ["kind", { version: lit("b1"), kind: lit("summary") }],
        ["deployment", { version: lit("b2"), deployment: lit("edge") }],
        ["local without digest", { version: lit("b3"), digest: null }],
        ["digest upper-case hex", { version: lit("b4"), digest: lit(`sha256:${"A".repeat(64)}`) }],
        ["digest too short", { version: lit("b5"), digest: lit("sha256:abc") }],
        ["digest other algorithm", { version: lit("b6"), digest: lit(`md5:${"c".repeat(64)}`) }],
        ["model_id upper-case", { version: lit("b7"), model_id: lit("Qwen3") }],
        ["model_id empty", { version: lit("b8"), model_id: lit("") }],
        ["model_id too long", { version: lit("b9"), model_id: lit("m".repeat(101)) }],
        ["model_id diacritics", { version: lit("b10"), model_id: lit("mô-hình") }],
        ["version empty", { version: lit("") }],
        ["version too long", { version: lit("v".repeat(41)) }],
        ["display_name empty", { version: lit("b11"), display_name: lit("") }],
        ["display_name too long", { version: lit("b12"), display_name: lit("n".repeat(201)) }],
        ["provider upper-case", { version: lit("b13"), provider: lit("Local_Chat") }],
        ["vietnamese_quality", { version: lit("b14"), vietnamese_quality: lit("great") }],
        ["speed", { version: lit("b15"), speed: lit("fast") }],
        ["status", { version: lit("b16"), status: lit("deprecated") }],
        ["retiring without a date", { version: lit("b17"), status: lit("retiring") }],
        ["context_window zero", { version: lit("b18"), context_window: "0" }],
        ["context_window negative", { version: lit("b19"), context_window: "-5" }],
        ["source_revision empty", { version: lit("b20"), source_revision: lit("") }],
      ];
      for (const [name, overrides] of rejected) {
        const result = insert(overrides);
        expect(result.status, `${name} must be rejected`).not.toBe(0);
        expect(result.stderr, name).toContain("violates check constraint");
      }
      // Same (org, model_id, version) twice.
      const duplicate = insert({});
      expect(duplicate.status).not.toBe(0);
      expect(duplicate.stderr).toContain("duplicate key value violates unique constraint");

      // Only the four accepted rows exist.
      expect(
        rows(`select version from model_catalog where org_id = '${org}' order by version`),
      ).toEqual(["v1", "v2", "v3", "v4"]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC7 TC-7-5: the same model_id and version can exist in two Organizations", async () => {
    const sfx = suffix();
    try {
      const orgA = createOrg(sfx, "a");
      const orgB = createOrg(sfx, "b");
      expect(modelAdd(orgA, LOCAL_REF).status).toBe(0);
      expect(modelAdd(orgB, LOCAL_REF).status).toBe(0);
      expect(catalogRefs(orgA)).toEqual([LOCAL_REF]);
      expect(catalogRefs(orgB)).toEqual([LOCAL_REF]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC7 TC-7-6: row-level security isolates the catalog: another Organization's rows are invisible and cannot be changed or forged", async () => {
    const sfx = suffix();
    try {
      const orgA = createOrg(sfx, "a");
      const orgB = createOrg(sfx, "b");
      expect(modelAdd(orgA, LOCAL_REF).status).toBe(0);
      expect(modelAdd(orgB, LOCAL_REF).status).toBe(0);
      const bRow = sql(`select id from model_catalog where org_id = '${orgB}'`);
      const script = `
begin;
select set_config('app.current_org', '${orgA}', true);
\\echo VISIBLE_ALL
select count(*) from model_catalog;
\\echo VISIBLE_B
select count(*) from model_catalog where org_id = '${orgB}';
\\echo UPDATE_B
update model_catalog set display_name = 'hacked' where org_id = '${orgB}';
\\echo DELETE_B
delete from model_catalog where org_id = '${orgB}';
\\echo INSERT_FOR_B
insert into model_catalog (org_id, kind, display_name, model_id, version, digest, deployment, provider)
  values ('${orgB}', 'chat', 'leak-probe-secret', 'qa-forged', 'v1', 'sha256:${"e".repeat(64)}', 'local', 'local-chat');
rollback;
`;
      const result = psql("ei_ai_app", script, ["-v", "ON_ERROR_STOP=0"]);
      const out = result.stdout
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const after = (marker: string) => out[out.indexOf(marker) + 1];
      expect(after("VISIBLE_ALL")).toBe("1");
      expect(after("VISIBLE_B")).toBe("0");
      expect(after("UPDATE_B")).toBe("UPDATE 0");
      expect(after("DELETE_B")).toBe("DELETE 0");
      expect(result.stderr).toContain(
        'new row violates row-level security policy for table "model_catalog"',
      );
      expect(result.stderr).not.toContain("leak-probe-secret");
      expect(rows(`select display_name from model_catalog where id = '${bRow}'`)).toEqual([
        "Qwen3 4B Instruct 2507",
      ]);
      // Without any tenant context the application role sees nothing.
      expect(psql("ei_ai_app", "select count(*) from model_catalog").stdout.trim()).toBe("0");
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC7 TC-7-7: model add registers a manifest model, audits it once, is idempotent and writes only to --org", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      const other = createOrg(sfx, "other");
      const demoBefore = sql(`select count(*) from model_catalog where org_id = '${DEMO_ORG}'`);

      const first = modelAdd(org, LOCAL_REF);
      expect(first.status, first.stderr).toBe(0);
      expect(first.stderr).toBe("");
      expect(lines(first.stdout)).toEqual([`added: ${LOCAL_REF} (chat, local)`]);
      const id = sql(`select id from model_catalog where org_id = '${org}'`);
      expect(modelEvents(org)).toEqual([`platform-operator|model.catalog_entry_added|model|${id}`]);
      // The row equals the manifest entry.
      expect(
        rows(
          `select digest || '|' || source_revision || '|' || provider from model_catalog where id = '${id}'`,
        ),
      ).toEqual([`${CHAT_DIGEST}|${CHAT_SOURCE}|local-chat`]);

      // Again: nothing new.
      const again = modelAdd(org, LOCAL_REF);
      expect(again.status, again.stderr).toBe(0);
      expect(lines(again.stdout)).toEqual([`already present: ${LOCAL_REF}`]);
      expect(catalogRefs(org)).toEqual([LOCAL_REF]);
      expect(modelEvents(org)).toHaveLength(1);

      // The other manifest models (kind and deployment in the output).
      expect(lines(modelAdd(org, EMBEDDING_REF).stdout)).toEqual([
        `added: ${EMBEDDING_REF} (embedding, local)`,
      ]);
      expect(lines(modelAdd(org, RERANK_REF).stdout)).toEqual([
        `added: ${RERANK_REF} (rerank, local)`,
      ]);
      expect(catalogRefs(org)).toEqual([RERANK_REF, EMBEDDING_REF, LOCAL_REF].sort());
      expect(modelEvents(org)).toHaveLength(3);

      // Nothing leaked into another Organization or the demo Organization.
      expect(catalogRefs(other)).toEqual([]);
      expect(modelEvents(other)).toEqual([]);
      expect(sql(`select count(*) from model_catalog where org_id = '${DEMO_ORG}'`)).toBe(
        demoBefore,
      );
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC7 TC-7-8: model add rejects bad input with the exact messages and writes nothing", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      const ghost = randomUUID();
      const before = sql(`select count(*) from model_catalog`);
      const eventsBefore = sql(`select count(*) from audit_events`);

      expectArgError(modelAdd("not-a-uuid", LOCAL_REF), MESSAGES.orgId);
      expectArgError(modelAdd(org, "no-at-sign"), MESSAGES.modelRef);
      expectArgError(modelAdd(org, "UPPER@1"), MESSAGES.modelRef);
      expectCliError(modelAdd(ghost, LOCAL_REF), MESSAGES.orgNotFound);
      for (const ref of [
        "gpt-4.1-2025-04-14@2025.04",
        "qwen3-4b-instruct-2507@2025.01",
        "nope@1",
      ]) {
        expectCliError(modelAdd(org, ref), MESSAGES.unknownModel(ref));
      }
      const missing = cli(["model", "add", "--org", org]);
      expect(missing.status).toBe(2);
      expect(missing.stderr).toContain("--model");

      expect(sql(`select count(*) from model_catalog`)).toBe(before);
      expect(sql(`select count(*) from audit_events`)).toBe(eventsBefore);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC7 TC-7-9: audit_events accepts the new target type model", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(sfx);
      const result = psql(
        "postgres",
        `insert into audit_events (org_id, actor, action, target_type, target_id)
         values ('${org}', 'platform-operator', 'model.catalog_entry_added', 'model', '${randomUUID()}');`,
        ["-v", "ON_ERROR_STOP=1"],
      );
      expect(result.status, result.stderr).toBe(0);
      const bad = psql(
        "postgres",
        `insert into audit_events (org_id, actor, action, target_type, target_id)
         values ('${org}', 'platform-operator', 'model.catalog_entry_added', 'not_a_type', '${randomUUID()}');`,
        ["-v", "ON_ERROR_STOP=1"],
      );
      expect(bad.status).not.toBe(0);
      expect(bad.stderr).toContain("violates check constraint");
    } finally {
      purgeBySuffix(sfx);
    }
  });
});
