// Runs one task of scripts/lib/tasks.mjs and returns its exit code.
import path from "node:path";
import { ensureEnv } from "./ensure-env.mjs";
import { ROOT, compose, run } from "./docker.mjs";
import { runMigrations } from "./migrate.mjs";
import { tasks } from "./tasks.mjs";

const isWindows = process.platform === "win32";

/** Starts only what the integration tests need, waiting until it is healthy, then migrates the database. */
function startServices() {
  const started = compose(["--profile", "core", "up", "--detach", "--wait", "db", "valkey"]).code;
  return started !== 0 ? started : runMigrations();
}

function runBackendInContainer(task) {
  ensureEnv(ROOT); // compose interpolates ${VAR:?} for every service, so .env must exist even for unit tests
  const built = compose(["--profile", "tools", "build", "backend-tools"]);
  if (built.code !== 0) return built.code;
  if (task.services) {
    const started = startServices();
    if (started !== 0) return started;
  }
  return compose(["--profile", "tools", "run", "--rm", "-T", "backend-tools", ...task.backend])
    .code;
}

/**
 * @param {string} name task name from tasks.mjs
 * @param {{ native?: boolean }} options native = run backend tools on the host (CI, local Python 3.12)
 */
export function runTask(name, { native = false } = {}) {
  const task = tasks[name];
  if (!task) {
    console.error(`unknown task ${name}; known: ${Object.keys(tasks).join(", ")}`);
    return 2;
  }
  if (task.run) return task.run();
  if (task.command) {
    const [command, ...args] = task.command;
    // npm is npm.cmd on Windows and cannot be spawned without a shell; the arguments are fixed.
    return run(command, args, { cwd: ROOT, shell: isWindows && command === "npm" }).code;
  }
  if (native) {
    const [command, ...args] = task.backend;
    return run(command, args, { cwd: path.join(ROOT, "backend") }).code;
  }
  return runBackendInContainer(task);
}
