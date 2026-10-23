// EA-20 (FND-03): per-Organization data keys (wrapped by a master key), encrypted original files and
// per-Organization vector partitions. Profile api: no HTTP route, no browser. Black-box: the Platform
// Operator CLI, psql as postgres / ei_ai_app, the migrator one-off container, the backend test suites
// and the container logs. Written from .work/EA-20/contract.md only.
// Runs against a running, migrated stack (migration head 0011, EI_AI_MASTER_KEY in .env):
//   npm run up && npm run migrate && npm run seed && npm run e2e -- e2e/foundation/EA-20-org-*
// Test data: every Organization is named `qa-EA20-<run>-<tag>`; teardown (afterAll) drops the partitions
// this run created, deletes the rows children first as the superuser (RLS is never altered) and proves
// that the row counts equal the counts of the start.
import { spawnSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { DEMO_ORG, ROOT, UUID, lines, rows, sql } from "../support/ea22";
import { dotenvValue } from "../support/ea94";

const SONG_HAN_ORG = "0192a000-0000-7000-8000-00000000ea94";
const RUN = randomBytes(3).toString("hex");
const MARK = `qa-EA20-${RUN}`;
const MARK_LC = MARK.toLowerCase();
const KEY_ERRORS = {
  required: "configuration error: EI_AI_MASTER_KEY or EI_AI_MASTER_KEY_FILE is required",
  invalid: "configuration error: EI_AI_MASTER_KEY must be 64 hexadecimal characters",
  both: "configuration error: set only one of EI_AI_MASTER_KEY and EI_AI_MASTER_KEY_FILE",
  fileUnreadable: "configuration error: EI_AI_MASTER_KEY_FILE cannot be read",
  fileInvalid: "configuration error: EI_AI_MASTER_KEY_FILE must hold 64 hexadecimal characters",
  migrationUrl: "configuration error: MIGRATION_DATABASE_URL is required",
};

// Tables whose row counts must be identical before and after this spec.
const COUNT_TABLES = [
  "organizations",
  "workspaces",
  "users",
  "memberships",
  "workspace_memberships",
  "set_password_tokens",
  "user_credentials",
  "admin_sessions",
  "audit_events",
  "organization_keys",
  "chunk_embeddings",
];
// Children first.
const PURGE_BY_ORG = [
  "chunk_embeddings",
  "organization_keys",
  "admin_sessions",
  "user_credentials",
  "audit_events",
  "set_password_tokens",
  "document_chunks",
  "documents",
  "folders",
  "collections",
  "model_catalog",
  "workspace_memberships",
  "memberships",
  "users",
  "workspaces",
];

// 1024-dimension vectors (contract: embedding vector(1024)).
const DIM = 1024;
const QUERY = `'[1${",0".repeat(DIM - 1)}]'::vector`; // unit vector on axis 1: distance 0 to itself
const ORTHOGONAL = `'[0,1${",0".repeat(DIM - 2)}]'::vector`;
const FILLED = `array_fill(0.1::real, ARRAY[${DIM}])::vector`;

/** `docker compose` with every profile, so that `config` and `logs` cover all services (core, model, tools). */
const ALL_PROFILES = ["compose", "--profile", "core", "--profile", "model", "--profile", "tools"];

type Run = { status: number | null; stdout: string; stderr: string };

/** Every stdout/stderr this spec captured (swept for the master key in the last test). */
const captured: { label: string; text: string }[] = [];

function spawn(file: string, args: string[], input?: string): Run {
  const result = spawnSync(file, args, {
    cwd: ROOT,
    encoding: "utf8",
    input,
    maxBuffer: 256 * 1024 * 1024,
  });
  return { status: result.status, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
}

function remember(label: string, run: Run): Run {
  captured.push({ label: `${label} stdout`, text: run.stdout });
  captured.push({ label: `${label} stderr`, text: run.stderr });
  return run;
}

/** `docker compose exec -T [-e K=V ...] api ei-ai <args>`; an empty value sets the variable empty. */
function ei(args: string[], env: Record<string, string> = {}): Run {
  const envArgs = Object.entries(env).flatMap(([key, value]) => ["-e", `${key}=${value}`]);
  return spawn("docker", ["compose", "exec", "-T", ...envArgs, "api", "ei-ai", ...args]);
}

/** `docker compose --profile tools run --rm -T migrate ei-ai <args>` (has the migrator credentials). */
function migrator(args: string[]): Run {
  return spawn("docker", [
    "compose",
    "--profile",
    "tools",
    "run",
    "--rm",
    "-T",
    "migrate",
    "ei-ai",
    ...args,
  ]);
}

/** `docker compose --profile tools run --rm -T backend-tools <args>`. */
function backendTools(args: string[]): Run {
  return spawn("docker", [
    "compose",
    "--profile",
    "tools",
    "run",
    "--rm",
    "-T",
    "backend-tools",
    ...args,
  ]);
}

/** psql in the db container as `role`; errors carry the SQLSTATE (VERBOSITY=verbose) and stop the script. */
function psqlAs(role: string, script: string): Run {
  return spawn(
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
      "VERBOSITY=verbose",
      "-v",
      "ON_ERROR_STOP=1",
    ],
    script,
  );
}

function expectSqlState(run: Run, state: string, text?: string): void {
  expect(run.status, "the statement must fail").not.toBe(0);
  expect(run.stderr).toContain(`${state}:`);
  if (text !== undefined) expect(run.stderr).toContain(text);
}

function inContext(orgId: string, body: string, end: "commit" | "rollback" = "rollback"): string {
  return `begin; set local app.current_org = '${orgId}'; ${body} ${end};`;
}

function masterKey(): string {
  const fromShell = process.env.EI_AI_MASTER_KEY;
  const value =
    fromShell !== undefined && fromShell !== ""
      ? fromShell
      : dotenvValue(path.join(ROOT, ".env"), "EI_AI_MASTER_KEY");
  expect(value, "precondition: EI_AI_MASTER_KEY is set in .env").toMatch(/^[0-9a-f]{64}$/);
  return value as string;
}

function mentionsKey(text: string): boolean {
  return text.toLowerCase().includes(masterKey());
}

function hexOf(orgId: string): string {
  return orgId.replace(/-/g, "");
}

function partitionName(orgId: string): string {
  return `chunk_embeddings_${hexOf(orgId)}`;
}

function partitionExists(orgId: string): boolean {
  return sql(`select to_regclass('public.${partitionName(orgId)}') is not null`) === "t";
}

type QaOrg = { id: string; hex: string; name: string; email: string; run: Run };

/** `org create` for a throwaway Organization of this run; parses the Organization id. */
function newOrg(tag: string): QaOrg {
  const name = `${MARK}-${tag}`;
  const email = `${MARK_LC}-${tag}@example.com`;
  const run = remember(
    `org create ${tag}`,
    ei(["org", "create", "--name", name, "--owner", email]),
  );
  expect(run.status, run.stderr).toBe(0);
  const out = lines(run.stdout);
  expect(out).toHaveLength(4); // unchanged output: Organization, Workspace, Org Owner, set-password link
  const match = new RegExp(`^Organization created: (${UUID}) \\(${name}\\)$`).exec(out[0] ?? "");
  expect(match, out[0]).not.toBeNull();
  const id = match?.[1] as string;
  return { id, hex: hexOf(id), name, email, run };
}

function createPartition(org: QaOrg): Run {
  return remember(
    `vector-partition ${org.hex}`,
    migrator(["db", "vector-partition", "--org", org.id]),
  );
}

type Fixture = { a: QaOrg; b: QaOrg; c: QaOrg };
let fixtureMemo: Fixture | undefined;

/** Organizations A and B with a vector partition each, C without one (created once per run). */
function fixture(): Fixture {
  if (fixtureMemo === undefined) {
    const a = newOrg("fa");
    const b = newOrg("fb");
    const c = newOrg("fc");
    for (const org of [a, b]) {
      const run = createPartition(org);
      expect(run.status, run.stderr).toBe(0);
    }
    fixtureMemo = { a, b, c };
  }
  return fixtureMemo;
}

/**
 * Inserts one complete vector row per vector expression for `org`, as ei_ai_app in its context:
 * since EA-35 every vector belongs to a chunk of a ready document and carries its metadata, so this
 * also creates a collection, a folder, a ready document and one chunk per vector. Returns the new
 * vector ids in the order of `vectors`.
 */
function insertVectors(org: QaOrg, vectors: string[]): string[] {
  const name = `${MARK}-vectors-${randomBytes(3).toString("hex")}`;
  const run = psqlAs(
    "ei_ai_app",
    inContext(
      org.id,
      `with ws as (select id from workspaces where org_id = '${org.id}' order by created_at, id limit 1),
       c as (insert into collections (org_id, workspace_id, name, access_level)
             select '${org.id}', id, '${name}', 'authenticated' from ws returning id, workspace_id),
       f as (insert into folders (org_id, collection_id, name, depth)
             select '${org.id}', id, 'qa', 1 from c returning id),
       d as (insert into documents (org_id, collection_id, folder_id, name, format, size_bytes, status, chunk_count, file_id)
             select '${org.id}', c.id, f.id, 'qa.txt', 'txt', 1, 'ready', ${vectors.length}, gen_random_uuid()
             from c cross join f returning id),
       v as (select u.embedding, (u.n - 1)::int as ordinal
             from unnest(array[${vectors.join(", ")}]::vector[]) with ordinality as u(embedding, n)),
       ch as (insert into document_chunks (org_id, document_id, ordinal, text, char_start, char_end, token_estimate)
              select '${org.id}', d.id, v.ordinal, 'qa', 0, 2, 1 from d cross join v returning id, ordinal),
       e as (insert into chunk_embeddings (org_id, embedding, chunk_id, document_id, workspace_id, collection_id,
                                           folder_id, access_level, groups, model_id, model_version)
             select '${org.id}', v.embedding, ch.id, d.id, c.workspace_id, c.id, f.id, 'authenticated', '{}', 'qa-ea20', '1'
             from ch join v using (ordinal) cross join d cross join c cross join f returning id, chunk_id)
       select e.id from e join ch on ch.id = e.chunk_id order by ch.ordinal;`,
      "commit",
    ),
  );
  expect(run.status, run.stderr).toBe(0);
  const ids = lines(run.stdout).filter((line) => !line.startsWith("INSERT "));
  expect(ids).toHaveLength(vectors.length);
  return ids;
}

function queryIds(orgId: string, body: string): string[] {
  const run = psqlAs("ei_ai_app", inContext(orgId, body));
  expect(run.status, run.stderr).toBe(0);
  return lines(run.stdout);
}

/** Names of every relation scanned in an EXPLAIN (FORMAT JSON) plan. */
function scannedRelations(node: unknown): string[] {
  if (Array.isArray(node)) return node.flatMap(scannedRelations);
  if (node === null || typeof node !== "object") return [];
  const record = node as Record<string, unknown>;
  const own =
    typeof record["Relation Name"] === "string" ? [record["Relation Name"] as string] : [];
  return [...own, ...Object.values(record).flatMap(scannedRelations)];
}

function tableCounts(): Record<string, number> {
  const parts = COUNT_TABLES.map((table) => `select '${table}', count(*) from ${table}`);
  parts.push(
    "select 'partitions', count(*) from pg_inherits where inhparent = 'chunk_embeddings'::regclass",
  );
  const result: Record<string, number> = {};
  for (const row of rows(parts.join(" union all "))) {
    const [table, count] = row.split("|");
    result[table as string] = Number(count);
  }
  return result;
}

/** Rows (any table) that still carry this run's marker. */
function markerRows(): string[] {
  return rows(
    `select 'organization|' || name from organizations where name ilike '%${MARK_LC}%'
     union all select 'user|' || email from users where email ilike '%${MARK_LC}%'
     union all select 'partition-without-org|' || relname from pg_class c
       where relnamespace = 'public'::regnamespace and relname like 'chunk\\_embeddings\\_%' and relkind = 'r'
       and not exists (select 1 from organizations o where replace(o.id::text, '-', '') = substr(c.relname, 18))`,
  );
}

/** Drops this run's partitions and deletes its Organizations and everything under them. */
function purgeRun(): void {
  const ids = rows(`select id from organizations where position('${MARK_LC}' in lower(name)) > 0`);
  if (ids.length === 0) return;
  const statements = ids.flatMap((id) => {
    expect(id).toMatch(new RegExp(`^${UUID}$`));
    return [
      `drop table if exists ${partitionName(id)};`,
      ...PURGE_BY_ORG.map((table) => `delete from ${table} where org_id = '${id}';`),
      `delete from organizations where id = '${id}';`,
    ];
  });
  sql(`begin; ${statements.join(" ")} commit;`);
}

function expectConfigError(run: Run, message?: string): void {
  expect(run.stdout.trim(), "stdout of a failed command").toBe("");
  expect(run.status).toBe(1);
  const errorLines = lines(run.stderr);
  expect(errorLines).toHaveLength(1);
  if (message === undefined) expect(errorLines[0]).toMatch(/^configuration error: /);
  else expect(errorLines).toEqual([message]);
  expect(run.stderr).not.toMatch(/Traceback|postgresql:\/\//);
  expect(mentionsKey(run.stderr)).toBe(false);
}

let before: Record<string, number>;

test.describe("EA-20 per-Organization encryption keys and vector partitions", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(300_000);

  test.beforeAll(() => {
    masterKey(); // precondition: a generated key exists
    expect(
      sql("select count(*) from information_schema.tables where table_name = 'organization_keys'"),
      "precondition: migration head 0011 is applied (npm run migrate)",
    ).toBe("1");
    before = tableCounts();
  });

  test.afterAll(() => {
    purgeRun();
    // Hygiene: counts equal the counts of the start, no row and no partition of this run is left.
    expect(tableCounts()).toEqual(before);
    expect(markerRows()).toEqual([]);
  });

  // ---------------------------------------------------------------------------------------------
  // AC1 Separate keys
  // ---------------------------------------------------------------------------------------------

  test("AC1: two Organizations get different wrapped data keys; the master key is stored nowhere", () => {
    const key = masterKey();
    const a = newOrg("a1");
    const b = newOrg("b1");

    // org create: output unchanged, audit events unchanged (5 each), one key row per Organization.
    for (const org of [a, b]) {
      expect(sql(`select count(*) from audit_events where org_id = '${org.id}'`)).toBe("5");
      expect(sql(`select count(*) from organization_keys where org_id = '${org.id}'`)).toBe("1");
    }

    const keyRows = rows(
      `select org_id || '|' || octet_length(wrapped_key) || '|' || encode(wrapped_key, 'hex') || '|' || kek_id
              || '|' || (destroyed_at is null) || '|' || (created_at is not null)
       from organization_keys where org_id in ('${a.id}', '${b.id}') order by org_id`,
    ).map((row) => row.split("|"));
    expect(keyRows).toHaveLength(2);
    const [first, second] = keyRows as [string[], string[]];
    for (const row of keyRows) {
      expect(row[1]).toBe("60");
      expect(row[2]).toMatch(/^[0-9a-f]{120}$/);
      expect(row[3]).toMatch(/^[0-9a-f]{16}$/);
      expect(row[4]).toBe("true");
      expect(row[5]).toBe("true");
    }
    expect(first[2], "different Organizations, different wrapped keys").not.toBe(second[2]);
    expect(first[3], "same master key, same kek_id").toBe(second[3]);
    expect(key.includes(first[3] as string), "kek_id is not a slice of the master key").toBe(false);

    // The master key is in no column of any tenant table, as text or as raw bytes.
    expect(
      sql(
        `select count(*) from organization_keys where position('${key}' in lower(encode(wrapped_key, 'hex'))) > 0
         or position(decode('${key}', 'hex') in wrapped_key) > 0 or position('${key}' in lower(kek_id)) > 0`,
      ),
    ).toBe("0");
    const dump = COUNT_TABLES.map(
      (table) =>
        `select '${table}' from ${table} t where position('${key}' in lower(row_to_json(t)::text)) > 0`,
    ).join(" union all ");
    expect(rows(dump)).toEqual([]);

    // Neither the CLI output nor any container log contains the master key (final sweep: last test).
    for (const org of [a, b]) {
      expect(mentionsKey(org.run.stdout + org.run.stderr)).toBe(false);
    }
  });

  test("AC1 TC-1-2: the master key is passed to api and backend-tools only", () => {
    const key = masterKey();
    const config = spawn("docker", [...ALL_PROFILES, "config", "--format", "json"]);
    expect(config.status, config.stderr).toBe(0);
    const services = (JSON.parse(config.stdout) as { services: Record<string, unknown> }).services;
    const names = Object.keys(services);
    expect(names).toEqual(
      expect.arrayContaining(["api", "backend-tools", "db", "migrate", "admin"]),
    );
    const withKey = names.filter((name) =>
      JSON.stringify(services[name]).toLowerCase().includes(key),
    );
    expect(withKey.sort()).toEqual(["api", "backend-tools"]);
    const withVariable = names.filter((name) =>
      JSON.stringify(services[name]).includes("EI_AI_MASTER_KEY"),
    );
    expect(withVariable.sort()).toEqual(["api", "backend-tools"]);
  });

  test(
    "AC1 TC-1-3: .env holds a generated key that is git-ignored, never committed and stable across migrate",
    { tag: "@slow" },
    () => {
      const key = masterKey();
      const ignored = spawn("git", ["check-ignore", "-q", ".env"]);
      expect(ignored.status, ".env must be git-ignored").toBe(0);
      expect(spawn("git", ["ls-files", ".env"]).stdout.trim()).toBe("");
      // The key is in no tracked file; .env.example holds only the placeholder.
      expect(spawn("git", ["grep", "-n", "-i", "-F", "--", key]).status, "git grep: no match").toBe(
        1,
      );
      expect(dotenvValue(path.join(ROOT, ".env.example"), "EI_AI_MASTER_KEY")).toBe(
        "__GENERATED_KEY__",
      );

      // A second `npm run migrate` neither rotates nor duplicates the key (a new key would orphan every wrapped key).
      const migrate = remember("migrate", spawn(process.execPath, ["scripts/dev.mjs", "migrate"]));
      expect(migrate.status, migrate.stdout + migrate.stderr).toBe(0);
      expect(masterKey()).toBe(key);
      expect(dotenvValue(path.join(ROOT, ".env"), "EI_AI_MASTER_KEY")).toBe(key);
    },
  );

  test("AC1 TC-1-4: a missing, invalid or conflicting master key gives an exact error, exit 1 and no write", () => {
    const key = masterKey();
    const counts = tableCounts();
    const create = (env: Record<string, string>, tag: string) =>
      remember(
        `org create ${tag}`,
        ei(
          ["org", "create", "--name", `${MARK}-${tag}`, "--owner", `${MARK_LC}-${tag}@example.com`],
          env,
        ),
      );

    expectConfigError(
      create({ EI_AI_MASTER_KEY: "", EI_AI_MASTER_KEY_FILE: "" }, "none"),
      KEY_ERRORS.required,
    );
    for (const [tag, value] of [
      ["abc", "abc"],
      ["nothex", "g".repeat(64)],
      ["short", "a".repeat(63)],
      ["long", "a".repeat(65)],
    ] as const) {
      const run = create({ EI_AI_MASTER_KEY: value, EI_AI_MASTER_KEY_FILE: "" }, tag);
      expectConfigError(run, KEY_ERRORS.invalid);
      expect(run.stderr, "the value never appears").not.toContain(value);
    }
    // Both variables set: the contract allows exactly one.
    expectConfigError(
      create({ EI_AI_MASTER_KEY: key, EI_AI_MASTER_KEY_FILE: "/tmp/qa-ea20-unused" }, "both"),
      KEY_ERRORS.both,
    );
    // A key file that is missing or is a directory: unreadable; the path never appears.
    for (const [tag, file] of [
      ["nofile", "/nonexistent/qa-ea20.key"],
      ["dirfile", "/tmp"],
    ] as const) {
      const run = create({ EI_AI_MASTER_KEY: "", EI_AI_MASTER_KEY_FILE: file }, tag);
      expectConfigError(run, KEY_ERRORS.fileUnreadable);
      expect(run.stderr, "the path never appears").not.toContain(file);
    }
    // A key file whose content is not 64 hex characters: the content never appears.
    const badFile = `/tmp/${MARK_LC}-bad.key`;
    try {
      const write = spawn("docker", [
        "compose",
        "exec",
        "-T",
        "api",
        "sh",
        "-c",
        `umask 077; printf 'not-a-key-qa-ea20-secret' > ${badFile}`,
      ]);
      expect(write.status, "precondition: a key file can be written in the api container").toBe(0);
      const run = create({ EI_AI_MASTER_KEY: "", EI_AI_MASTER_KEY_FILE: badFile }, "badfile");
      expectConfigError(run, KEY_ERRORS.fileInvalid);
      expect(run.stderr).not.toContain("not-a-key-qa-ea20-secret");
      expect(run.stderr).not.toContain(badFile);
    } finally {
      spawn("docker", ["compose", "exec", "-T", "api", "rm", "-f", badFile]);
    }

    expect(
      sql(
        `select count(*) from organizations where lower(name) ~ '^${MARK_LC}-(none|abc|nothex|short|long|both|nofile|dirfile|badfile)$'`,
      ),
      "no Organization written by any failed command",
    ).toBe("0");
    expect(tableCounts()).toEqual(counts);
  });

  test("AC1 TC-1-5: the key file variable gives the same master key (same kek_id) as the variable", () => {
    const key = masterKey();
    const file = `/tmp/${MARK_LC}.key`;
    const viaVariable = newOrg("kv");
    try {
      const write = spawn("docker", [
        "compose",
        "exec",
        "-T",
        "-e",
        `QA_KEY=${key}`,
        "api",
        "sh",
        "-c",
        `umask 077; printf %s "$QA_KEY" > ${file}`,
      ]);
      expect(write.status, "precondition: a key file can be written in the api container").toBe(0);
      const run = remember(
        "org create via key file",
        ei(["org", "create", "--name", `${MARK}-kf`, "--owner", `${MARK_LC}-kf@example.com`], {
          EI_AI_MASTER_KEY: "",
          EI_AI_MASTER_KEY_FILE: file,
        }),
      );
      expect(run.status, run.stderr).toBe(0);
      const id = new RegExp(`^Organization created: (${UUID}) `).exec(
        lines(run.stdout)[0] ?? "",
      )?.[1];
      expect(id).toBeTruthy();
      const kek = (orgId: string) =>
        sql(
          `select octet_length(wrapped_key) || '|' || kek_id from organization_keys where org_id = '${orgId}'`,
        );
      expect(kek(id as string)).toBe(kek(viaVariable.id));
      expect(mentionsKey(run.stdout + run.stderr)).toBe(false);
    } finally {
      spawn("docker", ["compose", "exec", "-T", "api", "rm", "-f", file]);
    }
  });

  test("AC1 TC-1-6: the demo seed leaves exactly one data key per demo Organization, also on a re-run", () => {
    const seed = () => remember("seed", spawn(process.execPath, ["scripts/dev.mjs", "seed"]));
    const keyOf = (orgId: string) =>
      rows(
        `select id || '|' || encode(wrapped_key, 'hex') || '|' || kek_id from organization_keys where org_id = '${orgId}'`,
      );
    const audit = (orgId: string) =>
      sql(`select count(*) from audit_events where org_id = '${orgId}'`);

    const warmUp = seed();
    expect(warmUp.status, warmUp.stderr).toBe(0);
    const snapshot: Record<string, string[]> = {
      [DEMO_ORG]: keyOf(DEMO_ORG),
      [SONG_HAN_ORG]: keyOf(SONG_HAN_ORG),
    };
    const events: Record<string, string> = {
      [DEMO_ORG]: audit(DEMO_ORG),
      [SONG_HAN_ORG]: audit(SONG_HAN_ORG),
    };
    const totals = tableCounts();
    for (const orgId of [DEMO_ORG, SONG_HAN_ORG]) {
      expect(snapshot[orgId], `one key row for ${orgId}`).toHaveLength(1);
      expect(sql(`select count(*) from chunk_embeddings where org_id = '${orgId}'`)).toBe("0");
      // Since EA-35 `npm run seed` ensures the demo Organizations' vector partitions.
      expect(partitionExists(orgId), "the seed ensures the vector partition").toBe(true);
    }

    const first = seed();
    const second = seed();
    expect(first.status, first.stderr).toBe(0);
    expect(second.status, second.stderr).toBe(0);
    expect(second.stdout).toBe(first.stdout);
    for (const orgId of [DEMO_ORG, SONG_HAN_ORG]) {
      expect(keyOf(orgId), "the key is neither rotated nor duplicated").toEqual(snapshot[orgId]);
      expect(audit(orgId), "audit event counts unchanged").toBe(events[orgId]);
    }
    expect(tableCounts()).toEqual(totals);
  });

  test("AC1 TC-1-7: organization_keys has the contract shape, is unique per Organization and keeps its invariants", () => {
    const { a } = fixture();
    const columns = rows(
      `select column_name || ':' || data_type || ':' || is_nullable from information_schema.columns
       where table_schema = 'public' and table_name = 'organization_keys' order by column_name`,
    );
    expect(columns).toEqual([
      "created_at:timestamp with time zone:NO",
      "destroyed_at:timestamp with time zone:YES",
      "id:uuid:NO",
      "kek_id:text:NO",
      "org_id:uuid:NO",
      "wrapped_key:bytea:YES",
    ]);
    // RLS like every table.
    expect(
      sql(
        `select relrowsecurity::text || '|' || relforcerowsecurity::text from pg_class where oid = 'organization_keys'::regclass`,
      ),
    ).toBe("true|true");
    // One row per Organization: a second key for the same Organization is a unique violation (23505).
    const duplicate = psqlAs(
      "postgres",
      `begin; insert into organization_keys (org_id, wrapped_key, kek_id)
         select org_id, wrapped_key, kek_id from organization_keys where org_id = '${a.id}'; rollback;`,
    );
    expectSqlState(duplicate, "23505");
    // Row invariants over every row: live = 60 bytes + kek_id 16 hex, destroyed = NULL key with a timestamp.
    expect(
      sql(
        `select count(*) from organization_keys where (wrapped_key is null) <> (destroyed_at is not null)
         or (wrapped_key is not null and octet_length(wrapped_key) <> 60) or kek_id !~ '^[0-9a-f]{16}$'`,
      ),
    ).toBe("0");
    expect(
      sql(
        `select count(*) from (select org_id from organization_keys group by org_id having count(*) > 1) x`,
      ),
    ).toBe("0");
  });

  // ---------------------------------------------------------------------------------------------
  // AC2 Encrypted files, AC3 Wrong org, AC5 Key destruction (backend suites + database observations)
  // ---------------------------------------------------------------------------------------------

  let suiteMemo: Run | undefined;
  /** The storage + crypto integration suites: one run serves AC2 and AC3. */
  function storageAndCrypto(): Run {
    if (suiteMemo === undefined) {
      suiteMemo = remember(
        "pytest storage+crypto",
        backendTools([
          "pytest",
          "tests/integration/storage",
          "tests/integration/crypto",
          "-m",
          "integration",
          "-v",
          "--no-cov",
        ]),
      );
    }
    return suiteMemo;
  }

  function expectPassed(run: Run, names: string[]): void {
    const output = run.stdout + run.stderr;
    for (const name of names) {
      const pattern = new RegExp(
        `(?:::${name}(?:\\[.*?\\])?\\s+PASSED|PASSED\\s+\\S*::${name}\\b)`,
      );
      expect(output, `${name} must PASS (not fail, skip or be missing)`).toMatch(pattern);
    }
  }

  test("AC2: the file on disk is unreadable and decrypts byte-for-byte through the backend library", () => {
    const run = storageAndCrypto();
    expect(run.status, run.stdout.slice(-3000)).toBe(0);
    expectPassed(run, [
      "test_file_on_disk_is_unreadable_and_decrypts_byte_for_byte",
      "test_file_permissions_are_private",
    ]);
  });

  test("AC3: decrypting another Organization's file or key fails without returning data", () => {
    const run = storageAndCrypto();
    expect(run.status, run.stdout.slice(-3000)).toBe(0);
    expectPassed(run, [
      "test_other_orgs_file_id_is_not_found",
      "test_foreign_blob_under_own_directory_fails_to_decrypt",
      "test_decrypt_with_another_orgs_context_fails_without_data",
      "test_context_of_a_with_session_of_b_finds_no_key",
      "test_wrapped_key_copied_to_another_org_does_not_unwrap",
    ]);
  });

  test("AC3 TC-3-3: in Organization A's context the application role cannot read, write or change B's key row", () => {
    const { a, b } = fixture();
    const wrappedOf = (orgId: string) =>
      sql(`select encode(wrapped_key, 'hex') from organization_keys where org_id = '${orgId}'`);
    const keyB = wrappedOf(b.id);
    expect(keyB).toMatch(/^[0-9a-f]{120}$/);

    expect(
      queryIds(a.id, `select count(*) from organization_keys where org_id = '${b.id}';`),
    ).toEqual(["0"]);
    expect(queryIds(a.id, `select org_id from organization_keys;`)).toEqual([a.id]);
    expect(
      queryIds(
        a.id,
        `select count(*) from organization_keys where encode(wrapped_key, 'hex') = '${keyB}';`,
      ),
    ).toEqual(["0"]);

    // A write for another Organization is rejected (42501), the error does not leak the values.
    const insert = psqlAs(
      "ei_ai_app",
      inContext(
        a.id,
        `insert into organization_keys (org_id, wrapped_key, kek_id) values ('${b.id}', decode(repeat('00', 60), 'hex'), '0123456789abcdef');`,
      ),
    );
    expectSqlState(insert, "42501");
    expect(insert.stderr).not.toContain(keyB);
    // Moving A's own row to B is rejected as well.
    expectSqlState(
      psqlAs(
        "ei_ai_app",
        inContext(
          a.id,
          `update organization_keys set org_id = '${b.id}' where org_id = '${a.id}';`,
        ),
      ),
      "42501",
    );
    // Updating or deleting B's row either changes 0 rows or is refused (42501); B's key stays byte-identical.
    for (const statement of [
      `with u as (update organization_keys set wrapped_key = null, destroyed_at = now() where org_id = '${b.id}' returning 1) select count(*) from u;`,
      `with d as (delete from organization_keys where org_id = '${b.id}' returning 1) select count(*) from d;`,
    ]) {
      const run = psqlAs("ei_ai_app", inContext(a.id, statement));
      if (run.status === 0) expect(lines(run.stdout)).toEqual(["0"]);
      else expectSqlState(run, "42501");
    }
    expect(wrappedOf(b.id)).toBe(keyB);
    expect(
      sql(
        `select count(*) from organization_keys where org_id = '${a.id}' and wrapped_key is not null and destroyed_at is null`,
      ),
    ).toBe("1");
  });

  test("AC5: after the key is destroyed none of the Organization's files or conversations can be decrypted", () => {
    const run = remember(
      "pytest destroyed",
      backendTools([
        "pytest",
        "tests/integration/crypto",
        "tests/integration/storage",
        "-m",
        "integration",
        "-v",
        "--no-cov",
        "-k",
        "destroyed",
      ]),
    );
    expect(run.status, run.stdout.slice(-3000)).toBe(0);
    expectPassed(run, [
      "test_destroyed_key_blocks_encrypt_and_decrypt",
      "test_destroyed_key_makes_files_unreadable",
    ]);
  });

  // ---------------------------------------------------------------------------------------------
  // AC4 Separate vectors
  // ---------------------------------------------------------------------------------------------

  test("AC4: a vector query in Organization A's context scans only A's partition and returns only A's rows", () => {
    const { a, b } = fixture();
    const idsA = insertVectors(a, [FILLED, ORTHOGONAL]);
    const idsB = insertVectors(b, [QUERY]); // B's vector is the query itself (distance 0): nearest of all

    const plan = psqlAs(
      "ei_ai_app",
      inContext(
        a.id,
        `set local plan_cache_mode = force_custom_plan;
         explain (format json) select id from chunk_embeddings where org_id = '${a.id}' order by embedding <=> ${QUERY} limit 5;`,
      ),
    );
    expect(plan.status, plan.stderr).toBe(0);
    const relations = [...new Set(scannedRelations(JSON.parse(plan.stdout)))];
    expect(relations, "the plan names only A's partition").toEqual([partitionName(a.id)]);
    expect(plan.stdout).not.toContain(b.hex);

    const hits = queryIds(
      a.id,
      `select id from chunk_embeddings where org_id = '${a.id}' order by embedding <=> ${QUERY} limit 5;`,
    );
    expect([...hits].sort()).toEqual([...idsA].sort());
    for (const id of idsB) expect(hits).not.toContain(id);
    // Without the explicit org filter the tenant policy still returns only A's rows.
    expect(
      [
        ...queryIds(
          a.id,
          `select id from chunk_embeddings order by embedding <=> ${QUERY} limit 5;`,
        ),
      ].sort(),
    ).toEqual([...idsA].sort());
    // B's context sees only B's row.
    expect(
      queryIds(b.id, `select id from chunk_embeddings order by embedding <=> ${QUERY} limit 5;`),
    ).toEqual(idsB);

    // Each partition holds only its own Organization's vectors.
    expect(sql(`select count(*) from ${partitionName(a.id)}`)).toBe("2");
    expect(sql(`select count(*) from ${partitionName(b.id)}`)).toBe("1");
    expect(sql(`select count(*) from ${partitionName(a.id)} where org_id <> '${a.id}'`)).toBe("0");
  });

  test("AC4 TC-4-2: the partitioned table, its partitions, ownership, hnsw index and grants", () => {
    const { a, b } = fixture();
    expect(
      sql(`select relkind::text || '|' || pg_get_partkeydef(oid) || '|' || relrowsecurity::text || '|' || relforcerowsecurity::text
           from pg_class where oid = 'chunk_embeddings'::regclass`),
    ).toBe("p|LIST (org_id)|true|true");
    expect(
      sql(`select string_agg(attname || ':' || format_type(atttypid, atttypmod), ',' order by attname)
           from pg_attribute where attrelid = 'chunk_embeddings'::regclass and attnum > 0 and not attisdropped`),
    ).toBe(
      // EA-35 added the chunk, document, location, access and model metadata columns.
      "access_level:text,chunk_id:uuid,collection_id:uuid,created_at:timestamp with time zone," +
        "document_id:uuid,embedding:vector(1024),folder_id:uuid,groups:text[],id:uuid," +
        "model_id:text,model_version:text,org_id:uuid,workspace_id:uuid",
    );
    expect(
      sql(`select count(*) from pg_inherits i join pg_class c on c.oid = i.inhrelid
           where i.inhparent = 'chunk_embeddings'::regclass and pg_get_expr(c.relpartbound, c.oid) = 'DEFAULT'`),
      "no DEFAULT partition",
    ).toBe("0");

    for (const org of [a, b]) {
      const partition = partitionName(org.id);
      expect(
        sql(`select c.relkind::text || '|' || pg_get_userbyid(c.relowner) || '|' || pg_get_expr(c.relpartbound, c.oid)
             from pg_class c where c.oid = 'public.${partition}'::regclass`),
      ).toBe(`r|ei_ai_migrator|FOR VALUES IN ('${org.id}')`);
      expect(
        Number(
          sql(`select count(*) from pg_index i join pg_class ic on ic.oid = i.indexrelid join pg_am am on am.oid = ic.relam
                    where i.indrelid = 'public.${partition}'::regclass and am.amname = 'hnsw'`),
        ),
        "an hnsw index",
      ).toBeGreaterThanOrEqual(1);
      for (const role of ["ei_ai_app", "ei_ai_signin"]) {
        for (const privilege of [
          "select",
          "insert",
          "update",
          "delete",
          "truncate",
          "references",
          "trigger",
        ]) {
          expect(
            sql(`select has_table_privilege('${role}', 'public.${partition}', '${privilege}')`),
            `${role} ${privilege}`,
          ).toBe("f");
        }
      }
      expect(
        sql(
          `select count(*) from information_schema.role_table_grants where grantee = 'ei_ai_app' and table_name = '${partition}'`,
        ),
      ).toBe("0");
    }
    // A vector with the wrong dimension is rejected, nothing is stored.
    const wrong = psqlAs(
      "ei_ai_app",
      inContext(
        a.id,
        `insert into chunk_embeddings (org_id, embedding) values ('${a.id}', '[1,2,3]'::vector);`,
      ),
    );
    expect(wrong.status).not.toBe(0);
    expect(wrong.stderr).toMatch(/expected 1024 dimensions/);
  });

  test("AC4 TC-4-3: db vector-partition creates once, repeats cleanly and refuses bad input", () => {
    const p = newOrg("pp");
    const ghost = randomUUID();
    const partitions = () =>
      sql("select count(*) from pg_inherits where inhparent = 'chunk_embeddings'::regclass");
    const publicTables = () =>
      sql("select count(*) from pg_class where relnamespace = 'public'::regnamespace");
    const start = partitions();

    // Without migrator credentials (api container) the command refuses and creates nothing.
    const refused = remember(
      "vector-partition in api",
      ei(["db", "vector-partition", "--org", p.id]),
    );
    expect(refused.status).toBe(1);
    expect(refused.stdout.trim()).toBe("");
    expect(lines(refused.stderr)).toEqual([KEY_ERRORS.migrationUrl]);
    expect(partitionExists(p.id)).toBe(false);

    const created = createPartition(p);
    expect(created.status, created.stderr).toBe(0);
    expect(lines(created.stdout)).toEqual([`vector partition created: ${p.id}`]);
    expect(partitionExists(p.id)).toBe(true);

    const again = createPartition(p);
    expect(again.status, again.stderr).toBe(0);
    expect(lines(again.stdout)).toEqual([`vector partition already present: ${p.id}`]);
    expect(Number(partitions())).toBe(Number(start) + 1);

    // Unknown Organization, malformed or missing id, and an injection attempt create nothing.
    const tablesBefore = publicTables();
    const unknown = createPartition({ ...p, id: ghost, hex: hexOf(ghost) });
    expect(unknown.status).toBe(1);
    expect(unknown.stdout.trim()).toBe("");
    expect(lines(unknown.stderr)).toContain("error: Organization not found");
    expect(partitionExists(ghost)).toBe(false);

    for (const args of [
      ["db", "vector-partition", "--org", "not-a-uuid"],
      ["db", "vector-partition"],
      ["db", "vector-partition", "--org", `${p.id}'; drop table x; --`],
      [
        "db",
        "vector-partition",
        "--org",
        `${randomUUID()}'; create table qa_ea20_${RUN}_x (i int); --`,
      ],
    ]) {
      const run = remember(`vector-partition ${args.slice(2).join(" ")}`, migrator(args));
      expect(run.status, args.join(" ")).toBe(2);
      expect(run.stdout.trim()).toBe("");
      expect(run.stderr.toLowerCase()).toContain("usage");
    }
    expect(sql(`select to_regclass('public.qa_ea20_${RUN}_x') is null`)).toBe("t");
    expect(publicTables(), "no table created by a refused command").toBe(tablesBefore);
    expect(Number(partitions())).toBe(Number(start) + 1);
  });

  test("AC4 TC-4-4: another Organization's id is rejected for vectors; no tenant context shows 0 rows in both tables", () => {
    const { a, b } = fixture();
    const beforeB = sql(`select count(*) from ${partitionName(b.id)}`);

    // As A, writing a vector for B is refused by row-level security (42501) and stores nothing.
    const insert = psqlAs(
      "ei_ai_app",
      inContext(
        a.id,
        `insert into chunk_embeddings (org_id, embedding) values ('${b.id}', ${FILLED});`,
      ),
    );
    expectSqlState(insert, "42501");
    expect(sql(`select count(*) from ${partitionName(b.id)}`)).toBe(beforeB);
    expect(
      queryIds(a.id, `select count(*) from chunk_embeddings where org_id = '${b.id}';`),
    ).toEqual(["0"]);

    // No context, an empty context and a forged context: 0 rows (fail closed).
    for (const table of ["chunk_embeddings", "organization_keys"]) {
      expect(lines(psqlAs("ei_ai_app", `select count(*) from ${table};`).stdout)).toEqual(["0"]);
      expect(
        lines(
          psqlAs(
            "ei_ai_app",
            `begin; set local app.current_org = ''; select count(*) from ${table}; rollback;`,
          ).stdout,
        ),
      ).toEqual(["0"]);
      expect(queryIds(randomUUID(), `select count(*) from ${table};`)).toEqual(["0"]);
    }
    const noContextInsert = psqlAs(
      "ei_ai_app",
      `insert into chunk_embeddings (org_id, embedding) values ('${a.id}', ${FILLED});`,
    );
    expectSqlState(noContextInsert, "42501");
  });

  test("AC4 TC-4-5: the application role cannot touch a partition directly or create or truncate partitions", () => {
    const { a } = fixture();
    const partition = partitionName(a.id);
    const denied = (statement: string) => {
      const run = psqlAs("ei_ai_app", `begin; ${statement} rollback;`);
      expectSqlState(run, "42501");
    };
    denied(`select * from ${partition};`);
    denied(`select count(*) from ${partition};`);
    denied(`insert into ${partition} (org_id, embedding) values ('${a.id}', ${FILLED});`);
    denied(`update ${partition} set org_id = org_id;`);
    denied(`delete from ${partition};`);
    denied(
      `create table qa_ea20_${RUN}_x partition of chunk_embeddings for values in ('${randomUUID()}');`,
    );
    denied(`truncate chunk_embeddings;`); // TRUNCATE bypasses RLS: it must not be granted
    denied(`drop table ${partition};`);
    expect(sql(`select to_regclass('public.qa_ea20_${RUN}_x') is null`)).toBe("t");
    expect(partitionExists(a.id)).toBe(true);
    expect(Number(sql(`select count(*) from ${partition}`))).toBeGreaterThan(0);
  });

  test("AC4 TC-4-6: an Organization without a partition cannot store vectors and its queries return no rows", () => {
    const { c } = fixture();
    expect(partitionExists(c.id)).toBe(false);
    const insert = psqlAs(
      "ei_ai_app",
      inContext(
        c.id,
        `insert into chunk_embeddings (org_id, embedding) values ('${c.id}', ${FILLED});`,
      ),
    );
    expect(insert.status, "no partition and no DEFAULT partition: the insert fails").not.toBe(0);
    expect(sql(`select count(*) from chunk_embeddings where org_id = '${c.id}'`)).toBe("0");
    expect(
      queryIds(
        c.id,
        `select id from chunk_embeddings where org_id = '${c.id}' order by embedding <=> ${QUERY} limit 5;`,
      ),
    ).toEqual([]);
    expect(
      sql(`select count(*) from pg_inherits i join pg_class k on k.oid = i.inhrelid
           where i.inhparent = 'chunk_embeddings'::regclass and pg_get_expr(k.relpartbound, k.oid) = 'DEFAULT'`),
    ).toBe("0");
  });

  test(
    "AC4 TC-4-7: partitions do not trip the schema guard (migrate stays idempotent at head 0011)",
    { tag: "@slow" },
    () => {
      fixture(); // partitions exist while the guard runs
      const migrate = remember(
        "migrate with partitions",
        spawn(process.execPath, ["scripts/dev.mjs", "migrate"]),
      );
      expect(migrate.status, migrate.stdout + migrate.stderr).toBe(0);
      expect(migrate.stdout + migrate.stderr).toContain("database revision: 0011");
      expect(migrate.stdout + migrate.stderr).toContain("schema guard: 0 violations");
    },
  );

  // ---------------------------------------------------------------------------------------------
  // Secrets sweep (keep last)
  // ---------------------------------------------------------------------------------------------

  test("AC1 TC-1-8: the master key appears in no CLI output, pytest output or container log", () => {
    const key = masterKey();
    for (const item of captured) {
      expect(item.text.toLowerCase().includes(key), `master key in: ${item.label}`).toBe(false);
    }
    const logs = spawn("docker", [...ALL_PROFILES, "logs", "--no-color"]);
    expect(logs.status, logs.stderr).toBe(0);
    expect(logs.stdout.toLowerCase().includes(key), "master key in docker compose logs").toBe(
      false,
    );
  });
});
