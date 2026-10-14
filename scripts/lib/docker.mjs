// Thin helpers around the docker CLI. Always an argument array and, for docker, never a shell:
// nothing is re-interpreted by Git Bash, cmd or PowerShell (paths such as /models stay untouched).
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

const profiles = (names) => names.flatMap((name) => ["--profile", name]);

/** Compose profile flags for `up`: core always, the model unless --no-model, demo on request. */
export function upProfileArgs({ model = true, demo = false } = {}) {
  return profiles(["core", ...(model ? ["model"] : []), ...(demo ? ["demo"] : [])]);
}

/** Every profile, so `down` and `ps` also see model, demo and tool containers. */
export const ALL_PROFILE_ARGS = profiles(["core", "model", "demo", "tools"]);

/** Flags of `npm run up`; throws on anything unknown. */
export function parseUpArgs(argv) {
  const options = { model: true, demo: false };
  for (const arg of argv) {
    if (arg === "--no-model") options.model = false;
    else if (arg === "--demo") options.demo = true;
    else throw new Error(`unknown option ${arg} (supported: --no-model, --demo)`);
  }
  return options;
}

/**
 * Runs a command. `capture` collects the output; otherwise it goes to this terminal. `shell` is only for
 * fixed commands such as npm.cmd on Windows.
 * Returns { code, stdout, stderr }; a missing executable has code 127.
 */
export function run(
  command,
  args,
  { capture = false, cwd = ROOT, env = process.env, shell = false } = {},
) {
  const result = spawnSync(command, args, {
    cwd,
    env,
    encoding: "utf8",
    shell,
    stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
  });
  if (result.error) return { code: 127, stdout: "", stderr: String(result.error.message) };
  return { code: result.status ?? 1, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
}

export const docker = (args, options) => run("docker", args, options);
export const compose = (args, options) => docker(["compose", ...args], options);

/**
 * Like run() with the output on this terminal, but asynchronous: `onTick` is called every `tickMs`
 * while the command runs (progress hints for a long wait). Resolves with the exit code.
 */
export function runWithTicks(command, args, { onTick, tickMs, cwd = ROOT, env = process.env }) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd, env, stdio: "inherit" });
    const timer = setInterval(onTick, tickMs);
    child.on("error", () => {
      clearInterval(timer);
      resolve(127);
    });
    child.on("close", (code) => {
      clearInterval(timer);
      resolve(code ?? 1);
    });
  });
}
