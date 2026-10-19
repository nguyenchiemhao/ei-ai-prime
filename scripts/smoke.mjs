// Smoke test of the running stack (used by the CI `stack` job and handy locally):
//   node scripts/smoke.mjs        API_URL / ADMIN_URL / WIDGET_URL override the defaults; the admin
//                                 default follows ADMIN_PORT (shell, then .env) like compose.yaml
// Exit code 0 when every probe answers as expected, 1 otherwise.
import { fileURLToPath } from "node:url";
import path from "node:path";
import { adminUrl } from "./lib/admin-url.mjs";
import { ROOT } from "./lib/docker.mjs";

const TIMEOUT_MS = 5000;

/** The probes for the three base URLs: [name, url, expected JSON body subset or null]. */
export function probes({ api, admin, widget }) {
  return [
    ["api /healthz", `${api}/healthz`, { status: "ok" }],
    ["api /readyz", `${api}/readyz`, { status: "ok" }],
    ["admin /", `${admin}/`, null],
    ["admin /api/healthz (nginx proxy)", `${admin}/api/healthz`, { status: "ok" }],
    ["widget /", `${widget}/`, null],
  ];
}

async function probe([name, url, expected]) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (response.status !== 200) return { name, ok: false, detail: `HTTP ${response.status}` };
    if (expected) {
      const body = await response.json();
      for (const [key, value] of Object.entries(expected)) {
        if (body[key] !== value) return { name, ok: false, detail: `${key} is not ${value}` };
      }
    }
    return { name, ok: true, detail: "HTTP 200" };
  } catch (error) {
    return { name, ok: false, detail: error.name };
  }
}

/** Runs every probe, prints one line each and returns true when all passed. */
export async function runSmoke(urls, log = console.log) {
  const results = await Promise.all(probes(urls).map(probe));
  for (const { name, ok, detail } of results) log(`${ok ? "PASS" : "FAIL"} ${name} - ${detail}`);
  return results.every((result) => result.ok);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const ok = await runSmoke({
    api: process.env.API_URL || "http://localhost:8000",
    admin: adminUrl(ROOT, process.env),
    widget: process.env.WIDGET_URL || "http://localhost:3001",
  });
  process.exit(ok ? 0 : 1);
}
