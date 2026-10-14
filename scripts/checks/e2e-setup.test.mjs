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

test("e2e_command_runs_the_playwright_specs", () => {
  assert.equal(packageJson.scripts.e2e, "playwright test");
  assert.ok(fs.existsSync(path.join(ROOT, "playwright.config.ts")));
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
