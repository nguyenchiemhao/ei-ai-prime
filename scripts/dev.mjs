// Entry point of the local integration environment: node scripts/dev.mjs <command> (npm run up|down|...).
// Node built-ins only, so it works right after `git clone` on Windows, macOS and Linux, and in CI.
//
//   up [--no-model] [--demo]   checks, creates .env on first run, builds and starts, waits until healthy
//   down                       stops and removes the containers (volumes are kept)
//   reset                      down + deletes the database volume only (never the model cache)
//   seed                       loads the Mekong Devworks demo data (ei-ai seed demo in the api container)
//   ps | logs [service]        status and recent logs
import { ensureEnv } from "./lib/ensure-env.mjs";
import { MIN_COMPOSE_VERSION, isAtLeast, parseComposeVersion } from "./lib/compose-version.mjs";
import {
  ALL_PROFILE_ARGS,
  runWithTicks,
  ROOT,
  compose,
  docker,
  parseUpArgs,
  upProfileArgs,
} from "./lib/docker.mjs";
import { memoryWarning } from "./lib/memory-preflight.mjs";
import { resetDatabase } from "./lib/reset.mjs";

const URLS = [
  "Admin UI   http://localhost:3000",
  "Widget     http://localhost:3001",
  "API health http://localhost:8000/healthz",
];

function fail(message) {
  console.error(message);
  process.exit(1);
}

function checkEngine() {
  const info = docker(["info", "--format", "{{.MemTotal}}"], { capture: true });
  if (info.code !== 0) {
    fail(
      "Docker is not available: start Docker Desktop (or the Docker service) and run the command again.",
    );
  }
  return Number(info.stdout.trim()) || 0;
}

function checkComposeVersion() {
  const result = compose(["version", "--short"], { capture: true });
  const version = parseComposeVersion(result.stdout);
  if (result.code !== 0 || !version) {
    fail(
      "Docker Compose v2 is required (the `docker compose` command). Install or update Docker Desktop.",
    );
  }
  if (!isAtLeast(version, parseComposeVersion(MIN_COMPOSE_VERSION))) {
    fail(
      `Docker Compose ${result.stdout.trim()} is too old; ${MIN_COMPOSE_VERSION} or newer is required. Update Docker Desktop.`,
    );
  }
}

function warnAboutMemory(profileArgs, engineBytes) {
  const resolved = compose([...profileArgs, "config", "--format", "json"], { capture: true });
  if (resolved.code !== 0) return;
  const text = memoryWarning(JSON.parse(resolved.stdout).services ?? {}, engineBytes);
  if (text) console.warn(`${text}\n`);
}

/** Services that are not running or not healthy, from `ps --format json` (array or one object per line). */
function unhealthyServices() {
  const result = compose([...ALL_PROFILE_ARGS, "ps", "--all", "--format", "json"], {
    capture: true,
  });
  const text = result.stdout.trim();
  if (!text) return [];
  let rows;
  try {
    rows = JSON.parse(text);
  } catch {
    rows = text.split("\n").map((line) => JSON.parse(line));
  }
  return [rows]
    .flat()
    .filter((row) => row.State !== "running" || (row.Health && row.Health !== "healthy"))
    .map((row) => row.Service);
}

async function up(argv) {
  let options;
  try {
    options = parseUpArgs(argv);
  } catch (error) {
    fail(error.message);
  }
  const started = Date.now();
  const engineBytes = checkEngine();
  checkComposeVersion();
  const envState = ensureEnv(ROOT);
  if (envState === "created") {
    console.log(
      "Created .env with generated passwords (git-ignored). Keep it: the database volume uses them.",
    );
  } else if (envState === "updated") {
    console.log(
      "Added the missing generated passwords to your existing .env (your own lines are unchanged).",
    );
  }
  const profileArgs = upProfileArgs(options);
  warnAboutMemory(profileArgs, engineBytes);
  if (options.model) {
    console.log(
      "Starting with the model. The first start downloads ~2.5 GB (see README); later starts reuse the cached volume.",
    );
  }
  const code = await runWithTicks(
    "docker",
    ["compose", ...profileArgs, "up", "--detach", "--build", "--wait"],
    {
      tickMs: 60_000,
      onTick: () =>
        console.log(
          options.model
            ? "Still waiting. The model may be downloading or loading; follow it with: npm run logs -- model"
            : "Still waiting. See what is starting with: npm run ps",
        ),
    },
  );
  if (code !== 0) {
    compose([...ALL_PROFILE_ARGS, "ps", "--all"]);
    for (const service of unhealthyServices()) {
      console.error(`\n--- last 50 log lines of ${service} ---`);
      compose([...ALL_PROFILE_ARGS, "logs", "--tail", "50", service]);
    }
    fail(
      `\nnpm run up failed after ${Math.round((Date.now() - started) / 1000)} s. See the messages above and the README troubleshooting section.`,
    );
  }
  console.log(
    `\nAll services are healthy (${Math.round((Date.now() - started) / 1000)} s).\n${URLS.join("\n")}`,
  );
  console.log("Demo data: npm run seed    Stop: npm run down");
}

function down() {
  process.exit(compose([...ALL_PROFILE_ARGS, "down", "--remove-orphans"]).code);
}

function reset() {
  ensureEnv(ROOT); // compose interpolates the password variables even to resolve the volume name
  const { code, message } = resetDatabase();
  console.log(message);
  process.exit(code);
}

const [command, ...rest] = process.argv.slice(2);
switch (command) {
  case "up":
    await up(rest);
    break;
  case "down":
    down();
    break;
  case "reset":
    reset();
    break;
  case "seed":
    process.exit(compose([...ALL_PROFILE_ARGS, "exec", "-T", "api", "ei-ai", "seed", "demo"]).code);
    break;
  case "ps":
    process.exit(compose([...ALL_PROFILE_ARGS, "ps", "--all"]).code);
    break;
  case "logs":
    process.exit(compose([...ALL_PROFILE_ARGS, "logs", "--tail", "100", ...rest]).code);
    break;
  default:
    fail(
      "usage: node scripts/dev.mjs up [--no-model] [--demo] | down | reset | seed | ps | logs [service]",
    );
}
