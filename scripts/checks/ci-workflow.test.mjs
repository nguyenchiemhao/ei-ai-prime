// EA-13 (SET-03) AC3, AC4, AC5, AC7: structure of .github/workflows/ci.yml (line based, no YAML library).
// A real GitHub run is an owner step; these tests make the file say what the acceptance criteria require.
// Run:  node --test scripts/checks/ci-workflow.test.mjs
// Override the file under test (mutation checks): CI_WORKFLOW=<path>
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";
import { tasks } from "../lib/tasks.mjs";

const WORKFLOW = path.resolve(ROOT, process.env.CI_WORKFLOW || ".github/workflows/ci.yml");
const text = fs.readFileSync(WORKFLOW, "utf8");
const lines = text.split("\n");

/** Job name -> its text, from the 2-space-indented keys under `jobs:`. */
function jobs() {
  const start = lines.findIndex((line) => line === "jobs:");
  assert.notEqual(start, -1, "no jobs: section");
  const result = {};
  let current = null;
  for (const line of lines.slice(start + 1)) {
    const key = line.match(/^ {2}([a-z][a-z0-9-]*):\s*$/);
    if (key) {
      current = key[1];
      result[current] = [];
    } else if (current) result[current].push(line);
  }
  return Object.fromEntries(Object.entries(result).map(([name, body]) => [name, body.join("\n")]));
}

const allJobs = jobs();
const runLines = (body) =>
  [...body.matchAll(/^\s+(?:- )?run: (.+)$/gm)].map((match) => match[1].trim());
const taskCalls = (body) =>
  [...body.matchAll(/scripts\/task\.mjs ([a-z:-]+)/g)].map((match) => match[1]);
const hasTask = (body, ...names) => names.every((name) => taskCalls(body).includes(name));

test("the_workflow_defines_the_five_jobs", () => {
  assert.deepEqual(Object.keys(allJobs).sort(), [
    "backend",
    "checks",
    "frontend",
    "stack",
    "tenant-isolation",
  ]);
});

// Owner decision 2026-10-14: CI runs on every push to any branch (ticket branches and main), so a
// branch is checked without opening a pull request. No pull_request trigger, to avoid double runs.
test("runs_on_every_branch_push", () => {
  const on = text.slice(text.indexOf("\non:"), text.indexOf("\npermissions:"));
  assert.match(on, /^ {2}push:\n {4}branches: \["\*\*"\]$/m);
  assert.doesNotMatch(on, /^ {2}pull_request:/m);
  assert.match(on, /^ {2}workflow_dispatch:/m);
});

test("workflow_permissions_are_read_only", () => {
  assert.match(text, /^permissions:\n {2}contents: read$/m);
});

test("frontend_and_backend_jobs_run_lint_typecheck_and_tests", () => {
  assert.ok(
    hasTask(
      allJobs.frontend,
      "frontend:lint",
      "frontend:typecheck",
      "frontend:test",
      "frontend:build",
      "frontend:api-types",
    ),
  );
  const backend = runLines(allJobs.backend).join("\n");
  for (const task of ["lint", "format", "typecheck", "test", "openapi"]) {
    assert.match(
      backend,
      new RegExp(`npm run backend -- ${task} --native`),
      `backend job does not run ${task}`,
    );
  }
});

test("no_step_continues_on_error", () => {
  assert.doesNotMatch(text, /continue-on-error/);
  assert.doesNotMatch(text, /\|\| true/);
});

test("ci_steps_call_the_shared_task_runner", () => {
  const allowed = [
    /^npm ci$/,
    /^pip install -e "backend\[dev\]"$/,
    /^node scripts\/task\.mjs [a-z:-]+$/,
    /^npm run backend -- [a-z-]+( --native)?$/,
    /^node scripts\/install-compose\.mjs( --verify)?$/,
    /^docker compose version$/,
    /^npm run up -- --no-model$/,
    /^node scripts\/smoke\.mjs$/,
    /^npm run seed$/,
    /^npm run down$/,
  ];
  for (const [name, body] of Object.entries(allJobs)) {
    for (const command of runLines(body)) {
      assert.ok(
        allowed.some((pattern) => pattern.test(command)),
        `${name}: step runs "${command}", which is not a shared task call`,
      );
    }
  }
});

test("every_task_called_in_ci_exists_in_tasks_mjs", () => {
  const called = [...text.matchAll(/scripts\/task\.mjs ([a-z:-]+)/g)].map((match) => match[1]);
  const backend = [...text.matchAll(/npm run backend -- ([a-z-]+)/g)].map(
    (match) => `backend:${match[1]}`,
  );
  assert.ok(called.length >= 8);
  for (const name of [...called, ...backend])
    assert.ok(tasks[name], `task ${name} is not defined in scripts/lib/tasks.mjs`);
});

