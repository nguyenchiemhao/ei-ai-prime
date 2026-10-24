// EA-37 (KB-06): one ask through the admin origin, printed frame by frame with timing, then the api log lines
// that mention answer_done. A small manual probe for the "Ask this collection" route (SSE stream, headers, trace).
//   node e2e/knowledge/scripts/EA-37-ask-collection-one-ask.mjs <workspace-id> <collection-id> "<question>" [anonymous|authenticated] [groups,comma,separated]
// Environment: EI_AI_SEED_PASSWORD (the shared seed password, see docs/dev/seed-data.md), ADMIN_PORT (default 3000).
// It signs in as the Knowledge Editor of the demo seed (thao.nguyen@mekongdevworks.example) through the API; it
// creates no data and changes nothing. Needs the stack with the `model` profile and `npm run seed`.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const origin = `http://localhost:${process.env.ADMIN_PORT ?? 3000}`;
const [workspace, collection, question, kind = "authenticated", groups = ""] =
  process.argv.slice(2);
const password = process.env.EI_AI_SEED_PASSWORD;
if (!workspace || !collection || !question || !password) {
  console.error(
    'usage: EI_AI_SEED_PASSWORD=... node EA-37-ask-collection-one-ask.mjs <workspace-id> <collection-id> "<question>" [kind] [groups]',
  );
  process.exit(2);
}

const jar = new Map();
function remember(response) {
  for (const line of response.headers.getSetCookie()) {
    const [pair] = line.split(";");
    const [name, ...rest] = pair.split("=");
    jar.set(name.trim(), rest.join("="));
  }
}
const cookie = () => [...jar].map(([name, value]) => `${name}=${value}`).join("; ");

let response = await fetch(`${origin}/api/auth/csrf`, { headers: { cookie: cookie() } });
remember(response);
response = await fetch(`${origin}/api/auth/sign-in`, {
  method: "POST",
  headers: {
    "content-type": "application/json",
    cookie: cookie(),
    origin,
    "x-csrf-token": jar.get("ei_csrf") ?? "",
  },
  body: JSON.stringify({ email: "thao.nguyen@mekongdevworks.example", password }),
});
remember(response);
if (!response.ok) {
  console.error(`sign-in failed: ${response.status}`);
  process.exit(1);
}

const started = performance.now();
const ask = await fetch(`${origin}/api/workspaces/${workspace}/collections/${collection}/ask`, {
  method: "POST",
  headers: {
    "content-type": "application/json",
    cookie: cookie(),
    origin,
    "x-csrf-token": jar.get("ei_csrf") ?? "",
  },
  body: JSON.stringify({
    question,
    principal: { kind, groups: groups ? groups.split(",") : [] },
  }),
});
console.log(`status ${ask.status} ${ask.headers.get("content-type")}`);
console.log(`cache-control: ${ask.headers.get("cache-control")}`);
const reader = ask.body.getReader();
const decoder = new TextDecoder();
for (;;) {
  const { done, value } = await reader.read();
  if (done) break;
  console.log(`+${Math.round(performance.now() - started)} ms  ${decoder.decode(value).trimEnd()}`);
}
await new Promise((resolve) => setTimeout(resolve, 1500));
const logs = spawnSync("docker", ["compose", "logs", "--no-color", "api"], {
  cwd: ROOT,
  encoding: "utf8",
}).stdout;
console.log("--- api log lines with answer_done ---");
console.log(
  logs
    .split(/\r?\n/)
    .filter((line) => line.includes("answer_done"))
    .join("\n") || "(none)",
);
