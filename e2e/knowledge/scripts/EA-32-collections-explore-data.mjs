// EA-32 (KB-01): test data for the exploratory run in the browser (Chrome DevTools).
//   node e2e/knowledge/scripts/EA-32-collections-explore-data.mjs setup     (prints the accounts as JSON)
//   node e2e/knowledge/scripts/EA-32-collections-explore-data.mjs bulk <email> <password> <workspaceId> [count]
//       (signs in as that user and creates `count` (default 100) collections `Bulk 000 <marker>` for the
//        performance trace; needs the run marker file written by `setup`)
//   node e2e/knowledge/scripts/EA-32-collections-explore-data.mjs cleanup   (removes everything it created)
// `setup` creates an empty Workspace `QA22 qa-EA32-<run> Explore` and two users that are members of it and
// of People Ops: a Workspace Admin and a Knowledge Editor. `cleanup` removes those users and Workspaces,
// the collections, folders and audit rows in them, and any other row that carries the marker.
// Needs the stack up (`npm run up -- --no-model`) and seeded (`npm run seed`). Never touches the seed rows.
// The passwords are random and only printed once; nothing is written to disk except the run marker file.
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { adminUrl } from "../../../scripts/lib/admin-url.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const ADMIN = adminUrl(ROOT, process.env);
const ORG = "0192a000-0000-7000-8000-00000000ea21";
const STATE = path.join(ROOT, ".work", "EA-32", "explore-run.json");
const DOMAIN = "mekongdevworks.example";

function run(file, args, input) {
  const result = spawnSync(file, args, { cwd: ROOT, encoding: "utf8", input });
  if (result.status !== 0) throw new Error(`${file} ${args.join(" ")}: ${result.stderr}`);
  return result.stdout.trim();
}

function cli(args) {
  return run("docker", ["compose", "exec", "-T", "api", "ei-ai", ...args]);
}

function sql(statement) {
  return run(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ei_ai", "-X", "-At", "-q"],
    statement,
  );
}

function softSql(statement) {
  spawnSync(
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
      "-c",
      statement,
    ],
    { cwd: ROOT, encoding: "utf8" },
  );
}

async function setPassword(token, password) {
  const csrf = await fetch(`${ADMIN}/api/auth/csrf`);
  const cookie = (csrf.headers.getSetCookie?.() ?? []).map((line) => line.split(";")[0]).join("; ");
  const value = /ei_csrf=([^;]+)/.exec(cookie)?.[1] ?? "";
  const response = await fetch(`${ADMIN}/api/auth/set-password`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie,
      "x-csrf-token": value,
      origin: new URL(ADMIN).origin,
    },
    body: JSON.stringify({ token, password }),
  });
  if (response.status !== 204) throw new Error(`set-password answered ${response.status}`);
}

async function createUser(marker, label, role, workspaceIds) {
  const email = `qa22.${marker}.${label}@${DOMAIN}`.toLowerCase();
  const out = cli([
    "user",
    "invite",
    "--org",
    ORG,
    "--email",
    email,
    "--role",
    role,
    "--workspace",
    workspaceIds[0],
    "--name",
    `QA32 ${label} ${marker}`,
  ]).split(/\r?\n/);
  const token = /#token=(\S+)$/.exec(out[1] ?? "")?.[1];
  if (!token) throw new Error("no set-password link in the CLI output");
  const password = `Qa32-${randomBytes(9).toString("base64url")}!`;
  await setPassword(token, password);
  for (const workspace of workspaceIds.slice(1)) {
    cli([
      "workspace",
      "add-member",
      "--org",
      ORG,
      "--workspace",
      workspace,
      "--email",
      email,
      "--role",
      role,
    ]);
  }
  return { email, password };
}

async function setup() {
  const marker = `qa-EA32-${randomBytes(4).toString("hex")}`;
  const peopleOps = sql(
    `select id from workspaces where org_id = '${ORG}' and name = 'People Ops'`,
  );
  const created = cli(["workspace", "create", "--org", ORG, "--name", `QA22 ${marker} Explore`]);
  const explore = /Workspace created: (\S+)/.exec(created)?.[1];
  if (!explore || !peopleOps) throw new Error("Workspace missing");
  const admin = await createUser(marker, "admin", "workspace_admin", [peopleOps, explore]);
  const editor = await createUser(marker, "editor", "knowledge_editor", [peopleOps, explore]);
  fs.mkdirSync(path.dirname(STATE), { recursive: true });
  fs.writeFileSync(STATE, JSON.stringify({ marker }));
  console.log(
    JSON.stringify({ marker, adminUrl: ADMIN, peopleOps, explore, admin, editor }, null, 2),
  );
}

