// EA-94 read-only SQL check: prints the row counts and audit actions of both demo Organizations after a
// seed and compares them with the contract (Mekong Devworks and Sông Hàn Retail). Exit code 0 when they
// match, 1 when not. It also prints how many tenant rows carry the QA marker `qa-ea94-` (must be 0).
//
// Run (stack up and seeded):  node e2e/foundation/scripts/EA-94-demo-seed-check-state.mjs
// Sign-in events (user.signed_in, user.signed_out) are not counted. It talks to the database as the superuser through `docker compose exec db psql`; nothing is written.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const ORGS = {
  "Mekong Devworks": {
    id: "0192a000-0000-7000-8000-00000000ea21",
    rows: {
      workspaces: 2,
      users: 10,
      memberships: 10,
      workspace_memberships: 11,
      user_credentials: 10,
      set_password_tokens: 0,
      collections: 8,
      folders: 33,
      model_catalog: 3,
      audit_events: 78,
    },
    audit: {
      "organization.created": 1,
      "workspace.created": 2,
      "user.invited": 10,
      "member.org_role_changed": 3,
      "member.workspace_role_changed": 11,
      "user.password_set": 10,
      "collection.created": 8,
      "folder.created": 33,
    },
  },
  "Sông Hàn Retail": {
    id: "0192a000-0000-7000-8000-00000000ea94",
    rows: {
      workspaces: 1,
      users: 2,
      memberships: 2,
      workspace_memberships: 2,
      user_credentials: 1,
      set_password_tokens: 0,
      collections: 1,
      folders: 3,
      model_catalog: 3,
      audit_events: 13,
    },
    audit: {
      "organization.created": 1,
      "workspace.created": 1,
      "user.invited": 2,
      "member.org_role_changed": 2,
      "member.workspace_role_changed": 2,
      "user.password_set": 1,
      "collection.created": 1,
      "folder.created": 3,
    },
  },
};

// Runs one SQL statement as the database superuser and returns its rows.
// Input: statement (string). Output: string[].
const sql = (statement) => {
  const result = spawnSync(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ei_ai", "-X", "-At", "-q"],
    { cwd: ROOT, encoding: "utf8", input: statement },
  );
  if (result.status !== 0) throw new Error(result.stderr);
  return result.stdout.split("\n").filter((line) => line.trim() !== "");
};

// Compares two flat objects. Input: label, actual, expected. Output: string[] of differences.
const diff = (label, actual, expected) =>
  Object.keys({ ...actual, ...expected })
    .filter((key) => (actual[key] ?? 0) !== (expected[key] ?? 0))
    .map((key) => `${label} ${key}: expected ${expected[key] ?? 0}, found ${actual[key] ?? 0}`);

// Entry point.
const main = () => {
  const problems = [];
  for (const [name, org] of Object.entries(ORGS)) {
    const counts = {};
    for (const table of Object.keys(org.rows).filter((key) => key !== "audit_events")) {
      counts[table] = Number(sql(`select count(*) from ${table} where org_id = '${org.id}'`)[0]);
    }
    // Sign-ins write user.signed_in / user.signed_out events (EA-22): only the seed's actions are counted.
    const audit = {};
    const seedActions = Object.keys(org.audit)
      .map((action) => `'${action}'`)
      .join(", ");
    for (const row of sql(
      `select action || '|' || count(*) from audit_events where org_id = '${org.id}' and action in (${seedActions}) group by action`,
    )) {
      const [action, count] = row.split("|");
      audit[action] = Number(count);
    }
    counts.audit_events = Object.values(audit).reduce((sum, value) => sum + value, 0);
    problems.push(
      ...diff(`${name} rows`, counts, org.rows),
      ...diff(`${name} audit`, audit, org.audit),
    );
    console.log(`${name}: ${JSON.stringify(counts)}`);
  }
  const marked = sql(
    "select count(*) from users where email ilike '%qa-ea94-%' or display_name ilike '%qa-ea94-%'",
  )[0];
  console.log(`rows with the qa-ea94 marker: ${marked}`);
  if (marked !== "0") problems.push(`${marked} rows carry the qa-ea94 marker`);
  if (problems.length > 0) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log("state matches the contract");
};

main();
