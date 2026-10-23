// EA-35 (KB-04) exploration: how long does "PUT /collections/{id}/access" take while a large document of the
// same collection is being indexed, and what is the state of the vectors afterwards?
//
// Creates a public collection + folder + one large TXT (~150 KB, ~100 chunks) with the marker
// qa-EA35-<run>, waits until the document is Ready, changes the access to restricted ["race-one"] through
// the admin origin (the nginx proxy times out after 60 s) or through the API port (--direct), prints the
// status and the duration of the call, waits until the document is indexed, prints the vector rows by
// level/groups, and deletes everything it created (documents, folder, collection, their audit rows).
//
// Needs the stack running with the model profile and the demo seed. Run from the repository root:
//   node e2e/knowledge/scripts/EA-35-vector-index-access-lock.mjs            (through the admin origin)
//   node e2e/knowledge/scripts/EA-35-vector-index-access-lock.mjs --direct   (API port 8000)
//   node e2e/knowledge/scripts/EA-35-vector-index-access-lock.mjs --kb 300   (document size in KB)
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { adminUrl } from "../../../scripts/lib/admin-url.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const args = process.argv.slice(2);
const direct = args.includes("--direct");
const kbIndex = args.indexOf("--kb");
const sizeKb = kbIndex >= 0 ? Number(args[kbIndex + 1]) : 150;
const RUN = randomBytes(3).toString("hex");
const MARK = `qa-EA35-${RUN}`;
const ADMIN = adminUrl(ROOT, process.env);
const BASE = direct ? `http://127.0.0.1:${process.env.API_PORT ?? "8000"}` : `${ADMIN}/api`;
const ORG = "0192a000-0000-7000-8000-00000000ea21";

