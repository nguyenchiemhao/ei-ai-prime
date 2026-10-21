// The single list of verification tasks. `npm run check`, `npm run backend -- <task>` and the CI
// workflow all run these commands through scripts/task.mjs, so local and CI results cannot drift.
//
// A task is either
//   { command: [...] }                     run on the host from the repository root, or
//   { backend: [...], services?: true }    run in the backend dev image (or natively with --native)
//                                          from backend/; `services` starts db and valkey first, or
//   { run: () => exitCode }                a function (container based repository checks).

import { prepareBackendServices } from "./backend-prepare.mjs";
import { actionlint, secretScan } from "./repo-tasks.mjs";

const npm = (...args) => ({ command: ["npm", "run", ...args] });

export const tasks = {
  "frontend:lint": npm("lint"),
  "frontend:typecheck": npm("typecheck"),
  "frontend:test": npm("test:frontend"),
  "frontend:build": npm("build"),
  "frontend:api-types": npm("api-types:check"),

  "backend:lint": { backend: ["ruff", "check", "."] },
  "backend:format": { backend: ["ruff", "format", "--check", "."] },
  "backend:typecheck": { backend: ["mypy"] },
  "backend:test": {
    backend: [
      "pytest",
      "-m",
      "not integration and not benchmark and not isolation",
      "--cov=ei_ai",
      "--cov-report=term-missing",
    ],
  },
  "backend:openapi": { backend: ["pytest", "tests/test_openapi_export.py"] },
  "backend:openapi-export": {
    backend: ["python", "-m", "ei_ai.openapi_export", "../packages/api-types/openapi.json"],
  },
  "backend:test-integration": {
    backend: ["pytest", "-m", "integration and not isolation", "--no-cov"],
    services: true,
  },
  // Pulls and builds what the isolation suite needs, without running tests (its own CI step).
  "backend:prepare": { run: prepareBackendServices },
  // Tenant-isolation suite (FND-02); CI job tenant-isolation, suite step capped at 5 minutes.
  "backend:test-isolation": {
    backend: ["pytest", "-m", "isolation", "--no-cov"],
    services: true,
  },

  // RLS overhead measurement (FND-01 NFR); output goes to docs/architecture/data-model.md.
  "backend:bench-rls": {
    backend: ["pytest", "tests/perf/test_rls_overhead.py", "-m", "benchmark", "--no-cov", "-s"],
    services: true,
  },
  // Model Gateway overhead (EA-24 NFR); output goes to docs/architecture/model-gateway.md.
  "backend:bench-gateway": {
    backend: ["pytest", "tests/perf/test_gateway_overhead.py", "-m", "benchmark", "--no-cov", "-s"],
    services: true,
  },

  "repo:node-checks": { command: ["node", "scripts/run-node-checks.mjs"] },
  "repo:actionlint": { run: actionlint },
  "repo:secret-scan": { run: secretScan },
};

/** Task name for `npm run backend -- <short>` ("lint" -> "backend:lint"). */
export const backendTaskName = (short) => `backend:${short}`;
