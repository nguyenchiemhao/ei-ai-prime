import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "./lib/docker.mjs";
import { STEP_MAX_BUFFER, buildPlan } from "./lib/check-plan.mjs";

const workflow = fs.readFileSync(path.join(ROOT, ".github/workflows/ci.yml"), "utf8");

const planTasks = (plan) =>
  plan.flatMap(({ steps }) =>
    steps.filter(([, argv]) => argv[0] === "scripts/task.mjs").map(([, argv]) => argv[1]),
  );

test("check_plan_runs_the_same_tasks_as_the_ci_workflow", () => {
  const inCi = new Set([
    ...[...workflow.matchAll(/scripts\/task\.mjs ([a-z:-]+)/g)].map((match) => match[1]),
    ...[...workflow.matchAll(/npm run backend -- ([a-z-]+)/g)].map(
      (match) => `backend:${match[1]}`,
    ),
  ]);
  assert.deepEqual([...new Set(planTasks(buildPlan()))].sort(), [...inCi].sort());
});

test("check_plan_groups_steps_by_the_ci_jobs_and_skips_the_stack_on_request", () => {
  assert.deepEqual(
    buildPlan().map(({ job }) => job),
    ["frontend", "backend", "checks", "tenant-isolation", "stack"],
  );
  assert.deepEqual(
    buildPlan({ skipStack: true }).map(({ job }) => job),
    ["frontend", "backend", "checks"],
  );
});

test("check_plan_tenant_isolation_job_prepares_the_images_then_runs_the_isolation_suite", () => {
  const job = buildPlan().find(({ job: name }) => name === "tenant-isolation");
  assert.deepEqual(
    job.steps.map(([, argv]) => argv),
    [
      ["scripts/task.mjs", "backend:prepare"],
      ["scripts/task.mjs", "backend:test-isolation"],
    ],
  );
});

test("check_plan_passes_native_to_backend_tasks_only", () => {
  const native = buildPlan({ native: true });
  const argvOf = (job) => native.find((entry) => entry.job === job).steps.map(([, argv]) => argv);
  assert.ok(argvOf("backend").every((argv) => argv.includes("--native")));
  assert.ok(argvOf("frontend").every((argv) => !argv.includes("--native")));
});

test("check_plan_stack_job_stops_the_stack_last_and_seeds_twice", () => {
  const stack = buildPlan()
    .find(({ job }) => job === "stack")
    .steps.map(([, argv]) => argv.join(" "));
  assert.equal(stack.at(-1), "scripts/dev.mjs down");
  assert.equal(stack.filter((command) => command === "scripts/dev.mjs seed").length, 2);
});

test("check_steps_may_print_a_cold_docker_build_log", () => {
  assert.ok(STEP_MAX_BUFFER >= 32 * 1024 * 1024);
});
