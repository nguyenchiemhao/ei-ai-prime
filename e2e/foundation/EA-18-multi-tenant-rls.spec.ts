// EA-18 (FND-01): multi-tenant data model with row-level security and a tenant context from authentication.
// Profile api, no browser. Runs against a running, migrated stack:
//   npm run up && npm run migrate && npx playwright test e2e/foundation/EA-18-*
// Everything here is non-destructive: queries are read-only, and the cross-Organization script runs in
// transactions that are rolled back. The positive path (verified Organization A + forged B) needs the
// test-only verifier and is covered by backend/tests/integration/api/test_organization_route.py.
import { execFileSync, spawnSync } from "node:child_process";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { adminUrl } from "../../scripts/lib/admin-url.mjs";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const ROOT = path.resolve(import.meta.dirname, "..", "..");
// ADMIN_URL, else ADMIN_PORT from the shell or .env (default 3000), like compose.yaml.
const ADMIN_URL = adminUrl(ROOT, process.env);
const FORGED = "0b9c1c3e-5f0a-4a52-9a53-2c0f1f6f7a11";
// EA-21 (FND-04) added audit_events and set_password_tokens (migration 0002); EA-22 (FND-05) added
// admin_sessions and user_credentials, the ei_ai_signin role and the sign_in_lookup policy (head 0004);
// EA-24 (FND-07) added model_catalog (head 0005); EA-23 (FND-06) added the audit role-change columns (head 0006);
// EA-32 added collections and folders (head 0007).
const TABLES = [
  "admin_sessions",
  "audit_events",
  "collections",
  "folders",
  "memberships",
  "model_catalog",
  "organizations",
  "set_password_tokens",
  "user_credentials",
  "users",
  "workspace_memberships",
  "workspaces",
];
const REVISION = "0007";
const STANDARD_EXPRESSION = "NULLIF(current_setting('app.current_org'::text, true), ''::text)";

/** Runs SQL through psql in the db container; returns stdout, stderr and the exit code. */
function psql(role: string, sql: string, extra: string[] = []) {
  const result = spawnSync(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", role, "-d", "ei_ai", "-X", "-At", ...extra],
    { cwd: ROOT, encoding: "utf8", input: sql },
  );
  return { out: result.stdout, err: result.stderr, status: result.status };
}

function scalar(role: string, sql: string): string {
  const r = psql(role, sql);
  expect(r.status, r.err).toBe(0);
  return r.out.trim();
}

