// What `npm run check` runs: the same tasks as .github/workflows/ci.yml, grouped by CI job.
// Each step is [label, argv]; argv starts with node and goes through scripts/task.mjs or dev.mjs.

/** Output a step may print before Node would kill it (a cold Docker build log is long). */
export const STEP_MAX_BUFFER = 64 * 1024 * 1024;

const task = (name, extra = []) => [name, ["scripts/task.mjs", name, ...extra]];

/**
 * @param {{ skipStack?: boolean, native?: boolean }} options
 * @returns {{ job: string, steps: [string, string[]][] }[]}
 */
export function buildPlan({ skipStack = false, native = false } = {}) {
  const backend = native ? ["--native"] : [];
  const plan = [
    {
      job: "frontend",
      steps: ["lint", "typecheck", "test", "build", "api-types"].map((name) =>
        task(`frontend:${name}`),
      ),
    },
    {
      job: "backend",
      steps: ["lint", "format", "typecheck", "test", "openapi"].map((name) =>
        task(`backend:${name}`, backend),
      ),
    },
    {
      job: "checks",
      steps: ["repo:node-checks", "repo:actionlint", "repo:secret-scan"].map((name) => task(name)),
    },
  ];
  if (!skipStack) {
    // Needs the Docker services (db, valkey), like the stack job, so --skip-stack leaves it out.
    plan.push({
      job: "tenant-isolation",
      steps: [task("backend:prepare"), task("backend:test-isolation")],
    });
    plan.push({
      job: "stack",
      steps: [
        ["up (no model)", ["scripts/dev.mjs", "up", "--no-model"]],
        ["smoke", ["scripts/smoke.mjs"]],
        ["seed (1st run)", ["scripts/dev.mjs", "seed"]],
        ["seed (2nd run)", ["scripts/dev.mjs", "seed"]],
        task("backend:test-integration"),
        ["down", ["scripts/dev.mjs", "down"]],
      ],
    });
  }
  return plan;
}
