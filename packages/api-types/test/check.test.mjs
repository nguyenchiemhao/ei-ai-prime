// EA-13 (SET-03) ADR-001 section 11: the generated TypeScript types must match the committed OpenAPI.
// Run:  node --test packages/api-types/test/check.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CHECK = path.join(PACKAGE, "scripts/check.mjs");

function run(env = {}) {
  const result = spawnSync(process.execPath, [CHECK], {
    cwd: PACKAGE,
    encoding: "utf8",
    env: { ...process.env, NODE_TEST_CONTEXT: undefined, ...env },
  });
  return { code: result.status, output: `${result.stdout}${result.stderr}` };
}

test("committed_types_match_the_committed_openapi", () => {
  const { code, output } = run();
  assert.equal(code, 0, output);
});

test("check_fails_when_the_openapi_changed_without_regenerating", () => {
  const openapi = JSON.parse(fs.readFileSync(path.join(PACKAGE, "openapi.json"), "utf8"));
  openapi.components.schemas.HealthStatus.properties.version = { type: "string", title: "Version" };
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-api-types-"));
  const changed = path.join(dir, "openapi.json");
  fs.writeFileSync(changed, JSON.stringify(openapi, null, 2));

  const { code, output } = run({ OPENAPI_FILE: changed });

  assert.equal(code, 1);
  assert.match(output, /out of date/);
  assert.match(output, /npm run generate -w @ei-ai\/api-types/);
});
