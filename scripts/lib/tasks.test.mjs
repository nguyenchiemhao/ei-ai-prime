// Pins what every task runs, so weakening a task (a no-op, a narrower path) cannot go unnoticed:
// CI and `npm run check` both call these tasks.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "./docker.mjs";
import { tasks } from "./tasks.mjs";

const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

test("tasks_pin_the_backend_commands", () => {
  assert.deepEqual(tasks["backend:lint"], { backend: ["ruff", "check", "."] });
  assert.deepEqual(tasks["backend:format"], { backend: ["ruff", "format", "--check", "."] });
  assert.deepEqual(tasks["backend:typecheck"], { backend: ["mypy"] });
  assert.deepEqual(tasks["backend:test"], {
    backend: [
      "pytest",
      "-m",
      "not integration and not benchmark and not isolation",
      "--cov=ei_ai",
      "--cov-report=term-missing",
    ],
  });
  assert.deepEqual(tasks["backend:bench-rls"], {
    backend: ["pytest", "tests/perf/test_rls_overhead.py", "-m", "benchmark", "--no-cov", "-s"],
    services: true,
  });
  assert.deepEqual(tasks["backend:bench-gateway"], {
    backend: ["pytest", "tests/perf/test_gateway_overhead.py", "-m", "benchmark", "--no-cov", "-s"],
    services: true,
  });
  assert.deepEqual(tasks["backend:openapi"], {
    backend: ["pytest", "tests/test_openapi_export.py"],
  });
  assert.deepEqual(tasks["backend:test-integration"], {
    backend: ["pytest", "-m", "integration and not isolation", "--no-cov"],
    services: true,
  });
  assert.deepEqual(tasks["backend:test-isolation"], {
    backend: ["pytest", "-m", "isolation", "--no-cov"],
    services: true,
  });
});

test("backend_prepare_is_a_function_task_that_runs_no_tests", () => {
  assert.equal(typeof tasks["backend:prepare"].run, "function");
});

test("tasks_pin_the_frontend_and_repository_commands", () => {
  assert.deepEqual(tasks["frontend:lint"].command, ["npm", "run", "lint"]);
  assert.deepEqual(tasks["frontend:typecheck"].command, ["npm", "run", "typecheck"]);
  assert.deepEqual(tasks["frontend:test"].command, ["npm", "run", "test:frontend"]);
  assert.deepEqual(tasks["frontend:build"].command, ["npm", "run", "build"]);
  assert.deepEqual(tasks["frontend:api-types"].command, ["npm", "run", "api-types:check"]);
  assert.deepEqual(tasks["repo:node-checks"].command, ["node", "scripts/run-node-checks.mjs"]);
  assert.equal(typeof tasks["repo:actionlint"].run, "function");
  assert.equal(typeof tasks["repo:secret-scan"].run, "function");
});

test("tasks_npm_scripts_run_the_real_tools_over_the_whole_repository", () => {
  const scripts = packageJson.scripts;
  assert.equal(scripts.lint, "eslint . && prettier --check .");
  assert.equal(
    scripts.typecheck,
    "npm run typecheck --workspaces --if-present && tsc --noEmit -p e2e",
  );
  assert.equal(scripts["test:frontend"], "npm run test --workspaces --if-present");
  assert.equal(
    scripts.build,
    "npm run build -w @ei-ai/design-tokens && npm run build -w @ei-ai/admin -w @ei-ai/widget",
  );
  assert.equal(
    scripts.prebuild,
    undefined,
    "the tokens are built once, by the build script itself",
  );
  for (const app of ["admin", "widget"]) {
    const appScripts = JSON.parse(
      fs.readFileSync(path.join(ROOT, `apps/${app}/package.json`), "utf8"),
    ).scripts;
    assert.equal(appScripts.typecheck, "tsc --noEmit");
    assert.equal(appScripts.test, "vitest run");
    assert.equal(appScripts.build, "vite build");
  }
});

test("every_task_runs_something", () => {
  for (const [name, task] of Object.entries(tasks)) {
    assert.ok(task.command?.length || task.backend?.length || task.run, `${name} runs nothing`);
  }
});
