// EA-20 exploratory checks that the Playwright spec does not assert (profile api, no browser):
//   TC-1-9  an upper-case 64-hex EI_AI_MASTER_KEY: accepted or rejected, and whether it yields the same kek_id.
//   TC-4-8  a prepared statement with a generic plan: other Organizations' partitions are listed but never executed.
//   and, for reference, which compose services hold EI_AI_MASTER_KEY (only api and backend-tools).
// It prints what it finds; nothing is asserted except the hygiene check at the end (exit 1 when a row or a
// partition with the QA marker is left, or when a row count changed).
//
// Run (stack up, migrated, EI_AI_MASTER_KEY in .env):  node e2e/foundation/scripts/EA-20-org-encryption-vectors-explore.mjs
// Test data: Organizations named `qa-EA20-<run>-<tag>`; the script deletes them and their partitions in `finally`.
// It never prints the master key.
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const RUN = randomBytes(3).toString("hex");
const MARK = `qa-EA20-${RUN}`;
const DIM = 1024;

function run(file, args, input) {
  const r = spawnSync(file, args, {
    cwd: ROOT,
    encoding: "utf8",
    input,
    maxBuffer: 64 * 1024 * 1024,
  });
  return { status: r.status, stdout: r.stdout ?? "", stderr: r.stderr ?? "" };
}

function psql(role, script) {
  return run(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "db",
      "psql",
      "-U",
      role,
      "-d",
      "ei_ai",
      "-X",
      "-At",
      "-q",
      "-v",
      "ON_ERROR_STOP=1",
    ],
    script,
  );
}

function sql(script) {
  const r = psql("postgres", script);
  if (r.status !== 0) throw new Error(`sql failed: ${r.stderr}`);
  return r.stdout.trim();
}

function masterKey() {
  const text = fs.readFileSync(path.join(ROOT, ".env"), "utf8");
  const match = /^EI_AI_MASTER_KEY=([0-9a-f]{64})\s*$/m.exec(text);
  if (!match) throw new Error("EI_AI_MASTER_KEY (64 lower-case hex) not found in .env");
  return match[1];
}

function orgCreate(tag, env = {}) {
  const envArgs = Object.entries(env).flatMap(([k, v]) => ["-e", `${k}=${v}`]);
  const name = `${MARK}-${tag}`;
  const r = run("docker", [
    "compose",
    "exec",
    "-T",
    ...envArgs,
    "api",
    "ei-ai",
    "org",
    "create",
    "--name",
    name,
    "--owner",
    `${MARK.toLowerCase()}-${tag}@example.com`,
  ]);
  const id = /^Organization created: ([0-9a-f-]{36}) /m.exec(r.stdout)?.[1];
  return { ...r, id, name };
}

const COUNT_SQL = `select 'organizations', count(*) from organizations union all
  select 'organization_keys', count(*) from organization_keys union all
  select 'chunk_embeddings', count(*) from chunk_embeddings union all
  select 'audit_events', count(*) from audit_events union all
  select 'partitions', count(*) from pg_inherits where inhparent = 'chunk_embeddings'::regclass order by 1`;

function cleanup() {
  const ids = sql(
    `select id from organizations where position('${MARK.toLowerCase()}' in lower(name)) > 0`,
  )
    .split("\n")
    .filter(Boolean);
  for (const id of ids) {
    const tables = [
      "chunk_embeddings",
      "organization_keys",
      "admin_sessions",
      "user_credentials",
      "audit_events",
      "set_password_tokens",
      "workspace_memberships",
      "memberships",
      "users",
      "workspaces",
    ];
    sql(
      `begin; drop table if exists chunk_embeddings_${id.replace(/-/g, "")};
       ${tables.map((t) => `delete from ${t} where org_id = '${id}';`).join(" ")}
       delete from organizations where id = '${id}'; commit;`,
    );
  }
}

const before = sql(COUNT_SQL);
let failed = false;
try {
  const key = masterKey();

  console.log("== TC-1-9 upper-case master key");
  const normal = orgCreate("lc");
  const upper = orgCreate("uc", { EI_AI_MASTER_KEY: key.toUpperCase() });
  if (upper.status === 0) {
    const kek = (id) => sql(`select kek_id from organization_keys where org_id = '${id}'`);
    console.log(`accepted; same kek_id as lower-case: ${kek(normal.id) === kek(upper.id)}`);
  } else {
    console.log(`rejected (exit ${upper.status}): ${upper.stderr.trim().split("\n")[0]}`);
  }
  console.log(
    `value echoed in output: ${(upper.stdout + upper.stderr).toLowerCase().includes(key)}`,
  );

  console.log("== TC-4-8 generic plan with runtime partition pruning");
  const a = orgCreate("pa");
  const b = orgCreate("pb");
  for (const org of [a, b]) {
    const r = run("docker", [
      "compose",
      "--profile",
      "tools",
      "run",
      "--rm",
      "-T",
      "migrate",
      "ei-ai",
      "db",
      "vector-partition",
      "--org",
      org.id,
    ]);
    console.log(`vector-partition ${org.name}: ${r.stdout.trim()}`);
  }
  for (const org of [a, b]) {
    const r = psql(
      "ei_ai_app",
      `begin; set local app.current_org = '${org.id}';
       insert into chunk_embeddings (org_id, embedding) values ('${org.id}', array_fill(0.1::real, ARRAY[${DIM}])::vector);
       commit;`,
    );
    if (r.status !== 0) throw new Error(r.stderr);
  }
  const plan = psql(
    "ei_ai_app",
    `begin; set local app.current_org = '${a.id}'; set local plan_cache_mode = force_generic_plan;
     prepare q(uuid, vector) as select id from chunk_embeddings where org_id = $1 order by embedding <=> $2 limit 5;
     explain (analyze, format json) execute q('${a.id}', array_fill(0.1::real, ARRAY[${DIM}])::vector);
     rollback;`,
  );
  const text = plan.stdout;
  const executed = (hex) =>
    new RegExp(`"Relation Name": "chunk_embeddings_${hex}"[\\s\\S]*?"Actual Loops": (\\d+)`).exec(
      text,
    )?.[1];
  console.log(
    `A partition actual loops: ${executed(a.id.replace(/-/g, ""))}; B partition actual loops: ${executed(b.id.replace(/-/g, "")) ?? "not in plan"}`,
  );

  console.log("== master key in the compose config");
  const config = run("docker", [
    "compose",
    "--profile",
    "core",
    "--profile",
    "model",
    "--profile",
    "tools",
    "config",
    "--format",
    "json",
  ]);
  const services = JSON.parse(config.stdout).services;
  console.log(
    `services holding EI_AI_MASTER_KEY: ${Object.keys(services)
      .filter((n) => JSON.stringify(services[n]).includes("EI_AI_MASTER_KEY"))
      .sort()
      .join(", ")}`,
  );
} catch (error) {
  failed = true;
  console.error(
    String(error instanceof Error ? error.message : error).replaceAll(masterKeySafe(), "<key>"),
  );
} finally {
  cleanup();
}

function masterKeySafe() {
  try {
    return masterKey();
  } catch {
    return "\u0000";
  }
}

const after = sql(COUNT_SQL);
const leftovers = sql(
  `select count(*) from organizations where position('${MARK.toLowerCase()}' in lower(name)) > 0`,
);
console.log(
  `== hygiene\nrow counts equal before = after: ${before === after}; marker rows left: ${leftovers}`,
);
process.exit(failed || before !== after || leftovers !== "0" ? 1 : 0);
