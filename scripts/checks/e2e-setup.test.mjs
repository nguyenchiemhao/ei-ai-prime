// The Playwright setup (e2e/, playwright.config.ts) is covered by the same lint, format and type checks
// as the rest of the code, and has one documented command.
// Run:  node --test scripts/checks/e2e-setup.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";

const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
const node = (args, input) =>
  spawnSync(process.execPath, args, { cwd: ROOT, input, encoding: "utf8" });

// Test tiers (docs/dev/coding-rules.md §3.1): `npm run e2e` is the fast tier used in every QA round;
// specs that copy the repository, re-run whole task suites or measure performance are tagged and run
// only at ticket completion or on demand.
test("e2e_command_runs_the_fast_tier_only", () => {
  assert.equal(packageJson.scripts.e2e, 'playwright test --grep-invert "@slow|@perf"');
  assert.ok(fs.existsSync(path.join(ROOT, "playwright.config.ts")));
});

test("full_and_perf_e2e_commands_exist", () => {
  assert.equal(packageJson.scripts["e2e:full"], "playwright test");
  assert.equal(packageJson.scripts["e2e:perf"], "playwright test --grep @perf");
});

test("slow_and_perf_specs_are_tagged", () => {
  const spec = (name) => fs.readFileSync(path.join(ROOT, "e2e", "foundation", name), "utf8");
  // Prettier may wrap the arguments, so whitespace between them is free.
  const tagged = (title, tag) => new RegExp(`${title}[^"]*",\\s*\\{ tag: "${tag}" \\}`);
  assert.match(spec("EA-19-tenant-isolation.spec.ts"), tagged('test\\.describe\\("EA-19', "@slow"));
  assert.match(spec("EA-13-repo-skeleton.spec.ts"), tagged('test\\(\\s*"AC3: ', "@slow"));
  assert.match(spec("EA-18-multi-tenant-rls.spec.ts"), tagged('test\\(\\s*"NFR: ', "@perf"));
});

test("typecheck_covers_the_e2e_specs_and_the_playwright_config", () => {
  assert.match(packageJson.scripts.typecheck, /tsc --noEmit -p e2e/);
  const tsconfig = JSON.parse(fs.readFileSync(path.join(ROOT, "e2e/tsconfig.json"), "utf8"));
  assert.ok(tsconfig.include.includes("../playwright.config.ts"));
  const result = node(["node_modules/typescript/bin/tsc", "--noEmit", "-p", "e2e"]);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test("prettier_checks_the_e2e_specs_and_the_playwright_config", () => {
  for (const file of ["playwright.config.ts", "e2e/foundation/EA-13-repo-skeleton.spec.ts"]) {
    const info = node(["node_modules/prettier/bin/prettier.cjs", "--file-info", file]);
    assert.equal(JSON.parse(info.stdout).ignored, false, `${file} is ignored by Prettier`);
  }
});

test("eslint_lints_the_e2e_specs_and_the_playwright_config", () => {
  for (const file of ["e2e/foundation/Fixture.spec.ts", "playwright.config.ts"]) {
    const result = node(
      ["node_modules/eslint/bin/eslint.js", "--stdin", "--stdin-filename", file],
      "const unusedValue = 1;\n",
    );
    assert.equal(result.status, 1, `${file} is not linted`);
    assert.match(result.stdout, /no-unused-vars/);
  }
});
