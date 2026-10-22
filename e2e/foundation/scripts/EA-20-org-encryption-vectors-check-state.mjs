// EA-20 read-only database check (no writes): prints the row counts of the tables this ticket touches, the
// vector partitions, and whether any row, partition or key carries a QA marker `qa-ea20-`. Exit code 0 when the
// state is clean and consistent, 1 otherwise. With `--cleanup` it first removes leftovers that carry the marker
// (partitions dropped, rows deleted children first as the superuser; RLS is never altered).
//
// Run (stack up, migrated):  node e2e/foundation/scripts/EA-20-org-encryption-vectors-check-state.mjs [--cleanup]
// Checks: every Organization has at most one key row; live keys are 60 bytes and `kek_id` is 16 lower-case hex;
// `destroyed_at` is set if and only if `wrapped_key` is NULL; no `chunk_embeddings_<hex>` partition without an
// Organization; no DEFAULT partition. It never prints a key value.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function sql(script) {
  const r = spawnSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "db",
      "psql",
      "-U",
      "postgres",
      "-d",
      "ei_ai",
      "-X",
      "-At",
      "-q",
      "-v",
      "ON_ERROR_STOP=1",
    ],
    { cwd: ROOT, encoding: "utf8", input: script },
  );
  if (r.status !== 0) {
    console.error(r.stderr);
    process.exit(2);
  }
  return r.stdout.trim();
}

const MARK = "qa-ea20-";
const BY_ORG = [
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

if (process.argv.includes("--cleanup")) {
  const ids = sql(`select id from organizations where position('${MARK}' in lower(name)) > 0`)
    .split("\n")
    .filter(Boolean);
  for (const id of ids) {
    sql(
      `begin; drop table if exists chunk_embeddings_${id.replace(/-/g, "")};
       ${BY_ORG.map((table) => `delete from ${table} where org_id = '${id}';`).join(" ")}
       delete from organizations where id = '${id}'; commit;`,
    );
  }
  console.log(`cleanup: removed ${ids.length} Organization(s) with the marker`);
}

const counts = sql(
  `select 'organizations ' || count(*) from organizations
   union all select 'organization_keys ' || count(*) from organization_keys
   union all select 'chunk_embeddings ' || count(*) from chunk_embeddings
   union all select 'partitions ' || count(*) from pg_inherits where inhparent = 'chunk_embeddings'::regclass
   union all select 'audit_events ' || count(*) from audit_events`,
);
console.log(counts);

const problems = [];
const check = (label, query) => {
  const value = sql(query);
  if (value !== "0") problems.push(`${label}: ${value}`);
  console.log(`${value === "0" ? "ok  " : "FAIL"} ${label}`);
};

check(
  "Organizations with the marker",
  `select count(*) from organizations where position('${MARK}' in lower(name)) > 0`,
);
check(
  "users with the marker",
  `select count(*) from users where position('${MARK}' in lower(email)) > 0`,
);
check(
  "partitions without an Organization",
  `select count(*) from pg_class c where relnamespace = 'public'::regnamespace and relkind = 'r'
   and relname ~ '^chunk_embeddings_[0-9a-f]{32}$'
   and not exists (select 1 from organizations o where replace(o.id::text, '-', '') = substr(c.relname, 18))`,
);
check(
  "DEFAULT partitions",
  `select count(*) from pg_inherits i join pg_class c on c.oid = i.inhrelid
   where i.inhparent = 'chunk_embeddings'::regclass and pg_get_expr(c.relpartbound, c.oid) = 'DEFAULT'`,
);
check(
  "Organizations with more than one key",
  `select count(*) from (select org_id from organization_keys group by org_id having count(*) > 1) x`,
);
check(
  "key rows that break an invariant",
  `select count(*) from organization_keys where (wrapped_key is null) <> (destroyed_at is not null)
   or (wrapped_key is not null and octet_length(wrapped_key) <> 60) or kek_id !~ '^[0-9a-f]{16}$'`,
);
check(
  "key rows without an Organization",
  `select count(*) from organization_keys k where not exists (select 1 from organizations o where o.id = k.org_id)`,
);

if (problems.length > 0) {
  console.error(`\nNOT CLEAN: ${problems.join("; ")}`);
  process.exit(1);
}
console.log("\nclean");
