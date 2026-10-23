// EA-33 (KB-02): test data for the exploratory run in the browser (Chrome DevTools).
//   node e2e/knowledge/scripts/EA-33-upload-process-documents-explore-data.mjs setup
//       signs in as Linh Tran, creates the folder `qa-EA33-explore` in "Employee Handbook" of People Ops
//       and uploads text files (a long one, a Vietnamese one, one with HTML in its name) into it; prints
//       the Workspace, collection and folder ids as JSON
//   node e2e/knowledge/scripts/EA-33-upload-process-documents-explore-data.mjs bulk [count]
//       uploads `count` (default 30) small TXT files into the folder (for the performance trace)
//   node e2e/knowledge/scripts/EA-33-upload-process-documents-explore-data.mjs cleanup
//       removes every document of the folder through the API, then the folder, then the audit rows of
//       those documents; any other row that carries the marker `qa-ea33-explore` is deleted too
// Needs the stack up (`npm run up -- --no-model`) and seeded (`npm run seed`). Never touches seed rows.
// The shared test password comes from EI_AI_SEED_PASSWORD (shell, .env, .env.example); it is never printed.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { adminUrl } from "../../../scripts/lib/admin-url.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const ADMIN = adminUrl(ROOT, process.env);
const ORIGIN = new URL(ADMIN).origin;
const ORG = "0192a000-0000-7000-8000-00000000ea21";
const MARK = "qa-EA33-explore";
const EMAIL = "linh.tran@mekongdevworks.example";
const STATE = path.join(ROOT, ".work", "EA-33", "explore-run.json");

function sql(statement) {
  const result = spawnSync(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ei_ai", "-X", "-At", "-q"],
    { cwd: ROOT, encoding: "utf8", input: statement },
  );
  if (result.status !== 0) throw new Error(result.stderr);
  return result.stdout.trim();
}

