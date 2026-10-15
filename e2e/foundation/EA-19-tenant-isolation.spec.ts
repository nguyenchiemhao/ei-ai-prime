// EA-19 (FND-02): automated tenant-isolation suite that runs in CI. Profile api, no browser.
// Runs against the running stack (db and valkey are started by the task itself):
//   npm run up && npm run migrate && npx playwright test e2e/foundation/EA-19-*
// The suite is run as a developer would run it (npm run backend -- test-isolation). Mutation runs
// (a new route, a leaky route, a leaky job, a raw Valkey key) happen in a scratch COPY of the repository
// under the tmp folder with its own Compose project (ei-ai-qa19), so the main database, volumes and the
// working tree are never touched. The scratch project and its volumes are removed in afterAll.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const ROOT = path.resolve(import.meta.dirname, "..", "..");
const NODE = process.execPath;
const QA_PROJECT = "ei-ai-qa19";
const SKIP_DIRS = new Set(["node_modules", ".git", ".work", "__pycache__", ".mypy_cache"]);
const SKIP_CACHES = new Set([".pytest_cache", ".ruff_cache"]);

function run(command: string, args: string[], cwd: string, env: NodeJS.ProcessEnv = process.env) {
  const result = spawnSync(command, args, {
    cwd,
    env,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  return { status: result.status, output };
}

const TIMING_FILE = path.join(ROOT, ".work", "EA-19", "isolation-seconds.txt");

test.describe("EA-19 tenant-isolation suite in CI", { tag: "@slow" }, () => {
  let scratch = "";
  const scratchEnv = { ...process.env, COMPOSE_PROJECT_NAME: QA_PROJECT };

  /** `npm run backend -- <task>` inside the scratch copy. */
  const backend = (task: string) => run(NODE, ["scripts/backend.mjs", task], scratch, scratchEnv);
  const touched = new Set<string>();
  /** Path of a file in the scratch copy; every file a test touches is put back by resetScratch(). */
  const scratchFile = (relative: string) => {
    touched.add(relative);
    return path.join(scratch, ...relative.split("/"));
  };
  const resetScratch = () => {
    for (const relative of touched) {
      const original = path.join(ROOT, ...relative.split("/"));
      const copy = path.join(scratch, ...relative.split("/"));
      if (fs.existsSync(original)) fs.copyFileSync(original, copy);
      else fs.rmSync(copy, { force: true });
    }
    touched.clear();
  };
  const restore = (relative: string) =>
    fs.copyFileSync(path.join(ROOT, ...relative.split("/")), scratchFile(relative));
  const append = (relative: string, text: string) => fs.appendFileSync(scratchFile(relative), text);
  const replaceIn = (relative: string, from: string, to: string) => {
    const file = scratchFile(relative);
    const before = fs.readFileSync(file, "utf8");
    expect(before, `${relative} must contain: ${from}`).toContain(from);
    fs.writeFileSync(file, before.replace(from, to));
  };

  test.beforeAll(() => {
    scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-qa19-"));
    fs.cpSync(ROOT, scratch, {
      recursive: true,
      filter: (source) => {
        const name = path.basename(source);
        return !(SKIP_DIRS.has(name) || SKIP_CACHES.has(name) || name === ".env");
      },
    });
  });

  test.afterAll(() => {
    if (!scratch) return;
    // Remove the scratch Compose project: containers, its database volume, local images, network.
    run(
      "docker",
      ["compose", "--profile", "tools", "--profile", "core", "down", "--volumes", "--rmi", "local"],
      scratch,
      scratchEnv,
    );
    fs.rmSync(scratch, { recursive: true, force: true });
  });

  test("AC1: every authenticated route called by org A with org B ids returns 403/404, never B's data", async ({
    request,
  }) => {
    test.setTimeout(6 * 60_000);
    const started = Date.now();
    const suite = run(NODE, ["scripts/backend.mjs", "test-isolation"], ROOT);
    fs.writeFileSync(TIMING_FILE, String((Date.now() - started) / 1000));
    expect(suite.status, suite.output.slice(-4000)).toBe(0);
    expect(suite.output).toMatch(/\d+ passed/);
    expect(suite.output).not.toMatch(/\d+ (failed|errors?)\b/);
    expect(suite.output).not.toMatch(/Traceback/);

    // The cross-tenant cases of GET /organization exist for both directions, and public routes are checked.
    const listing = run(
      "docker",
      [
        "compose",
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "backend-tools",
        "pytest",
        "-m",
        "isolation",
        "-k",
        "test_routes_isolated",
        "-v",
        "--no-cov",
        "-p",
        "no:cacheprovider",
      ],
      ROOT,
    );
    expect(listing.status, listing.output.slice(-3000)).toBe(0);
    for (const id of [
      "test_route_is_isolated[GET /organization A->B] PASSED",
      "test_route_is_isolated[GET /organization B->A] PASSED",
      "test_public_route_returns_no_tenant_data[GET /healthz] PASSED",
      "test_public_route_returns_no_tenant_data[GET /readyz] PASSED",
    ]) {
      expect(listing.output).toContain(id);
    }

    // Live check on the running API: a forged org id with no credential is a plain 401 without the id.
    const forged = "5d1b7c52-6c0e-4d0a-9a53-0c0f1f6f7a99";
    const response = await request.get(`${API_URL}/organization?org_id=${forged}`, {
      headers: { "X-Org-Id": forged },
    });
    expect(response.status()).toBe(401);
    expect(await response.text()).toBe('{"detail":"unauthenticated"}');
    expect(
      run("docker", ["compose", "logs", "--no-color", "api"], ROOT).output,
      "forged value in the API log",
    ).not.toContain(forged);
  });

  test("AC2: a new route without a declaration fails CI with 'route has no isolation test declared'", () => {
    test.setTimeout(12 * 60_000);
    resetScratch();
    const probe = (body: string) => `

@router.get("/organization/probe", response_model=CurrentOrganization, summary="QA probe")
${body}
`;
    const filtered = `async def probe_organization(
    tenant: Annotated[TenantContext, Depends(require_tenant)],
    session: TenantSession,
) -> CurrentOrganization:
    row = (
        await session.execute(
            select(Organization.id, Organization.name).where(Organization.id == tenant.org_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return CurrentOrganization(id=row.id, name=row.name)`;
    const orgFromHeader = `async def probe_organization(
    request: Request,
    tenant: Annotated[TenantContext, Depends(require_tenant)],
) -> CurrentOrganization:
    org = UUID(request.headers.get("x-org-id", str(tenant.org_id)))
    async with tenant_session(request.app.state.engine, org) as session:
        row = (
            await session.execute(
                select(Organization.id, Organization.name).where(Organization.id == org)
            )
        ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return CurrentOrganization(id=row.id, name=row.name)`;
    const organizationPy = "backend/src/ei_ai/api/organization.py";
    const casesPy = "backend/tests/integration/isolation/cases.py";

    // 1. Baseline of the copy is green (also proves the copy runs in its own Compose project).
    const baseline = backend("test-isolation");
    expect(baseline.status, baseline.output.slice(-3000)).toBe(0);

    // 2. A new authenticated route without a declaration: red with the exact message.
    append(organizationPy, probe(filtered));
    const undeclared = backend("test-isolation");
    expect(undeclared.status).not.toBe(0);
    expect(undeclared.output).toContain(
      "route has no isolation test declared: GET /organization/probe",
    );

    // 3. Declared as OwnTenantRoute and correct: green.
    replaceIn(
      casesPy,
      '    OwnTenantRoute("GET", "/organization"),',
      '    OwnTenantRoute("GET", "/organization"),\n    OwnTenantRoute("GET", "/organization/probe"),',
    );
    const declared = backend("test-isolation");
    expect(declared.status, declared.output.slice(-3000)).toBe(0);

    // 4. The route takes the Organization from a header (D32 violation): red, naming the other Organization.
    restore(organizationPy);
    replaceIn(
      organizationPy,
      "from fastapi import APIRouter, Depends, HTTPException",
      "from fastapi import APIRouter, Depends, HTTPException, Request\nfrom ei_ai.db.tenant import tenant_session",
    );
    append(organizationPy, probe(orgFromHeader));
    const leaky = backend("test-isolation");
    expect(leaky.status).not.toBe(0);
    expect(leaky.output).toMatch(
      /GET \/organization\/probe \((A->B|B->A)\): cross-Organization call: response body: \d+ marker\(s\) of Organization [AB] found/,
    );

    // 5. A request model that names an Organization: red with the field message.
    restore(organizationPy);
    append(
      organizationPy,
      `

class ProbeBody(BaseModel):
    org_id: UUID


@router.post("/organization/probe-body", status_code=201)
async def probe_body(
    body: ProbeBody, tenant: Annotated[TenantContext, Depends(require_tenant)]
) -> dict[str, str]:
    return {}
`,
    );
    const field = backend("test-isolation");
    expect(field.status).not.toBe(0);
    expect(field.output).toContain(
      "POST /organization/probe-body: request field org_id names an Organization (D32)",
    );
  });

  test("AC3: a background job runs with tenant context A and cannot read or write org B data", () => {
    test.setTimeout(12 * 60_000);
    resetScratch();
    // The job tests of the real tree (db and valkey are up after AC1).
    const jobs = run(
      "docker",
      [
        "compose",
        "--profile",
        "tools",
        "run",
        "--rm",
        "-T",
        "backend-tools",
        "pytest",
        "-m",
        "isolation",
        "-k",
        "test_jobs_isolated",
        "-v",
        "--no-cov",
        "-p",
        "no:cacheprovider",
      ],
      ROOT,
    );
    expect(jobs.status, jobs.output.slice(-3000)).toBe(0);
    for (const name of [
      "test_job_runs_with_the_tenant_context_of_its_envelope PASSED",
      "test_job_for_a_cannot_read_b_rows PASSED",
      "test_job_for_a_cannot_update_or_delete_b_rows[sample.update] PASSED",
      "test_job_for_a_cannot_update_or_delete_b_rows[sample.delete] PASSED",
      "test_job_for_a_cannot_insert_rows_for_b PASSED",
      "test_failed_job_rolls_back_and_leaves_no_context PASSED",
      "test_next_job_on_the_same_connection_sees_only_its_own_org PASSED",
      "test_every_registered_job_has_an_isolation_case PASSED",
    ]) {
      expect(jobs.output).toContain(name);
    }

    // Scratch copy, following the README: register a job handler, queue it through the registry.
    const jobModule = (body: string) => `"""QA probe job."""

from collections.abc import Mapping

from sqlalchemy import text

from ei_ai.jobs.envelope import JobContext
from ei_ai.jobs.registry import JOBS


@JOBS.register("ws.rename")
async def rename(context: JobContext, payload: Mapping[str, object]) -> None:
${body}
`;
    const safe = `    await context.session.execute(
        text("UPDATE workspaces SET name = 'renamed' WHERE id = :id"),
        {"id": payload["workspace_id"]},
    )`;
    const leaky = `    await context.session.execute(
        text("SELECT set_config('app.current_org', :o, true)"), {"o": payload["owner"]}
    )
    await context.session.execute(
        text("UPDATE workspaces SET name = 'renamed' WHERE id = :id"),
        {"id": payload["workspace_id"]},
    )`;
    const modulePy = scratchFile("backend/src/ei_ai/jobs/ws_rename.py");
    fs.writeFileSync(modulePy, jobModule(safe));
    append(
      "backend/src/ei_ai/jobs/__init__.py",
      "from ei_ai.jobs import ws_rename as _ws_rename  # noqa: F401\n",
    );

    // An imported handler without a JobCase fails the build.
    const undeclared = backend("test-isolation");
    expect(undeclared.status).not.toBe(0);
    expect(undeclared.output).toContain("job has no isolation test declared: ws.rename");

    // Declared and correct: green.
    const casesPy = "backend/tests/integration/isolation/cases.py";
    replaceIn(
      casesPy,
      "JOB_CASES: tuple[JobCase, ...] = ()",
      'JOB_CASES: tuple[JobCase, ...] = (\n    JobCase("ws.rename", lambda rows: {"workspace_id": str(rows.workspace_id), "owner": str(rows.org_id)}),\n)',
    );
    const declared = backend("test-isolation");
    expect(declared.status, declared.output.slice(-3000)).toBe(0);

    // A handler that switches to the Organization named in its payload writes into the other tenant: red.
    fs.writeFileSync(modulePy, jobModule(leaky));
    const leak = backend("test-isolation");
    expect(leak.status).not.toBe(0);
    expect(leak.output).toMatch(
      /job ws\.rename \((A->B|B->A)\): data of Organization [AB] changed/,
    );
  });

  test("AC4: every Valkey key carries org_id; code outside the cache wrapper cannot talk to Valkey", () => {
    test.setTimeout(12 * 60_000);
    resetScratch();
    // After AC1/AC3 the real database holds no key outside the org:<uuid>: prefix.
    const keys = run("docker", ["compose", "exec", "-T", "valkey", "valkey-cli", "--scan"], ROOT);
    expect(keys.status, keys.output).toBe(0);
    for (const key of keys.output.split("\n").filter(Boolean)) {
      expect(key).toMatch(/^org:[0-9a-f-]{36}:/);
    }

    // A module outside ei_ai/cache that imports redis fails the backend unit run.
    fs.writeFileSync(
      scratchFile("backend/src/ei_ai/api/ratelimit.py"),
      "from redis import asyncio as aioredis\n\nCLIENT = aioredis\n",
    );
    const guard = backend("test");
    expect(guard.status).not.toBe(0);
    expect(guard.output).toContain("ei_ai.api.ratelimit talks to Valkey directly");
    fs.rmSync(scratchFile("backend/src/ei_ai/api/ratelimit.py"));

    // A route that, besides the wrapper, writes a key without the Organization: the suite's scan fails.
    fs.writeFileSync(
      scratchFile("backend/src/ei_ai/api/hits.py"),
      `import os
from typing import Annotated

from fastapi import APIRouter, Depends
from redis import asyncio as aioredis

from ei_ai.cache import TenantCache
from ei_ai.tenancy.context import TenantContext, require_tenant

router = APIRouter()


@router.get("/hits")
async def hits(tenant: Annotated[TenantContext, Depends(require_tenant)]) -> dict[str, str | int]:
    client = aioredis.from_url(os.environ["VALKEY_URL"])
    try:
        n = await TenantCache(client, tenant).incr("hits", ttl_seconds=60)
        await client.set("hits:global", n, ex=60)
    finally:
        await client.aclose()
    return {"org": str(tenant.org_id), "n": n}
`,
    );
    replaceIn(
      "backend/src/ei_ai/main.py",
      "from ei_ai.api import health, organization",
      "from ei_ai.api import health, hits, organization",
    );
    replaceIn(
      "backend/src/ei_ai/main.py",
      "    app.include_router(organization.router)",
      "    app.include_router(organization.router)\n    app.include_router(hits.router)",
    );
    replaceIn(
      "backend/tests/integration/isolation/cases.py",
      '    OwnTenantRoute("GET", "/organization"),',
      '    OwnTenantRoute("GET", "/organization"),\n    OwnTenantRoute("GET", "/hits"),',
    );
    const raw = backend("test-isolation");
    expect(raw.status).not.toBe(0);
    expect(raw.output).toMatch(/Valkey key\(s\) outside the org:<uuid>: prefix/);
  });

  test("AC5: the suite finishes within 5 minutes and CI runs it as the tenant-isolation job", () => {
    // Measured in AC1 (includes image build check and stack start, warm).
    expect(fs.existsSync(TIMING_FILE), "AC1 must have run first").toBe(true);
    const isolationSeconds = Number(fs.readFileSync(TIMING_FILE, "utf8"));
    expect(isolationSeconds).toBeLessThanOrEqual(5 * 60);

    const workflow = fs.readFileSync(path.join(ROOT, ".github/workflows/ci.yml"), "utf8");
    const job = workflow.slice(workflow.indexOf("\n  tenant-isolation:"));
    const jobBody = job.slice(0, job.indexOf("\n  stack:"));
    expect(jobBody).toContain("npm run backend -- test-isolation");
    expect(jobBody).toMatch(
      /- run: npm run backend -- test-isolation\n\s+timeout-minutes: ([1-5])\n/,
    );
    expect(jobBody).toMatch(/if: always\(\)\n\s+run: npm run down/);

    const unit = run(NODE, ["--test", "scripts/checks/ci-workflow.test.mjs"], ROOT);
    expect(unit.status, unit.output.slice(-3000)).toBe(0);
    // Marking tenant-isolation as a required check is a repository setting (owner step): pending owner.
    test.info().annotations.push({ type: "pending-owner", description: "required check setting" });
  });
});