function cleanup() {
  const qaWorkspaces = `select id from workspaces where name like 'QA22 %'`;
  softSql(
    `delete from audit_events where (action like 'collection.%' or action like 'folder.%') and workspace_id in (${qaWorkspaces})`,
  );
  softSql(
    `delete from folders where collection_id in (select id from collections where workspace_id in (${qaWorkspaces}) or name ilike '%qa-ea32-%')`,
  );
  softSql(
    `delete from collections where workspace_id in (${qaWorkspaces}) or name ilike '%qa-ea32-%'`,
  );
  const users = sql(
    `select id from users where org_id = '${ORG}' and email like 'qa22.%@${DOMAIN}'`,
  )
    .split("\n")
    .filter(Boolean);
  const workspaces = sql(`select id from workspaces where org_id = '${ORG}' and name like 'QA22 %'`)
    .split("\n")
    .filter(Boolean);
  const quote = (values) => values.map((value) => `'${value}'`).join(", ");
  const statements = [];
  if (users.length > 0) {
    const ids = quote(users);
    statements.push(
      `delete from admin_sessions where org_id = '${ORG}' and user_id in (${ids});`,
      `delete from user_credentials where org_id = '${ORG}' and user_id in (${ids});`,
      `delete from audit_events where org_id = '${ORG}' and (target_id::text in (${ids}) or actor in (${quote(users.map((id) => `user:${id}`))}));`,
      `delete from set_password_tokens where org_id = '${ORG}' and user_id in (${ids});`,
      `delete from workspace_memberships where org_id = '${ORG}' and user_id in (${ids});`,
      `delete from memberships where org_id = '${ORG}' and user_id in (${ids});`,
      `delete from users where org_id = '${ORG}' and id in (${ids});`,
    );
  }
  if (workspaces.length > 0) {
    statements.push(
      `delete from audit_events where org_id = '${ORG}' and target_id::text in (${quote(workspaces)});`,
      `delete from workspaces where org_id = '${ORG}' and id in (${quote(workspaces)});`,
    );
  }
  if (statements.length > 0) sql(`begin; ${statements.join(" ")} commit;`);
  fs.rmSync(STATE, { force: true });
  const left = sql(
    `select name from collections where name ilike '%qa-ea32-%' union all select name from workspaces where name ilike '%qa-ea32-%' union all select email from users where email ilike '%qa-ea32-%'`,
  );
  console.log(
    left === "" ? "cleanup done: no row with the marker is left" : `LEFT BEHIND:\n${left}`,
  );
  if (left !== "") process.exitCode = 1;
}

async function bulk(email, password, workspaceId, count) {
  const { marker } = JSON.parse(fs.readFileSync(STATE, "utf8"));
  const origin = new URL(ADMIN).origin;
  const jar = new Map();
  const remember = (response) => {
    for (const line of response.headers.getSetCookie?.() ?? []) {
      const [pair] = line.split(";");
      const eq = pair.indexOf("=");
      jar.set(pair.slice(0, eq), pair.slice(eq + 1));
    }
  };
  const cookie = () => [...jar].map(([name, value]) => `${name}=${value}`).join("; ");
  const send = async (method, route, body) => {
    const response = await fetch(`${ADMIN}${route}`, {
      method,
      headers: {
        "content-type": "application/json",
        cookie: cookie(),
        "x-csrf-token": jar.get("ei_csrf") ?? "",
        origin,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    remember(response);
    return response;
  };
  remember(await fetch(`${ADMIN}/api/auth/csrf`));
  const signIn = await send("POST", "/api/auth/sign-in", { email, password });
  if (signIn.status >= 300) throw new Error(`sign-in answered ${signIn.status}`);
  for (let index = 0; index < count; index++) {
    const label = String(index).padStart(3, "0");
    const kind = index % 3;
    const response = await send("POST", `/api/workspaces/${workspaceId}/collections`, {
      name: `Bulk ${label} ${marker}`,
      subtitle: index % 5 === 0 ? `Subtitle ${label}` : null,
      access_level: ["authenticated", "public", "restricted"][kind],
      groups: kind === 2 ? ["managers", `team-${label}`] : [],
      local_only: index % 7 === 0,
    });
    if (response.status !== 201) throw new Error(`create ${label} answered ${response.status}`);
  }
  console.log(`created ${count} collections in ${workspaceId}`);
}

const mode = process.argv[2];
if (mode === "setup") await setup();
else if (mode === "bulk") {
  const [, , , email, password, workspaceId, count] = process.argv;
  await bulk(email, password, workspaceId, Number(count ?? 100));
} else if (mode === "cleanup") cleanup();
else {
  console.error("usage: node EA-32-collections-explore-data.mjs setup|cleanup");
  process.exitCode = 2;
}
