// EA-13 (SET-03) AC5: .env.example holds placeholders only, and a real .env can never be committed.
// Run:  node --test scripts/checks/env-example.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";

const SECRET_NAME = /PASSWORD|SECRET|TOKEN|KEY/i;
// The shared demo password is a documented local/test value, not a secret (see docs/dev/seed-data.md).
const DOCUMENTED_NAME = "EI_AI_SEED_PASSWORD";
const example = fs.readFileSync(path.join(ROOT, ".env.example"), "utf8");
const assignments = example
  .split("\n")
  .filter((line) => /^[A-Z][A-Z0-9_]*=/.test(line))
  .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]);

test("env_example_has_no_secret_values", () => {
  assert.ok(assignments.length >= 2, "expected the variables of the local environment");
  for (const [name, value] of assignments.filter(
    ([name]) => SECRET_NAME.test(name) && name !== DOCUMENTED_NAME,
  )) {
    assert.ok(
      value === "__GENERATED__" || value === "__GENERATED_KEY__" || value === "",
      `${name} must be a generated placeholder or empty in .env.example`,
    );
  }
  for (const name of [
    "POSTGRES_PASSWORD",
    "APP_DB_PASSWORD",
    "MIGRATION_DB_PASSWORD",
    "SIGNIN_DB_PASSWORD",
  ]) {
    assert.ok(
      assignments.some(([n, v]) => n === name && v === "__GENERATED__"),
      `${name}=__GENERATED__ is missing`,
    );
  }
});

test("env_example_documents_the_seed_password", () => {
  const entry = assignments.find(([name]) => name === DOCUMENTED_NAME);
  assert.ok(entry, `${DOCUMENTED_NAME} is missing`);
  assert.notEqual(entry[1], "", `${DOCUMENTED_NAME} must have a default value`);
});

test("env_is_git_ignored", () => {
  const ignored = spawnSync("git", ["check-ignore", ".env"], { cwd: ROOT, encoding: "utf8" });
  assert.equal(ignored.status, 0, ".env must be listed in .gitignore");
  const example = spawnSync("git", ["check-ignore", ".env.example"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  assert.equal(example.status, 1, ".env.example must stay tracked");
});

test("no_env_file_is_tracked_except_the_example", () => {
  const tracked = spawnSync("git", ["ls-files"], { cwd: ROOT, encoding: "utf8" }).stdout.split(
    "\n",
  );
  const envFiles = tracked.filter((file) => /(^|\/)\.env/.test(file));
  assert.deepEqual(
    envFiles.filter((file) => file !== ".env.example"),
    [],
  );
});

test("master_key_is_a_generated_key", () => {
  assert.ok(
    assignments.some(([n, v]) => n === "EI_AI_MASTER_KEY" && v === "__GENERATED_KEY__"),
    "EI_AI_MASTER_KEY=__GENERATED_KEY__ is missing",
  );
});