test.describe("EA-18 multi-tenant data model with RLS", () => {
  test("AC1: every business table has org_id NOT NULL, forced RLS and the tenant policy", () => {
    // Organizations are keyed by id (the tenant itself); every other table carries org_id uuid NOT NULL.
    const columns = scalar(
      "postgres",
      `select string_agg(table_name, ',' order by table_name) from information_schema.columns
       where table_schema='public' and column_name='org_id' and is_nullable='NO' and data_type='uuid'`,
    );
    expect(columns).toBe(
      "admin_sessions,audit_events,collections,folders,memberships,model_catalog,set_password_tokens,user_credentials,users,workspace_memberships,workspaces",
    );

    const rls = scalar(
      "postgres",
      `select string_agg(relname, ',' order by relname) from pg_class
       where relnamespace='public'::regnamespace and relkind='r' and relrowsecurity and relforcerowsecurity`,
    );
    expect(rls).toBe(TABLES.join(","));

    // Any table in public that is not listed above must be the migration bookkeeping table.
    const others = scalar(
      "postgres",
      `select string_agg(relname, ',') from pg_class
       where relnamespace='public'::regnamespace and relkind in ('r','p','v','m')
       and not (relrowsecurity and relforcerowsecurity)`,
    );
    expect(others).toBe("alembic_version");

    // 11 policies: one standard FOR ALL policy per table for every role, plus the one exception
    // `sign_in_lookup` (EA-22): FOR SELECT, only for ei_ai_signin, USING (true), no WITH CHECK.
    const policies = psql(
      "postgres",
      `select policyname, tablename, cmd, roles, qual, with_check from pg_policies order by tablename, policyname`,
    )
      .out.trim()
      .split("\n");
    expect(policies).toHaveLength(TABLES.length + 1);
    const signInLookup = policies.filter((line) => line.startsWith("sign_in_lookup|"));
    expect(signInLookup).toEqual(["sign_in_lookup|users|SELECT|{ei_ai_signin}|true|"]);
    const standard = policies.filter((line) => !line.startsWith("sign_in_lookup|"));
    expect(standard.map((line) => line.split("|")[1])).toEqual(TABLES);
    for (const line of standard) {
      expect(line).toContain(STANDARD_EXPRESSION);
      expect(line).toContain("|ALL|{public}|");
    }

    // Owner decision 2026-10-14: a user belongs to one Organization.
    const constraints = scalar(
      "postgres",
      `select string_agg(conname, ',' order by conname) from pg_constraint
       where conrelid in ('users'::regclass, 'memberships'::regclass)
       and conname in ('users_org_id_email_key', 'memberships_org_id_user_id_fkey')`,
    );
    expect(constraints).toBe("memberships_org_id_user_id_fkey,users_org_id_email_key");

    // Re-running the migration is idempotent and the schema guard reports 0 violations.
    test.setTimeout(5 * 60_000);
    for (let run = 0; run < 2; run++) {
      const migrate = spawnSync(process.execPath, ["scripts/dev.mjs", "migrate"], {
        cwd: ROOT,
        encoding: "utf8",
      });
      expect(migrate.status, migrate.stdout + migrate.stderr).toBe(0);
      expect(migrate.stdout + migrate.stderr).toContain(`database revision: ${REVISION}`);
      expect(migrate.stdout + migrate.stderr).toContain("schema guard: 0 violations");
    }
  });

  test("AC2: with context A, SELECT/UPDATE/DELETE of Organization B rows affects 0 rows", () => {
    const A = "aaaaaaaa-0000-4000-8000-00000000000a";
    const B = "bbbbbbbb-0000-4000-8000-00000000000b";
    const ctx = (org: string) => `select set_config('app.current_org','${org}',true);`;
    const sql = `
begin;
${ctx(A)}
insert into organizations(id,name) values ('${A}','QA Org A');
insert into users(org_id,email,display_name) values ('${A}','qa@example.invalid','QA A');
${ctx(B)}
insert into organizations(id,name) values ('${B}','QA Org B');
insert into users(org_id,email,display_name) values ('${B}','qa@example.invalid','QA B');
${ctx(A)}
\\echo VISIBLE_ORGS
select count(*) from organizations;
\\echo VISIBLE_B_ORG
select count(*) from organizations where id='${B}';
\\echo VISIBLE_B_USERS
select count(*) from users where org_id='${B}';
\\echo UPDATE_ORG
update organizations set name='hacked' where id='${B}';
\\echo UPDATE_USER
update users set display_name='hacked' where org_id='${B}';
\\echo DELETE_USER
delete from users where org_id='${B}';
\\echo DELETE_ORG
delete from organizations where id='${B}';
\\echo INSERT_FOR_B
insert into workspaces(org_id,name) values ('${B}','leak-probe-secret');
rollback;
`;
    const r = psql("ei_ai_app", sql, ["-v", "ON_ERROR_STOP=0"]);
    // -A -t prints command tags such as "UPDATE 0" on stderr-free stdout; errors go to stderr.
    const lines = r.out
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    const after = (marker: string) => lines[lines.indexOf(marker) + 1];
    expect(after("VISIBLE_ORGS")).toBe("1");
    expect(after("VISIBLE_B_ORG")).toBe("0");
    expect(after("VISIBLE_B_USERS")).toBe("0");
    expect(after("UPDATE_ORG")).toBe("UPDATE 0");
    expect(after("UPDATE_USER")).toBe("UPDATE 0");
    expect(after("DELETE_USER")).toBe("DELETE 0");
    expect(after("DELETE_ORG")).toBe("DELETE 0");
    // Writing a row for another Organization is rejected, and the error carries no row values.
    expect(r.err).toContain('new row violates row-level security policy for table "workspaces"');
    expect(r.err).not.toContain("leak-probe-secret");
    expect(r.err).not.toContain(B);
    // Nothing was committed. The database now also holds the demo and other Organizations (EA-21),
    // so only the ids of this test are checked.
    expect(
      scalar("postgres", `select count(*) from organizations where id in ('${A}','${B}')`),
    ).toBe("0");
  });

  test("AC3: with no tenant context every table returns 0 rows, also after a committed transaction", () => {
    for (const table of TABLES) {
      expect(scalar("ei_ai_app", `select count(*) from ${table}`)).toBe("0");
    }
    // A committed tenant transaction leaves '' behind on the connection; the policy (NULLIF) must still fail closed.
    const r = psql(
      "ei_ai_app",
      `begin; select set_config('app.current_org','${FORGED}',true); commit;
       select current_setting('app.current_org', true);
       select count(*) from organizations;`,
    );
    expect(r.status, r.err).toBe(0);
    const lines = r.out
      .replace(/\s+$/, "")
      .split("\n")
      .map((l) => l.trim());
    // set_config echoes its own value once; after the commit the leftover is '' (NULL) and 0 rows are visible.
    expect(lines.slice(-2)).toEqual(["", "0"]);

    // An insert without context is rejected without leaking the values.
    const insert = psql(
      "ei_ai_app",
      `begin; insert into organizations(name) values ('secret-name-xyz'); rollback;`,
    );
    expect(insert.err).toContain('violates row-level security policy for table "organizations"');
    expect(insert.err).not.toContain("secret-name-xyz");
  });

  test("AC4: GET /organization is 401 without a verified identity and ignores a forged org_id", async ({
    request,
  }) => {
    const expectUnauthenticated = async (url: string, headers: Record<string, string> = {}) => {
      const response = await request.get(url, { headers });
      expect(response.status(), url).toBe(401);
      expect(response.headers()["www-authenticate"]).toBe("Bearer");
      expect(await response.text()).toBe('{"detail":"unauthenticated"}');
    };
    await expectUnauthenticated(`${API_URL}/organization`);
    await expectUnauthenticated(`${API_URL}/organization?org_id=${FORGED}&tenant_id=${FORGED}`, {
      "X-Org-Id": FORGED,
      "X-Tenant-Id": FORGED,
    });
    await expectUnauthenticated(`${API_URL}/organization`, {
      Authorization: "Bearer not-a-real-token",
      "X-Organization-Id": FORGED,
    });
    // Through the admin reverse proxy (/api is stripped before the API).
    await expectUnauthenticated(`${ADMIN_URL}/api/organization?org_id=${FORGED}`, {
      "X-Org-Id": FORGED,
    });

    // The log has no stack trace, no credentials and never the forged value.
    const logs = execFileSync("docker", ["compose", "logs", "--no-color", "api"], {
      cwd: ROOT,
      encoding: "utf8",
    });
    expect(logs).not.toContain(FORGED);
    expect(logs).not.toMatch(/Traceback|ei_ai_migrator|password/i);

    // The route is documented in the OpenAPI schema with the 401 answer.
    const openapi = await (await request.get(`${API_URL}/openapi.json`)).json();
    expect(openapi.paths["/organization"].get.responses["401"]).toBeDefined();
    expect(JSON.stringify(openapi.paths["/organization"].get.parameters ?? [])).not.toMatch(
      /org_?id/i,
    );
  });

  test("AC5: the application role cannot bypass RLS, only the migration role owns objects", () => {
    const roles = scalar(
      "postgres",
      `select string_agg(rolname||':'||rolsuper::int||rolbypassrls::int||rolcreatedb::int||rolcreaterole::int, ',' order by rolname)
       from pg_roles where rolname like 'ei_ai%'`,
    );
    expect(roles).toBe("ei_ai_app:0000,ei_ai_migrator:0000,ei_ai_signin:0000");

    const owners = scalar(
      "postgres",
      `select string_agg(distinct tableowner, ',') from pg_tables where schemaname='public'`,
    );
    expect(owners).toBe("ei_ai_migrator");

    // The application role has only DML grants: no TRUNCATE, no REFERENCES, no TRIGGER, nothing on alembic_version.
    const privileges = scalar(
      "postgres",
      `select string_agg(distinct privilege_type, ',' order by privilege_type) from information_schema.role_table_grants
       where grantee='ei_ai_app' and table_schema='public'`,
    );
    expect(privileges).toBe("DELETE,INSERT,SELECT,UPDATE");
    // ... on each of the 12 tables, and on nothing else.
    const perTable = psql(
      "postgres",
      `select table_name || ':' || string_agg(privilege_type, ',' order by privilege_type)
       from information_schema.role_table_grants where grantee='ei_ai_app' and table_schema='public'
       group by table_name order by table_name`,
    )
      .out.trim()
      .split("\n");
    expect(perTable).toEqual(TABLES.map((table) => `${table}:DELETE,INSERT,SELECT,UPDATE`));
    expect(psql("ei_ai_app", "select * from alembic_version").err).toContain("permission denied");

    // EA-22: the sign-in role reads exactly three columns of users (the lookup before the tenant is known).
    expect(
      scalar(
        "postgres",
        `select count(*) from information_schema.role_table_grants where grantee='ei_ai_signin'`,
      ),
    ).toBe("0");
    expect(
      scalar(
        "postgres",
        `select string_agg(table_name || '.' || column_name || ':' || privilege_type, ',' order by table_name, column_name)
         from information_schema.column_privileges where grantee='ei_ai_signin' and table_schema='public'`,
      ),
    ).toBe("users.email:SELECT,users.id:SELECT,users.org_id:SELECT");
    expect(
      scalar(
        "postgres",
        `select count(*) from pg_auth_members m join pg_roles r on r.oid = m.member where r.rolname = 'ei_ai_signin'`,
      ),
    ).toBe("0");
    expect(
      scalar("postgres", `select count(*) from pg_class where relowner = 'ei_ai_signin'::regrole`),
    ).toBe("0");
    const lookup = psql(
      "ei_ai_signin",
      "select count(*) from (select id, email, org_id from users) t",
    );
    expect(lookup.status, lookup.err).toBe(0);
    expect(Number(lookup.out.trim())).toBeGreaterThan(0); // sees every Organization's rows, no tenant context
    for (const forbidden of [
      "select display_name from users",
      "select * from users",
      "select count(*) from user_credentials",
      "select count(*) from admin_sessions",
      "select count(*) from organizations",
      "update users set email = email",
    ]) {
      expect(psql("ei_ai_signin", forbidden).err, forbidden).toContain("permission denied");
    }

    // No DDL for the application role.
    expect(psql("ei_ai_app", "create table probe (id int)").err).toContain(
      "permission denied for schema public",
    );

    // The API container holds the application credentials only.
    const env = execFileSync("docker", ["compose", "exec", "-T", "api", "env"], {
      cwd: ROOT,
      encoding: "utf8",
    });
    expect(env).toMatch(/^DATABASE_URL=postgresql:\/\/ei_ai_app:/m);
    expect(env).not.toMatch(/MIGRATION_|ei_ai_migrator|POSTGRES_PASSWORD/);

    // The one-shot migrate service is not left running.
    const ps = execFileSync("docker", ["compose", "ps", "--services", "--status", "running"], {
      cwd: ROOT,
      encoding: "utf8",
    });
    expect(ps.split("\n")).not.toContain("migrate");
  });

  test("NFR: RLS overhead on a 100k-row table is within 1 ms or 10 %", { tag: "@perf" }, () => {
    test.setTimeout(5 * 60_000);
    const bench = spawnSync(process.execPath, ["scripts/backend.mjs", "bench-rls"], {
      cwd: ROOT,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    });
    const output = bench.stdout + bench.stderr;
    expect(bench.status, output.slice(-3000)).toBe(0);
    expect(output).toContain("100000 rows");
    expect(output).toContain("1 passed");
  });
});