function envValue(name) {
  if (process.env[name]) return process.env[name];
  for (const file of [".env", ".env.example"]) {
    const full = path.join(ROOT, file);
    if (!fs.existsSync(full)) continue;
    const match = new RegExp(`^${name}=(.*)$`, "m").exec(fs.readFileSync(full, "utf8"));
    const value = match?.[1]?.trim().replace(/^["']|["']$/g, "");
    if (value) return value;
  }
  return undefined;
}

function run(file, fileArgs, input) {
  return spawnSync(file, fileArgs, { cwd: ROOT, encoding: "utf8", input });
}
function sql(statement) {
  const result = run(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ei_ai", "-X", "-At", "-q"],
    statement,
  );
  if (result.status !== 0) throw new Error(result.stderr);
  return result.stdout.trim();
}
function indexStatus(documentId) {
  const result = run("docker", [
    "compose",
    "exec",
    "-T",
    "api",
    "ei-ai",
    "index",
    "status",
    "--org",
    ORG,
    "--document",
    documentId,
  ]);
  return result.stdout.trim();
}

const jar = new Map();
async function call(method, route, { json, body, headers = {} } = {}) {
  const cookie = [...jar].map(([k, v]) => `${k}=${v}`).join("; ");
  const csrf = jar.get("ei_csrf");
  const all = { cookie, origin: new URL(ADMIN).origin, ...headers };
  if (csrf && method !== "GET") all["x-csrf-token"] = csrf;
  let payload = body;
  if (json !== undefined) {
    payload = JSON.stringify(json);
    all["content-type"] = "application/json";
  }
  const started = Date.now();
  const response = await fetch(`${BASE}${route}`, { method, headers: all, body: payload });
  const text = await response.text();
  for (const line of response.headers.getSetCookie()) {
    const [pair] = line.split(";");
    const eq = pair.indexOf("=");
    if (/max-age=0/i.test(line)) jar.delete(pair.slice(0, eq));
    else jar.set(pair.slice(0, eq), pair.slice(eq + 1));
  }
  let parsed = null;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = null;
  }
  return { status: response.status, ms: Date.now() - started, text, json: parsed };
}

function leaveText(chars) {
  let out = "";
  let n = 1;
  while (out.length < chars) {
    out += `Điều ${n}. Đơn xin nghỉ phép năm phải được gửi cho quản lý trực tiếp ít nhất ba ngày làm việc trước ngày nghỉ. Nhân viên có mười hai ngày phép mỗi năm (mục ${n}). Quản lý phê duyệt đơn trong vòng hai ngày làm việc.\n\n`;
    n += 1;
  }
  return out;
}

const created = { docs: [], folder: null, collection: null };
let workspaceId = "";
try {
  workspaceId = sql(`select id from workspaces where org_id = '${ORG}' and name = 'People Ops'`);
  await call("GET", "/auth/csrf");
  const signIn = await call("POST", "/auth/sign-in", {
    json: { email: "linh.tran@mekongdevworks.example", password: envValue("EI_AI_SEED_PASSWORD") },
  });
  if (signIn.status !== 200) throw new Error(`sign-in ${signIn.status}`);
  const col = await call("POST", `/workspaces/${workspaceId}/collections`, {
    json: { name: `${MARK}-lock`, subtitle: null, access_level: "public", groups: [] },
  });
  created.collection = col.json.id;
  const folder = await call(
    "POST",
    `/workspaces/${workspaceId}/collections/${col.json.id}/folders`,
    {
      json: { name: `${MARK}-lock-folder` },
    },
  );
  created.folder = folder.json.id;
  const upload = await call(
    "POST",
    `/workspaces/${workspaceId}/collections/${col.json.id}/folders/${folder.json.id}/documents`,
    {
      body: Buffer.from(leaveText(sizeKb * 1000), "utf8"),
      headers: {
        "content-type": "application/octet-stream",
        "x-file-name": encodeURIComponent(`${MARK}-lock.txt`),
      },
    },
  );
  const doc = upload.json;
  created.docs.push(doc.id);
  console.log(`upload ${upload.status} document ${doc.id} (${sizeKb} KB)`);
  for (;;) {
    const list = await call(
      "GET",
      `/workspaces/${workspaceId}/collections/${col.json.id}/documents`,
    );
    const item = list.json.documents.find((entry) => entry.id === doc.id);
    if (item && ["ready", "failed", "not_supported"].includes(item.status)) {
      console.log(`status ${item.status}`);
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  const readyAt = Date.now();
  console.log(`index status at Ready: ${indexStatus(doc.id)}`);
  // Probe: other API calls stay fast while the index job and the blocked PUT run.
  let probing = true;
  const latencies = [];
  const probe = (async () => {
    while (probing) {
      const read = await call("GET", `/workspaces/${workspaceId}/collections`);
      latencies.push(read.ms);
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  })();
  const change = await call("PUT", `/workspaces/${workspaceId}/collections/${col.json.id}/access`, {
    json: { access_level: "restricted", groups: ["race-one"] },
  });
  console.log(
    `PUT access via ${direct ? "API port" : "admin origin"}: HTTP ${change.status} after ${change.ms} ms (${(Date.now() - readyAt) / 1000} s after Ready)`,
  );
  probing = false;
  await probe;
  console.log(
    `GET collections during the wait: ${latencies.length} calls, max ${Math.max(...latencies)} ms`,
  );
  if (change.status !== 200 && change.status !== 204) console.log(change.text.slice(0, 200));
  const deadline = Date.now() + 600_000;
  while (Date.now() < deadline) {
    const line = indexStatus(doc.id);
    if (/ indexed=1 /.test(line)) {
      console.log(`indexed after ${(Date.now() - readyAt) / 1000} s from Ready: ${line}`);
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  const levels = sql(
    `select access_level || ' ' || groups::text || ' x' || n from (select access_level, groups, count(*) as n from chunk_embeddings where document_id = '${doc.id}' group by access_level, groups) t`,
  );
  console.log(`vector rows by level/groups:\n${levels}`);
  const stored = await call("GET", `/workspaces/${workspaceId}/collections`);
  const item = stored.json.collections.find((entry) => entry.id === col.json.id);
  console.log(`collection access now: ${item.access_level} ${JSON.stringify(item.groups)}`);
} finally {
  for (const id of created.docs) {
    await call(
      "DELETE",
      `/workspaces/${workspaceId}/collections/${created.collection}/documents/${id}`,
    );
  }
  if (created.folder) {
    await call(
      "DELETE",
      `/workspaces/${workspaceId}/collections/${created.collection}/folders/${created.folder}`,
    );
  }
  if (created.collection)
    await call("DELETE", `/workspaces/${workspaceId}/collections/${created.collection}`);
  const ids = [...created.docs, created.folder, created.collection]
    .filter(Boolean)
    .map((id) => `'${id}'`);
  if (ids.length > 0) sql(`delete from audit_events where target_id::text in (${ids.join(", ")})`);
  const left = sql(`select count(*) from collections where name ilike '%${MARK}%'`);
  console.log(`cleanup done; collections left with the marker: ${left}`);
}
