// Tests of the Node check runner CLI: it must fail when a pattern matches no file, when a check runs
// zero tests, when a test fails and when a command check exits non-zero. Fixtures are *.fixture.mjs so
// the real `scripts/**/*.test.mjs` pattern never picks up the deliberately failing ones.
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RUNNER = path.join(ROOT, "scripts/run-node-checks.mjs");

function run(configName) {
  const config = path.join(ROOT, "scripts/test-fixtures/node-checks", `${configName}.fixture.mjs`);
  const result = spawnSync(process.execPath, [RUNNER, "--config", config], {
    cwd: ROOT,
    encoding: "utf8",
  });
  return { code: result.status, output: `${result.stdout}${result.stderr}` };
}

test("passes_and_prints_one_summary_line_per_check", () => {
  const { code, output } = run("config-pass");
  assert.equal(code, 0, output);
  assert.match(output, /PASS fixture-pass .*2 tests/);
  assert.match(output, /PASS fixture-command/);
});

test("fails_when_a_glob_matches_no_file", () => {
  const { code, output } = run("config-no-match");
  assert.equal(code, 1);
  assert.match(
    output,
    /FAIL fixture-empty.*no file matches scripts\/test-fixtures\/node-checks\/empty\/\*\.fixture\.mjs/,
  );
});

test("fails_when_tests_count_is_zero", () => {
  const { code, output } = run("config-zero-tests");
  assert.equal(code, 1);
  assert.match(output, /FAIL fixture-zero.*0 tests/);
});

test("fails_when_a_test_fails", () => {
  const { code, output } = run("config-fail");
  assert.equal(code, 1);
  assert.match(output, /FAIL fixture-fail.*1 failed/);
});

test("fails_when_a_command_check_exits_non_zero", () => {
  const { code, output } = run("config-command-fails");
  assert.equal(code, 1);
  assert.match(output, /FAIL fixture-command-fails.*exit code 3/);
});