test("every_job_has_timeout_minutes_at_most_10", () => {
  for (const [name, body] of Object.entries(allJobs)) {
    const timeout = body.match(/^ {4}timeout-minutes: (\d+)$/m);
    assert.ok(timeout, `${name}: no timeout-minutes`);
    assert.ok(Number(timeout[1]) <= 10, `${name}: timeout-minutes ${timeout[1]} > 10`);
    assert.match(body, /^ {4}runs-on: ubuntu-24\.04$/m, `${name}: runs-on must be pinned`);
  }
});

test("jobs_run_in_parallel_with_dependency_cache", () => {
  assert.doesNotMatch(text, /^\s+needs:/m, "jobs must not wait for each other");
  assert.match(allJobs.frontend, /cache: npm/);
  assert.match(allJobs.checks, /cache: npm/);
  assert.match(allJobs.backend, /cache: pip/);
  assert.match(allJobs.backend, /cache-dependency-path: backend\/pyproject\.toml/);
});

test("superseded_runs_are_cancelled", () => {
  assert.match(
    text,
    /^concurrency:\n {2}group: ci-\$\{\{ github\.ref \}\}\n {2}cancel-in-progress: true$/m,
  );
});

test("secret_scan_scans_full_history", () => {
  assert.match(allJobs.checks, /fetch-depth: 0/);
  assert.ok(hasTask(allJobs.checks, "repo:secret-scan"));
});

test("node_checks_cover_design_licence_and_evl01", () => {
  assert.ok(hasTask(allJobs.checks, "repo:node-checks", "repo:actionlint"));
  const config = fs.readFileSync(path.join(ROOT, "scripts/node-checks.config.mjs"), "utf8");
  for (const covered of [
    "docs/design/checks/*.test.mjs",
    "docs/architecture/checks/*.test.mjs",
    "eval/datasets/mekong-devworks/checks/*.test.mjs",
    "eval/datasets/mekong-devworks/tools/validate.mjs",
  ]) {
    assert.ok(config.includes(covered), `scripts/node-checks.config.mjs does not run ${covered}`);
  }
});

test("actions_are_pinned_to_commit_shas", () => {
  const uses = [...text.matchAll(/^\s+- uses: (\S+)(?: # (\S+))?$/gm)];
  assert.ok(uses.length >= 6);
  for (const [, action, comment] of uses) {
    assert.match(
      action,
      /^[\w.-]+\/[\w.-]+@[0-9a-f]{40}$/,
      `${action} is not pinned to a commit SHA`,
    );
    assert.match(comment ?? "", /^v\d/, `${action}: add the version as a comment`);
  }
});

test("stack_job_installs_the_minimum_compose_version_and_always_stops_the_stack", () => {
  const stack = allJobs.stack;
  assert.match(stack, /node scripts\/install-compose\.mjs\n/);
  assert.match(
    stack,
    /node scripts\/install-compose\.mjs --verify/,
    "CI must prove that the minimum Compose is the one running",
  );
  assert.match(stack, /npm run up -- --no-model/);
  assert.match(stack, /node scripts\/smoke\.mjs/);
  assert.equal(
    runLines(stack).filter((command) => command === "npm run seed").length,
    2,
    "seed must run twice (idempotent)",
  );
  assert.match(stack, /npm run backend -- test-integration/);
  assert.match(stack, /if: always\(\)\n\s+run: npm run down/);
});

// EA-19 (FND-02) AC5: the tenant-isolation suite is its own job so it can be a required check. The
// 5-minute cap is on the suite step: image builds and pulls happen in an earlier step, so the cap
// measures the suite and a slow registry cannot fail the required check by itself.
test("tenant_isolation_job_runs_the_suite_within_5_minutes", () => {
  const job = allJobs["tenant-isolation"];
  const jobTimeout = job.match(/^ {4}timeout-minutes: (\d+)$/m);
  assert.ok(jobTimeout && Number(jobTimeout[1]) <= 10, "job timeout-minutes must be 10 or less");
  assert.deepEqual(
    runLines(job),
    ["npm run backend -- prepare", "npm run backend -- test-isolation", "npm run down"],
    "the job prepares the images, runs the isolation suite and stops the stack",
  );
  assert.match(
    job,
    /- run: npm run backend -- test-isolation\n {8}timeout-minutes: 5\n/,
    "the suite step itself is capped at 5 minutes",
  );
  assert.doesNotMatch(
    job.split("npm run backend -- test-isolation")[0],
    /timeout-minutes: 5/,
    "the preparation is not under the suite cap",
  );
  assert.match(job, /if: always\(\)\n\s+run: npm run down/);
  assert.match(job, /actions\/setup-node@[0-9a-f]{40} # v\d/);
  assert.match(job, /node-version: 22/);
});

test("backend_job_pins_node_for_the_task_runner", () => {
  assert.match(allJobs.backend, /actions\/setup-node@[0-9a-f]{40} # v\d/);
  assert.match(allJobs.backend, /node-version: 22/);
});