function seedPassword() {
  if (process.env.EI_AI_SEED_PASSWORD) return process.env.EI_AI_SEED_PASSWORD;
  for (const file of [".env", ".env.example"]) {
    const full = path.join(ROOT, file);
    if (!fs.existsSync(full)) continue;
    const match = /^EI_AI_SEED_PASSWORD=(.*)$/m.exec(fs.readFileSync(full, "utf8"));
    if (match?.[1]) return match[1].trim().replace(/^["']|["']$/g, "");
  }
  throw new Error("EI_AI_SEED_PASSWORD is not set");
}

/** A tiny API client with a cookie jar. */
async function signIn() {
  const jar = new Map();
  const remember = (response) => {
    for (const line of response.headers.getSetCookie?.() ?? []) {
      const [pair] = line.split(";");
      const at = pair.indexOf("=");
      jar.set(pair.slice(0, at), pair.slice(at + 1));
    }
  };
  const call = async (method, apiPath, { body, headers } = {}) => {
    const response = await fetch(`${ADMIN}/api${apiPath}`, {
      method,
      body,
      headers: {
        cookie: [...jar].map(([name, value]) => `${name}=${value}`).join("; "),
        "x-csrf-token": jar.get("ei_csrf") ?? "",
        origin: ORIGIN,
        ...headers,
      },
    });
    remember(response);
    const text = await response.text();
    return { status: response.status, json: text ? JSON.parse(text) : null };
  };
  remember(await fetch(`${ADMIN}/api/auth/csrf`));
  const session = await call("POST", "/auth/sign-in", {
    body: JSON.stringify({ email: EMAIL, password: seedPassword() }),
    headers: { "content-type": "application/json" },
  });
  if (session.status >= 300) throw new Error(`sign-in answered ${session.status}`);
  return call;
}

async function locate(call) {
  const workspaceId = sql(
    `select id from workspaces where org_id = '${ORG}' and name = 'People Ops'`,
  );
  const list = await call("GET", `/workspaces/${workspaceId}/collections`);
  const collection = list.json.collections.find((item) => item.name === "Employee Handbook");
  return { workspaceId, collectionId: collection.id };
}

async function findFolder(call, ids) {
  const detail = await call(
    "GET",
    `/workspaces/${ids.workspaceId}/collections/${ids.collectionId}`,
  );
  return detail.json.folders.find((folder) => folder.name === MARK);
}

async function upload(call, ids, folderId, name, text) {
  return call(
    "POST",
    `/workspaces/${ids.workspaceId}/collections/${ids.collectionId}/folders/${folderId}/documents`,
    {
      body: text,
      headers: {
        "content-type": "application/octet-stream",
        "x-file-name": encodeURIComponent(name),
      },
    },
  );
}

const words = (marker, count) =>
  Array.from(
    { length: count },
    (_, index) => `${marker} sentence ${index} of the exploratory text.`,
  ).join(" ");

async function setup() {
  const call = await signIn();
  const ids = await locate(call);
  let folder = await findFolder(call, ids);
  if (!folder) {
    const created = await call(
      "POST",
      `/workspaces/${ids.workspaceId}/collections/${ids.collectionId}/folders`,
      {
        body: JSON.stringify({ name: MARK }),
        headers: { "content-type": "application/json" },
      },
    );
    folder = created.json;
  }
  const files = [
    [`${MARK}-long.txt`, words("zqlong", 2500)],
    [
      `${MARK}-Bảng chấm công & phê duyệt.txt`,
      "Nhân viên ghi nhận giờ làm thêm trong bảng chấm công. ".repeat(40),
    ],
    [
      `${MARK}-<img src=x onerror=alert(1)>.txt`,
      "<script>alert('xss')</script> plain text of the xss probe. ".repeat(10),
    ],
  ];
  for (const [name, text] of files) await upload(call, ids, folder.id, name, text);
  if (!fs.existsSync(STATE)) {
    fs.mkdirSync(path.dirname(STATE), { recursive: true });
    fs.writeFileSync(
      STATE,
      JSON.stringify({ startedAt: new Date(Date.now() - 5000).toISOString() }),
    );
  }
  console.log(JSON.stringify({ ...ids, folderId: folder.id, folderName: MARK }));
}

async function bulk(count) {
  const call = await signIn();
  const ids = await locate(call);
  const folder = await findFolder(call, ids);
  if (!folder) throw new Error("run setup first");
  for (let index = 0; index < count; index++) {
    await upload(
      call,
      ids,
      folder.id,
      `${MARK}-bulk-${String(index).padStart(3, "0")}.txt`,
      words(`zqb${index}`, 40),
    );
  }
  console.log(`uploaded ${count} files`);
}

async function cleanup() {
  const call = await signIn();
  const ids = await locate(call);
  const folder = await findFolder(call, ids);
  const removed = [];
  if (folder) {
    const list = await call(
      "GET",
      `/workspaces/${ids.workspaceId}/collections/${ids.collectionId}/documents?folder_id=${folder.id}`,
    );
    for (const item of list.json.documents) {
      await call(
        "DELETE",
        `/workspaces/${ids.workspaceId}/collections/${ids.collectionId}/documents/${item.id}`,
      );
      removed.push(item.id);
    }
    await call(
      "DELETE",
      `/workspaces/${ids.workspaceId}/collections/${ids.collectionId}/folders/${folder.id}`,
    );
  }
  // Documents uploaded and removed through the browser leave audit rows: remove the ones written since
  // `setup` whose document no longer exists, and the audit rows of the folder.
  const startedAt = fs.existsSync(STATE)
    ? JSON.parse(fs.readFileSync(STATE, "utf8")).startedAt
    : null;
  if (startedAt) {
    sql(
      `delete from audit_events where action like 'document.%' and created_at >= '${startedAt}' and target_id::text not in (select id::text from documents)`,
    );
  }
  if (folder) sql(`delete from audit_events where target_id::text = '${folder.id}'`);
  fs.rmSync(STATE, { force: true });
  console.log(`removed ${removed.length} documents${folder ? " and the folder" : ""}`);
}

const [command, argument] = process.argv.slice(2);
if (command === "setup") await setup();
else if (command === "bulk") await bulk(Number(argument ?? 30));
else if (command === "cleanup") await cleanup();
else {
  console.error("usage: setup | bulk [count] | cleanup");
  process.exit(2);
}
