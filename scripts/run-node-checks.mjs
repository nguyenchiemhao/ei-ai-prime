// Runs every repository Node check (design, architecture, EVL-01, package and script tests, validators).
// Fails when a pattern matches no file, when a check reports 0 tests, on a failing test or command.
// Usage: node scripts/run-node-checks.mjs [--config <file>]
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { expandPattern, parseTapSummary } from "./lib/node-checks.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// A runner started from inside `node --test` would otherwise make its own children report as subtests.
const CHILD_ENV = { ...process.env, NODE_TEST_CONTEXT: undefined };

function runTests(check) {
  const files = expandPattern(ROOT, check.pattern);
  if (files.length === 0) return { ok: false, detail: `no file matches ${check.pattern}` };
  const result = spawnSync(process.execPath, ["--test", "--test-reporter=tap", ...files], {
    cwd: ROOT,
    encoding: "utf8",
    env: CHILD_ENV,
  });
  const summary = parseTapSummary(result.stdout ?? "");
  if (!summary)
    return {
      ok: false,
      detail: "no TAP summary in the output",
      log: `${result.stdout}${result.stderr}`,
    };
  const counts = `${summary.tests} tests, ${summary.skipped} skipped, ${files.length} files`;
  if (summary.tests === 0) return { ok: false, detail: `0 tests (${files.length} files)` };
  if (summary.fail > 0 || result.status !== 0)
    return { ok: false, detail: `${summary.fail} failed of ${counts}`, log: result.stdout };
  return { ok: true, detail: counts };
}

function runCommand(check) {
  const [command, ...args] = check.command;
  const result = spawnSync(command, args, { cwd: ROOT, encoding: "utf8", env: CHILD_ENV });
  const log = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  if (result.status !== 0) return { ok: false, detail: `exit code ${result.status}`, log };
  return { ok: true, detail: "exit code 0" };
}

async function main() {
  const configIndex = process.argv.indexOf("--config");
  const configPath =
    configIndex > 0
      ? path.resolve(process.argv[configIndex + 1])
      : path.join(ROOT, "scripts/node-checks.config.mjs");
  const { default: checks } = await import(pathToFileURL(configPath).href);
  let failed = 0;
  for (const check of checks) {
    const started = Date.now();
    const outcome = check.pattern ? runTests(check) : runCommand(check);
    const seconds = ((Date.now() - started) / 1000).toFixed(1);
    console.log(`${outcome.ok ? "PASS" : "FAIL"} ${check.name} - ${outcome.detail} (${seconds}s)`);
    if (!outcome.ok) {
      failed += 1;
      if (outcome.log) console.log(outcome.log);
    }
  }
  console.log(
    failed === 0
      ? `All ${checks.length} checks passed.`
      : `${failed} of ${checks.length} checks failed.`,
  );
  process.exit(failed === 0 ? 0 : 1);
}

await main();
