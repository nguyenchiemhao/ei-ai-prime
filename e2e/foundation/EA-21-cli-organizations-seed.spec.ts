// EA-21 (FND-04): Platform Operator CLI (org create, workspace create, user invite, user link) and the
// Mekong Devworks demo seed. Profile api, no browser.
// Runs against a running, migrated and seeded stack:
//   npm run up && npm run seed && npx playwright test e2e/foundation/EA-21-*
// Every test that creates Organizations uses a unique suffix in the names and deletes its rows afterwards
// as the database superuser, children first (RLS is never altered).
import { spawnSync } from "node:child_process";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { adminUrl } from "../../scripts/lib/admin-url.mjs";

const DEMO_ORG = "0192a000-0000-7000-8000-00000000ea21";
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const SEED_REFUSED = "refused: the demo seed runs only in local or test environments";
const LEAKS = /Key \(|Traceback|SELECT|INSERT|postgresql:\/\//;

// Children first; the order is also the order of the global count snapshot.
const TABLES_CHILD_FIRST = [
  "audit_events",
  "set_password_tokens",
  "workspace_memberships",
  "memberships",
  "users",
  "workspaces",
  "organizations",
];

const ERR = {
  orgName: "error: Organization name must be 1-200 characters",
  orgExists: "error: an Organization with this name already exists",
  email: "error: invalid email address",
  displayName: "error: display name must be 1-200 characters",
  workspaceName: "error: Workspace name must be 1-200 characters",
  workspaceExists: "error: a Workspace with this name already exists in this Organization",
  orgId: "error: --org must be an Organization id (UUID)",
  orgNotFound: "error: Organization not found",
  workspaceId: "error: --workspace must be a Workspace id (UUID)",
  workspaceNotFound: "error: Workspace not found in this Organization",
  unknownRole: (role: string) =>
    `error: unknown role "${role}"; valid roles: org_owner, org_admin, workspace_admin, developer, builder, knowledge_editor, reviewer, viewer, member`,
  tooManyRoles: "error: give at most one Organization role and one Workspace role",
  workspaceRoleNeedsWorkspace: "error: a Workspace role needs --workspace",
  workspaceNeedsRole: "error: --workspace needs a Workspace role",
  userExists: "error: a user with this email already exists in this Organization",
  userNotFound: "error: user not found in this Organization",
};

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

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// The admin base URL of the running stack (ADMIN_URL, else ADMIN_PORT from the shell or .env, else 3000):
// the CLI prints links on the same base. The token travels in the URL fragment, never in a query string.
const ADMIN = adminUrl(ROOT, process.env);
const ADMIN_RE = escapeRegExp(ADMIN);
const LINK_LINE = new RegExp(
  `^Set-password link \\(valid 24 h, shown once\\): ${ADMIN_RE}/set-password#token=(${UUID})\\.([A-Za-z0-9_-]{43})$`,
);
const SEED_LINK_LINE = new RegExp(
  `^ {4}- (\\S+): ${ADMIN_RE}/set-password#token=(${UUID})\\.([A-Za-z0-9_-]{43})$`,
);

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

/** `docker compose exec -T api ei-ai <args>`; `env` entries become `-e KEY=VALUE`. */
function cli(args: string[], env: Record<string, string> = {}): Run {
  const envArgs = Object.entries(env).flatMap(([key, value]) => ["-e", `${key}=${value}`]);
  return spawn("docker", ["compose", "exec", "-T", ...envArgs, "api", "ei-ai", ...args]);
}

/** `npm run seed` without npm: the same script the EA-13 spec uses. */
function seed(): Run {
  return spawn(process.execPath, ["scripts/dev.mjs", "seed"]);
}

/** Read-only or cleanup SQL as the database superuser (bypasses RLS); returns trimmed stdout. */
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

function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

type Counts = Record<string, number>;

/** Row count of every tenant table; `orgId` limits it to one Organization, else it is global. */
function counts(orgId?: string): Counts {
  const parts = TABLES_CHILD_FIRST.map((table) => {
    const filter =
      orgId === undefined
        ? ""
        : table === "organizations"
          ? ` where id = '${orgId}'`
          : ` where org_id = '${orgId}'`;
    return `select '${table}', count(*) from ${table}${filter}`;
  });
  const result: Counts = {};
  for (const row of rows(parts.join(" union all "))) {
    const [table, count] = row.split("|");
    result[table as string] = Number(count);
  }
  return result;
}

/** Deletes one Organization and everything under it, children first. */
function purgeOrg(orgId: string): void {
  expect(orgId).toMatch(new RegExp(`^${UUID}$`));
  // EA-22: sessions and credentials of users (created by sign-in tests) reference users; they go first.
  const byOrg = [
    "admin_sessions",
    "user_credentials",
    ...TABLES_CHILD_FIRST.filter((t) => t !== "organizations"),
  ].map((table) => `delete from ${table} where org_id = '${orgId}';`);
  sql(`begin; ${byOrg.join(" ")} delete from organizations where id = '${orgId}'; commit;`);
}

/** Cleanup for tests that put their random suffix into every Organization name they create. */
function purgeBySuffix(sfx: string): void {
  const ids = rows(`select id from organizations where position('${sfx}' in lower(name)) > 0`);
  for (const id of ids) purgeOrg(id);
}

function orgIdsBySuffix(sfx: string): string[] {
  return rows(`select id from organizations where position('${sfx}' in lower(name)) > 0`);
}

function expectCliError(result: Run, message: string, status = 1): void {
  expect(result.stdout.trim(), "stdout of a failed command").toBe("");
  expect(lines(result.stderr)).toEqual([message]);
  expect(result.status).toBe(status);
  expect(result.stderr).not.toMatch(LEAKS);
}

/** argparse usage error: exit 2, empty stdout; `missing` is the flag list argparse reports. */
function expectUsageError(result: Run, missing?: string): void {
  expect(result.status).toBe(2);
  expect(result.stdout.trim()).toBe("");
  expect(result.stderr.toLowerCase()).toContain("usage");
  if (missing !== undefined) {
    expect(result.stderr).toContain(`error: the following arguments are required: ${missing}`);
  }
}

type Link = { orgId: string; secret: string };

function parseLinkLine(line: string | undefined): Link {
  const match = LINK_LINE.exec(line ?? "");
  expect(match, `not a set-password link line: ${line}`).not.toBeNull();
  return { orgId: match?.[1] as string, secret: match?.[2] as string };
}

type CreatedOrg = {
  orgId: string;
  workspaceId: string;
  ownerId: string;
  link: Link;
  run: Run;
};

/** Runs `org create` successfully and parses the four output lines. */
function createOrg(name: string, owner: string, extra: string[] = []): CreatedOrg {
  const run = cli(["org", "create", "--name", name, "--owner", owner, ...extra]);
  expect(run.status, run.stderr).toBe(0);
  const out = lines(run.stdout);
  expect(out).toHaveLength(4);
  const org = new RegExp(`^Organization created: (${UUID}) \\(.*\\)$`).exec(out[0] as string);
  const workspace = new RegExp(`^Workspace created: (${UUID}) \\(.*\\)$`).exec(out[1] as string);
  const user = new RegExp(`^Org Owner created: (${UUID}) \\(.*\\)$`).exec(out[2] as string);
  expect(org, out[0]).not.toBeNull();
  expect(workspace, out[1]).not.toBeNull();
  expect(user, out[2]).not.toBeNull();
  return {
    orgId: org?.[1] as string,
    workspaceId: workspace?.[1] as string,
    ownerId: user?.[1] as string,
    link: parseLinkLine(out[3]),
    run,
  };
}

function eventSet(orgId: string): string[] {
  return rows(
    `select actor || '|' || action || '|' || target_type || '|' || target_id
     from audit_events where org_id = '${orgId}'`,
  ).sort();
}

function demoCounts(): Counts {
  return counts(DEMO_ORG);
}

test.describe("EA-21 Platform Operator CLI and demo seed", () => {
  test.setTimeout(180_000);

  test("AC1: org create creates the org, a default workspace and the Org Owner and prints a one-time link valid 24 h", async ({
    request,
  }) => {
    const sfx = suffix();
    const name = `QA EA-21 ${sfx}`;
    try {
      const created = createOrg(name, `Owner.${sfx}@Example.com`);
      const out = lines(created.run.stdout);
      const email = `owner.${sfx}@example.com`;

      expect(out[0]).toBe(`Organization created: ${created.orgId} (${name})`);
      expect(out[1]).toBe(`Workspace created: ${created.workspaceId} (Default)`);
      expect(out[2]).toBe(`Org Owner created: ${created.ownerId} (${email})`);
      expect(created.link.orgId).toBe(created.orgId);
      expect(created.link.secret).toHaveLength(43);

      const org = created.orgId;
      expect(counts(org)).toEqual({
        audit_events: 3,
        set_password_tokens: 1,
        workspace_memberships: 1,
        memberships: 1,
        users: 1,
        workspaces: 1,
        organizations: 1,
      });
      expect(rows(`select id || '|' || name from organizations where id = '${org}'`)).toEqual([
        `${org}|${name}`,
      ]);
      expect(rows(`select id || '|' || name from workspaces where org_id = '${org}'`)).toEqual([
        `${created.workspaceId}|Default`,
      ]);
      // The email is stored lowercased; the display name defaults to the email local part.
      expect(
        rows(`select id || '|' || email || '|' || display_name from users where org_id = '${org}'`),
      ).toEqual([`${created.ownerId}|${email}|owner.${sfx}`]);
      expect(rows(`select org_role from memberships where org_id = '${org}'`)).toEqual([
        "org_owner",
      ]);
      expect(rows(`select role from workspace_memberships where org_id = '${org}'`)).toEqual([
        "workspace_admin",
      ]);

      // One unused token valid for exactly 24 h; only the sha256 of the secret is stored.
      expect(
        rows(
          `select (used_at is null) || '|' || (expires_at - created_at = interval '24 hours')
                  || '|' || (token_hash = '${sha256Hex(created.link.secret)}')
                  || '|' || (token_hash = encode(sha256(convert_to('${created.link.secret}','UTF8')),'hex'))
           from set_password_tokens where org_id = '${org}'`,
        ),
      ).toEqual(["true|true|true|true"]);
      expect(
        sql(`select count(*) from set_password_tokens where token_hash = '${created.link.secret}'`),
      ).toBe("0");
      // The raw secret is in no row of any tenant table (whole-row text search).
      const dump = TABLES_CHILD_FIRST.map(
        (table) => `select row_to_json(t)::text as j from ${table} t`,
      ).join(" union all ");
      expect(
        sql(`select count(*) from (${dump}) x where position('${created.link.secret}' in j) > 0`),
      ).toBe("0");

      // The link keeps the token in the fragment: no query string at all.
      const linkUrl = (lines(created.run.stdout)[3] as string).split(": ").slice(1).join(": ");
      expect(linkUrl).toBe(`${ADMIN}/set-password#token=${created.orgId}.${created.link.secret}`);
      expect(linkUrl).not.toContain("?");
      expect(linkUrl.split("#")).toHaveLength(2);

      // The secret never reaches the API container's log.
      const apiLogs = spawn("docker", ["compose", "logs", "--no-color", "api"]).stdout;
      expect(apiLogs).not.toContain(created.link.secret);
      // EA-22: the only line allowed to carry a token is the local-only "Reset link" line of forgot-password.
      const tokenLines = lines(apiLogs).filter((line) => line.includes("token="));
      expect(
        tokenLines.filter((line) => !line.includes("Reset link (valid 24 h, shown once)")),
      ).toEqual([]);

      // Requesting the printed link: a fragment is never sent, so the admin (nginx) log has the
      // request line without the secret and without "token=".
      await request.get(linkUrl, { failOnStatusCode: false });
      const adminLogs = spawn("docker", ["compose", "logs", "--no-color", "admin"]).stdout;
      expect(adminLogs, "the request reached the admin container").toContain("/set-password");
      expect(adminLogs).not.toContain(created.link.secret);
      expect(adminLogs).not.toContain("token=");
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC1 TC-1-2: names are trimmed, options are honoured, the email is lowercased and trimmed", async () => {
    const sfx = suffix();
    try {
      const created = createOrg(`  QA EA-21 ${sfx}  `, `  Owner+QA.${sfx}@Example.com `, [
        "--owner-name",
        "  Owner QA  ",
        "--workspace-name",
        "  QA Workspace  ",
      ]);
      const out = lines(created.run.stdout);
      expect(out[0]).toBe(`Organization created: ${created.orgId} (QA EA-21 ${sfx})`);
      expect(out[1]).toBe(`Workspace created: ${created.workspaceId} (QA Workspace)`);
      expect(out[2]).toBe(`Org Owner created: ${created.ownerId} (owner+qa.${sfx}@example.com)`);
      expect(rows(`select name from organizations where id = '${created.orgId}'`)).toEqual([
        `QA EA-21 ${sfx}`,
      ]);
      expect(rows(`select name from workspaces where org_id = '${created.orgId}'`)).toEqual([
        "QA Workspace",
      ]);
      expect(
        rows(`select email || '|' || display_name from users where org_id = '${created.orgId}'`),
      ).toEqual([`owner+qa.${sfx}@example.com|Owner QA`]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC1 TC-1-3: Vietnamese names with diacritics are stored and printed unchanged", async () => {
    const sfx = suffix();
    const name = `Công ty Mê Kông ${sfx}`;
    try {
      const created = createOrg(name, `tran.linh.${sfx}@example.com`, [
        "--owner-name",
        "Trần Thị Linh",
        "--workspace-name",
        "Phòng Nhân sự",
      ]);
      const out = lines(created.run.stdout);
      expect(out[0]).toBe(`Organization created: ${created.orgId} (${name})`);
      expect(out[1]).toBe(`Workspace created: ${created.workspaceId} (Phòng Nhân sự)`);
      expect(rows(`select name from organizations where id = '${created.orgId}'`)).toEqual([name]);
      expect(rows(`select name from workspaces where org_id = '${created.orgId}'`)).toEqual([
        "Phòng Nhân sự",
      ]);
      expect(rows(`select display_name from users where org_id = '${created.orgId}'`)).toEqual([
        "Trần Thị Linh",
      ]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC1 TC-1-4: an Organization name of exactly 200 characters is accepted", async () => {
    const sfx = suffix();
    const prefix = `QA EA-21 ${sfx} `;
    const name = prefix + "x".repeat(200 - prefix.length);
    expect(name).toHaveLength(200);
    try {
      const created = createOrg(name, `long.${sfx}@example.com`);
      expect(
        rows(`select char_length(name) from organizations where id = '${created.orgId}'`),
      ).toEqual(["200"]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC1 TC-1-5: the link base URL comes from ADMIN_BASE_URL (trailing slash removed)", async () => {
    const sfx = suffix();
    try {
      const run = cli(
        ["org", "create", "--name", `QA EA-21 ${sfx}`, "--owner", `o.${sfx}@example.com`],
        {
          ADMIN_BASE_URL: "https://admin.example.test/",
        },
      );
      expect(run.status, run.stderr).toBe(0);
      const link = lines(run.stdout)[3] as string;
      expect(link).toMatch(
        new RegExp(
          `^Set-password link \\(valid 24 h, shown once\\): https://admin\\.example\\.test/set-password#token=${UUID}\\.[A-Za-z0-9_-]{43}$`,
        ),
      );
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC1 TC-1-6: migration 0002 tables have the contract columns", async () => {
    const columns = (table: string) =>
      rows(
        `select column_name from information_schema.columns
         where table_schema = 'public' and table_name = '${table}' order by ordinal_position`,
      );
    expect(columns("set_password_tokens")).toEqual([
      "id",
      "org_id",
      "user_id",
      "token_hash",
      "expires_at",
      "used_at",
      "created_at",
    ]);
    expect(columns("audit_events")).toEqual([
      "id",
      "org_id",
      "actor",
      "action",
      "target_type",
      "target_id",
      "created_at",
    ]);
  });

  test("AC2: duplicate org name or malformed email prints a clear error, exits 1 and changes no row", async () => {
    const sfx = suffix();
    const unique = `QA EA-21 ${sfx}`;
    try {
      const before = counts();
      const mekong = () =>
        sql("select count(*) from organizations where lower(name) = 'mekong devworks'");
      expect(mekong(), "precondition: the stack is seeded").toBe("1");

      // (a) The literal command of AC1 on the seeded stack is a duplicate.
      expectCliError(
        cli([
          "org",
          "create",
          "--name",
          "Mekong Devworks",
          "--owner",
          "linh.tran@mekongdevworks.example",
        ]),
        ERR.orgExists,
      );
      expect(counts()).toEqual(before);

      // (b) Case and surrounding spaces do not make a different name.
      expectCliError(
        cli(["org", "create", "--name", " mekong devworks ", "--owner", `a.${sfx}@example.com`]),
        ERR.orgExists,
      );
      expect(counts()).toEqual(before);
      expect(mekong()).toBe("1");

      // (c) and (d) Malformed owner email.
      for (const owner of ["not-an-email", "a b@c.example"]) {
        expectCliError(cli(["org", "create", "--name", unique, "--owner", owner]), ERR.email);
        expect(counts()).toEqual(before);
        expect(orgIdsBySuffix(sfx)).toEqual([]);
      }
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-3: a case and space variant of a just-created name is a duplicate", async () => {
    const sfx = suffix();
    try {
      const first = createOrg(`QA EA-21 ${sfx}`, `a.${sfx}@example.com`);
      const before = counts();
      expectCliError(
        cli([
          "org",
          "create",
          "--name",
          ` qa ea-21 ${sfx.toUpperCase()} `,
          "--owner",
          `b.${sfx}@example.com`,
        ]),
        ERR.orgExists,
      );
      expect(counts()).toEqual(before);
      expect(orgIdsBySuffix(sfx)).toEqual([first.orgId]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-4: invalid owner emails, empty or too long names are rejected without writing", async () => {
    const sfx = suffix();
    const unique = `QA EA-21 ${sfx}`;
    try {
      const before = counts();
      for (const owner of [
        "a@b",
        "a@@b.example",
        "linh@",
        "@example.com",
        "",
        `${"a".repeat(65)}@example.com`,
      ]) {
        expectCliError(cli(["org", "create", "--name", unique, "--owner", owner]), ERR.email);
      }
      for (const badName of ["", "   ", "x".repeat(201)]) {
        expectCliError(
          cli(["org", "create", "--name", badName, "--owner", `o.${sfx}@example.com`]),
          ERR.orgName,
        );
      }
      expectCliError(
        cli([
          "org",
          "create",
          "--name",
          unique,
          "--owner",
          `o.${sfx}@example.com`,
          "--owner-name",
          "",
        ]),
        ERR.displayName,
      );
      expectCliError(
        cli([
          "org",
          "create",
          "--name",
          unique,
          "--owner",
          `o.${sfx}@example.com`,
          "--workspace-name",
          "  ",
        ]),
        ERR.workspaceName,
      );
      expect(counts()).toEqual(before);
      expect(orgIdsBySuffix(sfx)).toEqual([]);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-5: usage errors exit 2 and write nothing", async () => {
    const before = counts();
    const id = randomUUID();
    const cases: [string[], string | undefined][] = [
      [["org", "create", "--owner", "a@example.com"], "--name"],
      [["org", "create", "--name", "QA EA-21 missing owner"], "--owner"],
      [["workspace", "create", "--name", "x"], "--org"],
      [["workspace", "create", "--org", id], "--name"],
      [["user", "invite", "--org", id, "--email", "a@example.com"], "--role"],
      [["user", "invite", "--org", id, "--role", "org_admin"], "--email"],
      [["user", "invite", "--email", "a@example.com", "--role", "org_admin"], "--org"],
      [["user", "link", "--email", "a@example.com"], "--org"],
      [["user", "link", "--org", id], "--email"],
      [["org", "frobnicate"], undefined],
      [["nonsense"], undefined],
    ];
    for (const [args, missing] of cases) {
      expectUsageError(cli(args), missing);
    }
    // Several flags missing at once: all of them are named.
    const none = cli(["org", "create"]);
    expectUsageError(none);
    expect(none.stderr).toContain("error: the following arguments are required:");
    expect(none.stderr).toContain("--name");
    expect(none.stderr).toContain("--owner");
    expect(counts()).toEqual(before);
  });

  test("AC2 TC-2-6: workspace, invite and link validation errors are exact and write nothing", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(`QA EA-21 ${sfx}`, `owner.${sfx}@example.com`);
      const demoUserEmail = rows(`select email from users where org_id = '${DEMO_ORG}' limit 1`)[0];
      expect(demoUserEmail, "precondition: demo users exist").toBeTruthy();
      const before = counts();
      const ghost = randomUUID();
      const invite = (...args: string[]) => cli(["user", "invite", "--org", org.orgId, ...args]);
      const email = `member.${sfx}@example.com`;

      expectCliError(cli(["workspace", "create", "--org", "not-a-uuid", "--name", "W"]), ERR.orgId);
      expectCliError(cli(["workspace", "create", "--org", ghost, "--name", "W"]), ERR.orgNotFound);
      expectCliError(
        cli(["workspace", "create", "--org", org.orgId, "--name", "   "]),
        ERR.workspaceName,
      );
      expectCliError(
        cli(["workspace", "create", "--org", org.orgId, "--name", "Default"]),
        ERR.workspaceExists,
      );
      expectCliError(
        cli(["user", "invite", "--org", "nope", "--email", email, "--role", "org_admin"]),
        ERR.orgId,
      );
      expectCliError(
        cli(["user", "invite", "--org", ghost, "--email", email, "--role", "org_admin"]),
        ERR.orgNotFound,
      );
      expectCliError(invite("--email", "a@b", "--role", "org_admin"), ERR.email);
      expectCliError(
        invite("--email", email, "--role", "org_admin", "--name", ""),
        ERR.displayName,
      );
      expectCliError(
        invite("--email", email, "--role", "superadmin"),
        ERR.unknownRole("superadmin"),
      );
      expectCliError(
        invite("--email", email, "--role", "org_owner", "--role", "org_admin"),
        ERR.tooManyRoles,
      );
      expectCliError(
        invite(
          "--email",
          email,
          "--role",
          "builder",
          "--role",
          "viewer",
          "--workspace",
          org.workspaceId,
        ),
        ERR.tooManyRoles,
      );
      expectCliError(
        invite("--email", email, "--role", "builder"),
        ERR.workspaceRoleNeedsWorkspace,
      );
      expectCliError(
        invite("--email", email, "--role", "org_admin", "--workspace", org.workspaceId),
        ERR.workspaceNeedsRole,
      );
      expectCliError(
        invite("--email", email, "--role", "builder", "--workspace", "nope"),
        ERR.workspaceId,
      );
      expectCliError(
        invite("--email", email, "--role", "builder", "--workspace", ghost),
        ERR.workspaceNotFound,
      );
      // Emails are unique per Organization, case-insensitively.
      expectCliError(
        invite("--email", `OWNER.${sfx}@EXAMPLE.com`, "--role", "org_admin"),
        ERR.userExists,
      );
      expectCliError(cli(["user", "link", "--org", "nope", "--email", email]), ERR.orgId);
      expectCliError(cli(["user", "link", "--org", ghost, "--email", email]), ERR.orgNotFound);
      expectCliError(cli(["user", "link", "--org", org.orgId, "--email", email]), ERR.userNotFound);
      // An email that exists only in another Organization is not found here either.
      expectCliError(
        cli(["user", "link", "--org", org.orgId, "--email", demoUserEmail as string]),
        ERR.userNotFound,
      );

      expect(counts()).toEqual(before);
      expect(eventSet(org.orgId)).toHaveLength(3);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-7: a database error prints the exception class only, never SQL or the connection string", async () => {
    const sfx = suffix();
    try {
      const before = counts();
      const run = cli(
        ["org", "create", "--name", `QA EA-21 ${sfx}`, "--owner", `o.${sfx}@example.com`],
        {
          DATABASE_URL: "postgresql://ei_ai_app:Sup3rS3cretPw@127.0.0.1:1/ei_ai",
        },
      );
      expect(run.status).toBe(1);
      expect(run.stdout.trim()).toBe("");
      expect(lines(run.stderr)).toHaveLength(1);
      expect(run.stderr.trim()).toMatch(/^error: org create failed \(\w+\)$/);
      expect(run.stderr).not.toContain("Sup3rS3cretPw");
      expect(run.stderr).not.toMatch(LEAKS);
      expect(counts()).toEqual(before);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-8: configuration errors are exact, checked before any write", async () => {
    const sfx = suffix();
    const production = { EI_AI_ENV: "production", ADMIN_BASE_URL: "" };
    const required = "configuration error: ADMIN_BASE_URL is required";
    try {
      const org = createOrg(`QA EA-21 ${sfx}`, `owner.${sfx}@example.com`);
      const before = counts();
      const eventsBefore = eventSet(org.orgId);

      expectCliError(
        cli(["org", "create", "--name", `QA EA-21 bad ${sfx}`, "--owner", `o.${sfx}@example.com`], {
          ADMIN_BASE_URL: "ftp://admin.example.test",
        }),
        "configuration error: ADMIN_BASE_URL must be an http or https URL",
      );

      // Production without ADMIN_BASE_URL: the three commands that print a link refuse, with no row
      // and no audit event.
      expectCliError(
        cli(
          ["org", "create", "--name", `QA EA-21 prod ${sfx}`, "--owner", `p.${sfx}@example.com`],
          production,
        ),
        required,
      );
      expectCliError(
        cli(
          [
            "user",
            "invite",
            "--org",
            org.orgId,
            "--email",
            `i.${sfx}@example.com`,
            "--role",
            "org_admin",
          ],
          production,
        ),
        required,
      );
      expectCliError(
        cli(
          ["user", "link", "--org", org.orgId, "--email", `owner.${sfx}@example.com`],
          production,
        ),
        required,
      );
      expect(counts()).toEqual(before);
      expect(eventSet(org.orgId)).toEqual(eventsBefore);
      expect(orgIdsBySuffix(sfx)).toEqual([org.orgId]);
      // The refused link command did not replace the owner's token.
      expect(
        rows(
          `select token_hash from set_password_tokens where org_id = '${org.orgId}' and used_at is null`,
        ),
      ).toEqual([sha256Hex(org.link.secret)]);

      // workspace create never prints a link and does not read ADMIN_BASE_URL.
      const workspace = cli(
        ["workspace", "create", "--org", org.orgId, "--name", `Prod ${sfx}`],
        production,
      );
      expect(workspace.status, workspace.stderr).toBe(0);
      expect(lines(workspace.stdout)).toHaveLength(1);
      expect(lines(workspace.stdout)[0]).toMatch(
        new RegExp(`^Workspace created: ${UUID} \\(Prod ${sfx}\\)$`),
      );
      expect(eventSet(org.orgId)).toHaveLength(eventsBefore.length + 1);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC2 TC-2-9: Organization names are unique platform-wide through a lower(name) unique index", async () => {
    const definition = rows(
      "select indexdef from pg_indexes where indexname = 'organizations_name_lower_key'",
    );
    expect(definition).toHaveLength(1);
    expect(definition[0]).toMatch(
      /UNIQUE INDEX organizations_name_lower_key ON public\.organizations/,
    );
    expect(definition[0]).toContain("lower(");
  });

  test("AC3: seed demo twice leaves every row count unchanged", async () => {
    const warmUp = seed();
    expect(warmUp.status, warmUp.stderr).toBe(0);
    const before = demoCounts();
    const auditTotal = counts().audit_events;
    expect(before).toMatchObject({
      organizations: 1,
      workspaces: 1,
      users: 6,
      memberships: 6,
      workspace_memberships: 6,
    });
    const roles = rows(
      `select role from workspace_memberships where org_id = '${DEMO_ORG}'`,
    ).sort();
    expect(roles).toEqual(
      ["builder", "developer", "knowledge_editor", "reviewer", "viewer", "workspace_admin"].sort(),
    );
    expect(
      rows(
        `select org_role from memberships where org_id = '${DEMO_ORG}' and org_role is not null`,
      ),
    ).toEqual(["org_admin"]);
    expect(rows(`select display_name from users where org_id = '${DEMO_ORG}'`).sort()).toEqual(
      ["Hà Vũ", "Linh Tran", "Minh Pham", "Quang Le", "Son Hoang", "Thao Nguyen"].sort(),
    );

    const first = seed();
    const second = seed();
    expect(first.status, first.stderr).toBe(0);
    expect(second.status, second.stderr).toBe(0);
    expect(second.stdout).toBe(first.stdout);
    expect(first.stdout).toContain("Demo seed: Mekong Devworks");
    expect(first.stdout).toContain(`Organization: Mekong Devworks (${DEMO_ORG}): already present`);
    expect(first.stdout).toMatch(
      new RegExp(`Workspace: People Ops \\(${UUID}\\): already present`),
    );
    expect(first.stdout).toContain("Members: 6");
    expect(first.stdout).toContain("Audit events written: 0");
    expect(first.stdout).toContain(
      'Set-password links: none (no member was created; use "ei-ai user link" for a new link)',
    );
    expect(first.stdout).not.toContain(": created");
    expect(first.stdout).not.toContain("#token=");
    expect(lines(first.stdout).filter((line) => line.endsWith(": already present"))).toHaveLength(
      8,
    );

    expect(demoCounts()).toEqual(before);
    expect(counts().audit_events).toBe(auditTotal);
    expect(sql("select count(*) from organizations where lower(name) = 'mekong devworks'")).toBe(
      "1",
    );
  });

  test("AC3 TC-3-2: a fresh load creates everything once and prints one link per member", async () => {
    const warmUp = seed();
    expect(warmUp.status, warmUp.stderr).toBe(0);
    purgeOrg(DEMO_ORG);
    expect(demoCounts().organizations).toBe(0);

    const fresh = seed();
    expect(fresh.status, fresh.stderr).toBe(0);
    expect(fresh.stdout).toContain(`Organization: Mekong Devworks (${DEMO_ORG}): created`);
    expect(fresh.stdout).toMatch(new RegExp(`Workspace: People Ops \\(${UUID}\\): created`));
    expect(fresh.stdout).toContain("Members: 6");
    expect(fresh.stdout).toContain("Audit events written: 8");
    expect(lines(fresh.stdout).filter((line) => line.endsWith(": created"))).toHaveLength(8);
    expect(fresh.stdout).toContain("Set-password links (valid 24 h, shown once):");

    const links = lines(fresh.stdout)
      .map((line) => SEED_LINK_LINE.exec(line))
      .filter((match): match is RegExpExecArray => match !== null);
    expect(links).toHaveLength(6);
    expect(new Set(links.map((match) => match[1])).size).toBe(6);
    expect(new Set(links.map((match) => match[3])).size).toBe(6);
    for (const match of links) {
      expect(match[2]).toBe(DEMO_ORG);
      expect(
        sql(
          `select count(*) from set_password_tokens where org_id = '${DEMO_ORG}'
           and used_at is null and token_hash = '${sha256Hex(match[3] as string)}'`,
        ),
      ).toBe("1");
    }

    const afterFirst = demoCounts();
    expect(afterFirst).toEqual({
      audit_events: 8,
      set_password_tokens: 6,
      workspace_memberships: 6,
      memberships: 6,
      users: 6,
      workspaces: 1,
      organizations: 1,
    });
    expect(
      rows(
        `select action || '|' || count(*) from audit_events where org_id = '${DEMO_ORG}' group by action`,
      ).sort(),
    ).toEqual(["organization.created|1", "user.invited|6", "workspace.created|1"]);
    expect(rows(`select distinct actor from audit_events where org_id = '${DEMO_ORG}'`)).toEqual([
      "platform-operator",
    ]);

    // A second run changes nothing and issues no new token.
    const again = seed();
    expect(again.status, again.stderr).toBe(0);
    expect(again.stdout).toContain("Audit events written: 0");
    expect(again.stdout).not.toContain(": created");
    expect(demoCounts()).toEqual(afterFirst);
  });

  test("AC4: every CLI command writes its audit events with actor platform-operator, action and target", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(`QA EA-21 ${sfx}`, `owner.${sfx}@example.com`);
      const orgId = org.orgId;

      const secondWs = cli(["workspace", "create", "--org", orgId, "--name", `Second ${sfx}`]);
      expect(secondWs.status, secondWs.stderr).toBe(0);
      const wsMatch = new RegExp(`^Workspace created: (${UUID}) \\(Second ${sfx}\\)$`).exec(
        lines(secondWs.stdout)[0] as string,
      );
      expect(lines(secondWs.stdout)).toHaveLength(1);
      expect(wsMatch).not.toBeNull();
      const secondWsId = wsMatch?.[1] as string;

      const builderEmail = `builder.${sfx}@example.com`;
      const builderRun = cli([
        "user",
        "invite",
        "--org",
        orgId,
        "--email",
        builderEmail,
        "--role",
        "builder",
        "--workspace",
        secondWsId,
      ]);
      expect(builderRun.status, builderRun.stderr).toBe(0);
      const builderOut = lines(builderRun.stdout);
      expect(builderOut).toHaveLength(2);
      const builderMatch = new RegExp(
        `^User invited: (${UUID}) \\(${builderEmail.replace(/\./g, "\\.")}\\) roles: builder$`,
      ).exec(builderOut[0] as string);
      expect(builderMatch, builderOut[0]).not.toBeNull();
      const builderId = builderMatch?.[1] as string;
      const builderLink1 = parseLinkLine(builderOut[1]);
      expect(builderLink1.orgId).toBe(orgId);

      const adminEmail = `admin.${sfx}@example.com`;
      const adminRun = cli([
        "user",
        "invite",
        "--org",
        orgId,
        "--email",
        adminEmail,
        "--role",
        "org_admin",
      ]);
      expect(adminRun.status, adminRun.stderr).toBe(0);
      const adminOut = lines(adminRun.stdout);
      expect(adminOut).toHaveLength(2);
      const adminMatch = new RegExp(
        `^User invited: (${UUID}) \\(${adminEmail.replace(/\./g, "\\.")}\\) roles: org_admin$`,
      ).exec(adminOut[0] as string);
      expect(adminMatch, adminOut[0]).not.toBeNull();
      const adminId = adminMatch?.[1] as string;
      const adminLink = parseLinkLine(adminOut[1]);

      const linkRun = cli(["user", "link", "--org", orgId, "--email", builderEmail]);
      expect(linkRun.status, linkRun.stderr).toBe(0);
      expect(lines(linkRun.stdout)).toHaveLength(1);
      const builderLink2 = parseLinkLine(lines(linkRun.stdout)[0]);
      expect(builderLink2.orgId).toBe(orgId);

      // One failing command adds no event and no row.
      const before = counts();
      expectCliError(
        cli(["workspace", "create", "--org", orgId, "--name", `Second ${sfx}`]),
        ERR.workspaceExists,
      );
      expect(counts()).toEqual(before);

      const expected = [
        `platform-operator|organization.created|organization|${orgId}`,
        `platform-operator|workspace.created|workspace|${org.workspaceId}`,
        `platform-operator|user.invited|user|${org.ownerId}`,
        `platform-operator|workspace.created|workspace|${secondWsId}`,
        `platform-operator|user.invited|user|${builderId}`,
        `platform-operator|user.invited|user|${adminId}`,
        `platform-operator|user.set_password_link_issued|user|${builderId}`,
      ].sort();
      expect(eventSet(orgId)).toEqual(expected);
      expect(eventSet(orgId)).toHaveLength(7);

      // No audit column holds an email, a secret or a name.
      const auditText = rows(
        `select row_to_json(a)::text from audit_events a where org_id = '${orgId}'`,
      ).join("\n");
      for (const forbidden of [
        "@",
        sfx,
        org.link.secret,
        builderLink1.secret,
        builderLink2.secret,
        adminLink.secret,
      ]) {
        expect(auditText).not.toContain(forbidden);
      }

      // A new link replaces that user's unused token and nobody else's.
      expect(
        new Set([org.link.secret, builderLink1.secret, builderLink2.secret, adminLink.secret]).size,
      ).toBe(4);
      const unused = (userId: string) =>
        rows(
          `select token_hash from set_password_tokens
           where org_id = '${orgId}' and user_id = '${userId}' and used_at is null`,
        );
      expect(unused(builderId)).toEqual([sha256Hex(builderLink2.secret)]);
      expect(unused(adminId)).toEqual([sha256Hex(adminLink.secret)]);
      expect(unused(org.ownerId)).toEqual([sha256Hex(org.link.secret)]);

      // The invited users have the requested memberships.
      expect(
        rows(
          `select org_role from memberships where org_id = '${orgId}' and user_id = '${adminId}'`,
        ),
      ).toEqual(["org_admin"]);
      expect(
        rows(`select role from workspace_memberships where org_id = '${orgId}'`).sort(),
      ).toEqual(["builder", "workspace_admin"]);

      // Cross-Organization: a Workspace of the demo Organization is not found, nothing is written anywhere.
      const demoWorkspace = rows(
        `select id from workspaces where org_id = '${DEMO_ORG}' limit 1`,
      )[0];
      expect(demoWorkspace, "precondition: demo workspace exists").toBeTruthy();
      const beforeCross = counts();
      const demoBefore = demoCounts();
      expectCliError(
        cli([
          "user",
          "invite",
          "--org",
          orgId,
          "--email",
          `cross.${sfx}@example.com`,
          "--role",
          "builder",
          "--workspace",
          demoWorkspace as string,
        ]),
        ERR.workspaceNotFound,
      );
      expect(counts()).toEqual(beforeCross);
      expect(demoCounts()).toEqual(demoBefore);
      expect(eventSet(orgId)).toEqual(expected);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC4 TC-4-2: invite with two roles prints the Organization role first and writes one event", async () => {
    const sfx = suffix();
    try {
      const org = createOrg(`QA EA-21 ${sfx}`, `owner.${sfx}@example.com`);
      const email = `dual.${sfx}@example.com`;
      const run = cli([
        "user",
        "invite",
        "--org",
        org.orgId,
        "--email",
        email.toUpperCase(),
        "--role",
        "builder",
        "--role",
        "org_admin",
        "--workspace",
        org.workspaceId,
        "--name",
        "Trần Văn Dual",
      ]);
      expect(run.status, run.stderr).toBe(0);
      const out = lines(run.stdout);
      expect(out).toHaveLength(2);
      const match = new RegExp(
        `^User invited: (${UUID}) \\(${email.replace(/\./g, "\\.")}\\) roles: org_admin, builder$`,
      ).exec(out[0] as string);
      expect(match, out[0]).not.toBeNull();
      const userId = match?.[1] as string;
      expect(
        rows(
          `select email || '|' || display_name from users where id = '${userId}' and org_id = '${org.orgId}'`,
        ),
      ).toEqual([`${email}|Trần Văn Dual`]);
      expect(eventSet(org.orgId)).toContain(`platform-operator|user.invited|user|${userId}`);
      expect(eventSet(org.orgId)).toHaveLength(4);
    } finally {
      purgeBySuffix(sfx);
    }
  });

  test("AC5: seed demo is refused in production with exit 2 and writes nothing", async () => {
    const demoBefore = demoCounts();
    const globalBefore = counts();
    const environments: Record<string, string>[] = [
      { EI_AI_ENV: "production" },
      { EI_AI_ENV: "production", ADMIN_BASE_URL: "" },
    ];
    for (const env of environments) {
      const run = cli(["seed", "demo"], env);
      expect(run.status, JSON.stringify(env)).toBe(2);
      expect(run.stdout.trim()).toBe("");
      expect(lines(run.stderr)).toEqual([SEED_REFUSED]);
      expect(demoCounts()).toEqual(demoBefore);
      expect(counts()).toEqual(globalBefore);
    }
  });

  test("AC5 TC-5-2: any environment other than local or test is refused", async () => {
    const globalBefore = counts();
    for (const value of ["staging", "", "PRODUCTION", "prod"]) {
      const run = cli(["seed", "demo"], { EI_AI_ENV: value });
      expect(run.status, `EI_AI_ENV=${value}`).toBe(2);
      expect(run.stdout.trim()).toBe("");
      expect(lines(run.stderr)).toEqual([SEED_REFUSED]);
    }
    expect(counts()).toEqual(globalBefore);
  });

  test("AC5 TC-5-3: a refused production seed does not delete or change the demo Organization", async () => {
    const warmUp = seed();
    expect(warmUp.status, warmUp.stderr).toBe(0);
    const names = () =>
      rows(`select name from workspaces where org_id = '${DEMO_ORG}'`).concat(
        rows(`select display_name from users where org_id = '${DEMO_ORG}' order by display_name`),
      );
    const before = names();
    const run = cli(["seed", "demo"], { EI_AI_ENV: "production" });
    expect(run.status).toBe(2);
    expect(names()).toEqual(before);
  });
});
