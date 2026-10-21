# ei-ai

Embeddable enterprise AI assistant: a Python/FastAPI backend, a React admin UI, a Preact chat widget, a local ~4B model on CPU and a one-command local environment. Product decisions are in `docs/workshop/`, UI decisions in `docs/design/design-decisions.md`, the tech stack in `docs/architecture/adr-001-tech-stack.md`, the backlog in Jira project EA (`docs/backlog/backlog.md`).

This repository is also worked on by AI agents. The rules for humans and agents are the same: `CLAUDE.md` and `docs/dev/coding-rules.md`.

> Older tickets say `make up` and `make seed`. There is no Makefile: `make up` means `npm run up` and `make seed` means `npm run seed`. The commands are plain Node scripts (no `npm install` needed to start the stack), so they work the same on Windows, macOS and Linux.

## What this is

A monorepo with:

- `backend/` - FastAPI service (`/healthz`, `/readyz`), settings, the `ei-ai seed demo` command.
- `apps/admin/` - React admin UI (English by default, Vietnamese switch).
- `apps/widget/` - Preact widget (Vietnamese or English by browser language).
- `packages/` - shared design tokens (compiled to CSS variables), the VI/EN message catalog and the API types generated from the backend OpenAPI document.
- `compose.yaml` - the local integration environment: PostgreSQL 16 + pgvector, Valkey 8, llama.cpp with the pinned ~4B model, API, admin UI and widget.

It is the environment where every later acceptance criterion is verified (there is no staging yet).

## Prerequisites

- **Docker** with Compose v2: Docker Desktop (Windows with WSL2, macOS) or Docker Engine (Linux). Docker Compose **2.20.3 or newer** (`docker compose version`); `npm run up` refuses an older version. CI runs exactly 2.20.3.
- **Node 22.12 or newer** and npm (the root scripts, the frontends and the document checks).
- **Git** (Windows: Git for Windows; see Troubleshooting for Git Bash).
- No local Python is needed: backend tools run in a container (`npm run backend -- <task>`).
- **Windows with WSL2, running the model:** Docker Desktop gives the WSL2 VM about half of the machine's RAM. On a 16 GB machine that is about 6.7-7.2 GB, less than the sum of the container memory limits (see Memory budget). The model alone needs 3-5 GB, so it can work, but the safe setting is 10 GB. Create `%UserProfile%\.wslconfig`:

  ```
  [wsl2]
  memory=10GB
  ```

  then run `wsl --shutdown` and restart Docker Desktop. `npm run up` prints this advice when the limits exceed the memory Docker has. Without the model (`--no-model`) the default is enough.

## Quick start

```
git clone <repository-url>
cd ei-ai-prime
npm run up
```

On the first run `npm run up` creates `.env` with generated passwords (git-ignored; keep it, the database volume uses these passwords), builds the images, starts the database, applies the database migrations (`schema guard: 0 violations` must be printed), starts every service and waits until all are healthy. It prints the elapsed time and the URLs:

| What | URL |
|---|---|
| Admin UI | http://localhost:3000 |
| Widget | http://localhost:3001 |
| API health | http://localhost:8000/healthz (readiness: `/readyz`) |

All ports are bound to `127.0.0.1` only. They are fixed, except the admin UI port: set `ADMIN_PORT` in `.env` (for example `ADMIN_PORT=3100`) when 3000 is taken by another program; `compose.yaml`, `npm run up`, the smoke test, Playwright and the set-password links all follow it. The database, Valkey and the model server have no published port.

- **First run time:** measured once on the development machine with a fast connection, the Docker image cache holding the base images (python, node, nginx, pgvector, valkey, llama.cpp) and an empty model volume: about 2.5 minutes in total (26 s to build the images without cache, 119 s to start every service including the 2.5 GB model download). The target is 10 minutes. With no cached base images add the time to pull about 1.6 GB; on a slow link use `--no-model` and add the model later.
- **Warm start** (images built, model file cached): about 20 seconds with the model; about 35 seconds on the very first core-only start (image build included).
- `npm run up -- --no-model` starts everything except the model server: no 2.5 GB download and about 1.5 GB less RAM.
- `npm run up -- --demo` also starts the `demo` profile (the host demo site and the HR API mock arrive with tickets WGT-10 and SKL-04; nothing is in that profile yet).
- **Reuse a model you already downloaded:** put `MODEL_CACHE_VOLUME=<volume name>` in `.env` (for example `ei-ai-stack-spike_model-cache` from the EA-11 spike). The default volume is `ei-ai-model-cache`.
- `npm run ps` shows the status, `npm run logs -- api` the recent logs of one service, `npm run down` stops everything (data is kept), `npm run reset` stops everything and deletes the database volume only (never the model cache).
- Hot-reload development on the host: `npm install`, then `npm run dev:admin` (http://localhost:5173) or `npm run dev:widget` (http://localhost:5174); the admin dev server proxies `/api` to the API on port 8000.

## Seed data

```
npm run seed
```

Runs `ei-ai seed demo` inside the API container. It refuses to run unless the environment is `local` or `test` (exit code 2, before any other setting is read or the database is touched). It loads the versioned Mekong Devworks manifest (`backend/src/ei_ai/seed/data/mekong-devworks.json`: Organization "Mekong Devworks" with the fixed id `0192a000-0000-7000-8000-00000000ea21`, Workspace "People Ops", six members with their role codes, six collections) as the application role in one tenant transaction, and writes an audit event for every object it creates. In the same transaction it adds the three platform models (`qwen3-4b-instruct-2507@2026.10`, `bge-m3@2026.10`, `bge-reranker-v2-m3@2026.10`) to the demo Organization's model catalog, without audit events or output lines (EA-24). It also creates six collections in "People Ops" when none of that name (ignoring case) exists, each with a `collection.created` audit event and no documents: "Company & Careers" (Public), "Employee Handbook", "Engineering Standards" and "IT & Security" (Authenticated), "Manager Handbook" (Restricted to `managers`, local model only) and "Project Falcon" (subtitle "Client: Japan · under NDA", Restricted to `project-falcon`, local model only) (EA-32). A renamed or changed collection is left as it is. It is idempotent: it creates only what is missing and never changes or deletes an existing row, so a second run writes nothing and prints the same output every time (`already present`, `Audit events written: 0`). It never repairs memberships: if "People Ops" was deleted or renamed by hand, a run recreates it without adding the existing members (`npm run reset` gives a clean demo). A run that creates members prints one set-password link per new member (valid 24 hours, shown once); for a fresh link later, use `ei-ai user link` (below). If another Organization already holds the name "Mekong Devworks", the seed stops with exit code 1.

## Sign in locally

1. `npm run reset` once if the database was created before EA-22 (a new database role is created only on a fresh database; this deletes the local database), then `npm run up` and `npm run seed`.
2. The seed prints a set-password link per new member, for example `http://localhost:3000/set-password#token=<org-id>.<secret>`. For a fresh link later: `docker compose exec -T api ei-ai user link --org 0192a000-0000-7000-8000-00000000ea21 --email linh.tran@mekongdevworks.example`. Only the newest link of a user works; issuing a new link, or a forgot-password request, kills the older unused ones.
3. Open the link, set a password of at least 12 characters, then sign in at http://localhost:3000 with the email and that password. You land on the Dashboard of your default Workspace.
4. Forgot password: the reset link is not emailed; the API prints one line, `Reset link (valid 24 h, shown once): http://localhost:3000/reset#token=...`, which you read with `docker compose logs api`.
5. To try the Workspace switcher, create a second Workspace and add the user to it (see "Platform Operator CLI": `workspace create`, `workspace add-member`).

## Platform Operator CLI

The Platform Operator onboards a customer from a shell in the API container (there is no platform admin UI yet). Run the commands with `docker compose exec -T api ei-ai <command>`:

| Command | Example | Result |
|---|---|---|
| `org create --name NAME --owner EMAIL [--owner-name DISPLAY_NAME] [--workspace-name NAME]` | `ei-ai org create --name "Mekong Devworks" --owner linh.tran@mekongdevworks.example` | the Organization, its default Workspace (`Default`) and the Org Owner (also Workspace Admin), plus a set-password link |
| `workspace create --org ORG_ID --name NAME` | `ei-ai workspace create --org 0192a000-0000-7000-8000-00000000ea21 --name "Finance"` | a Workspace in the Organization |
| `workspace add-member --org ORG_ID --workspace WORKSPACE_ID --email EMAIL --role ROLE` | `ei-ai workspace add-member --org <org-id> --workspace <workspace-id> --email minh.pham@example.com --role viewer` | puts an existing user of the Organization into another Workspace of it with a Workspace role (`workspace_admin`, `developer`, `builder`, `knowledge_editor`, `reviewer`, `viewer`, `member`), so a tester can switch Workspaces; prints `Workspace member added: <user-id> (<email>) role: <role>`; fails if the user or Workspace is not in the Organization or the user is already a member |
| `user invite --org ORG_ID --email EMAIL --role ROLE [--role ROLE] [--workspace WORKSPACE_ID] [--name DISPLAY_NAME]` | `ei-ai user invite --org <org-id> --email minh.pham@example.com --role builder --workspace <workspace-id>` | a user with at most one Organization role (`org_owner`, `org_admin`) and one Workspace role (`workspace_admin`, `developer`, `builder`, `knowledge_editor`, `reviewer`, `viewer`, `member`; needs `--workspace`), plus a set-password link |
| `user link --org ORG_ID --email EMAIL` | `ei-ai user link --org <org-id> --email minh.pham@example.com` | a new set-password link; the user's earlier unused links stop working |
| `seed demo` | `ei-ai seed demo` | the demo data (see "Seed data") |
| `model add --org ORG_ID --model MODEL_ID@VERSION` | `ei-ai model add --org <org-id> --model qwen3-4b-instruct-2507@2026.10` | copies a platform model (`bge-m3@2026.10`, `bge-reranker-v2-m3@2026.10`, `qwen3-4b-instruct-2507@2026.10`) into the Organization's model catalog: `added: <ref> (<kind>, <deployment>)`, or `already present: <ref>` with nothing written |
| `model try --org ORG_ID --model MODEL_ID@VERSION [--prompt TEXT] [--max-tokens N]` | `ei-ai model try --org 0192a000-0000-7000-8000-00000000ea21 --model qwen3-4b-instruct-2507@2026.10` | streams one chat answer through the Model Gateway, then prints `done: model=… digest=… prompt_tokens=… completion_tokens=… attempts=… first_token_ms=… total_ms=…`; a gateway error prints `error: <CODE>: <message>` (codes in `docs/architecture/model-gateway.md`) |

- Names are trimmed; emails are trimmed and lowercased. Organization names are unique across the platform (case-insensitive); Workspace names per Organization; emails per Organization.
- A set-password link looks like `http://localhost:3000/set-password#token=<org-id>.<secret>`. The token sits in the URL fragment, which the browser never sends to a server, so it cannot reach the admin access log, a proxy or a Referer header. It is valid for 24 hours, works once, is printed on stdout only and never logged; the database stores only its SHA-256 hash. The base URL comes from `ADMIN_BASE_URL` (Compose sets `http://localhost:${ADMIN_PORT:-3000}`; required in production). See "Sign in locally" for how to use it.
- Every successful command writes audit events (actor `platform-operator`, action, target) in the same transaction as its rows; a failing command writes nothing. `model try` writes no row; a call to a cloud model while the Organization's "Allow cloud models" switch is off is audited as `model.cloud_call_blocked`.
- Exit codes: `0` done; `1` validation error, conflict, not found, configuration or database error (one `error: ...` line on stderr, never SQL or connection details); `2` usage error (unknown command, missing required flag) or `seed demo` refused outside `local`/`test`.

## Running tests and checks

| Command | What it runs |
|---|---|
| `npm ci` | Install the Node dependencies (needed for the frontends and the checks, not for `npm run up`) |
| `npm run lint` | ESLint (including the no-hard-coded-text rule) and Prettier check for the frontends |
| `npm run format` | Prettier write |
| `npm run typecheck` | TypeScript strict type check of every workspace |
| `npm run test:frontend` | Vitest unit tests of admin, widget |
| `npm run build` | Compile the design tokens, then build admin and widget |
| `npm run api-types:check` | The generated API types match the committed OpenAPI document |
| `npm run backend -- lint` | `ruff check` in the backend-tools container |
| `npm run backend -- format` | `ruff format --check` |
| `npm run backend -- typecheck` | `mypy` (strict) |
| `npm run backend -- test` | pytest unit tests with a 70 % coverage gate |
| `npm run backend -- openapi` | The committed OpenAPI document matches the app (`npm run backend -- openapi-export` rewrites it) |
| `npm run backend -- test-integration` | Starts the database and Valkey, applies the migrations, then runs the integration tests against them (the tenant-isolation suite is excluded, it has its own command) |
| `npm run backend -- prepare` | Pulls the database and Valkey images and builds the backend tools and migrate images; runs no test (CI runs it before the isolation suite so that suite's time limit measures the suite) |
| `npm run backend -- test-isolation` | The tenant-isolation suite (FND-02): every route, job and cache key, plus the FND-01 cross-Organization database tests; see [Writing isolation tests](#writing-isolation-tests) |
| `npm run migrate` | Starts the database if needed and applies the database migrations as the owner role, then runs the schema guard; safe to repeat |
| `npm run backend -- bench-rls` | The RLS overhead benchmark (100 000 rows, FND-01); not part of `npm run check` |
| `npm run backend -- bench-gateway` | The Model Gateway overhead benchmark (EA-24 NFR, < 20 ms per call; results in `docs/architecture/model-gateway.md`); not part of `npm run check` |
| `npm run backend -- bench-vn-text` | The Vietnamese normalisation throughput benchmark (EA-28 NFR, >= 1 MB/s; results and rules in `backend/src/ei_ai/vn_text/README.md`); not part of `npm run check` |
| `node scripts/run-node-checks.mjs` | Document and repository checks (design tokens, licence review, ADR, EVL-01 data set, packages, scripts); fails when a pattern matches no file or a check runs 0 tests |
| `npm test` | Frontend tests, Node checks and backend unit tests |
| `npm run check` | **Everything CI runs**, in five jobs (frontend, backend, checks, tenant-isolation, stack), with PASS/FAIL and the duration of each step. `-- --skip-stack` skips the two jobs that need Docker (tenant-isolation and stack); the stack job starts the stack without the model and stops it at the end. |

Add `--native` after a backend task (`npm run backend -- lint --native`; not for `test-integration`, which needs the Compose services) to run it on the host with Python 3.12 (`pip install -e "backend[dev]"`), as CI does.

Playwright end-to-end tests live in `e2e/` (specs `e2e/<area>/<ticket>-<slug>.spec.ts`; configuration in `playwright.config.ts`). They run against an already running stack:

```
npx playwright install chromium     # once per machine: downloads the test browser
npm run up && npm run seed          # the stack the specs talk to
npm run e2e                         # fast tier (skips @slow and @perf); or: npm run e2e -- e2e/<area>/<ticket>-<slug>.spec.ts
npm run e2e:full                    # every spec, including @slow (repository copies, task re-runs) and @perf
npm run e2e:perf                    # only the @perf specs (benchmarks, timings)
```

Tag a test `{ tag: "@slow" }` when it copies the repository, starts a second Compose project or re-runs whole task suites, and `{ tag: "@perf" }` when it measures time or overhead. The fast tier runs in every QA round; `@slow` and `@perf` run once when a ticket is finished, or when you change their area (test tiers: `docs/dev/coding-rules.md` §3.1).

`ADMIN_URL` is the base URL (default `http://localhost:3000`, or the `ADMIN_PORT` of the shell or `.env`); the HTML report goes to `.work/playwright-report/` and traces of failed tests to `.work/playwright-results/` (git-ignored). `npm run lint` and `npm run typecheck` cover the specs and the config too.

## Folder structure

| Directory | Contents |
|---|---|
| `.claude/` | Agent team definitions and skills for the ticket workflow |
| `.github/` | CI workflow (`workflows/ci.yml`) |
| `apps/` | `admin/` (React) and `widget/` (Preact), each with its Dockerfile |
| `backend/` | Python package `ei_ai`, tests, Dockerfile |
| `docs/` | Workshop decisions, architecture (ADR-001, licence review), design (tokens checks, canvas), backlog, dev rules |
| `e2e/` | Playwright end-to-end specs per ticket (`e2e/<area>/<ticket>-<slug>.spec.ts`) and their tsconfig; configuration is `playwright.config.ts` at the root |
| `eval/` | Evaluation data sets (EVL-01 Mekong Devworks) and their checks |
| `examples/` | Reserved slots for the host demo site and the HR API mock (profile `demo`) |
| `infra/` | Infrastructure files mounted into containers (database init scripts: roles) |
| `packages/` | `design-tokens/`, `i18n/`, `api-types/` shared by the apps |
| `scripts/` | Node scripts behind the `npm run` commands, the repository checks and CI helpers (no npm dependencies) |

## Verify acceptance criteria locally

Staging does not exist yet, so a ticket's acceptance criteria are verified in this environment:

1. `npm run up` (add `--no-model` when the criterion does not need the model) and `npm run seed`.
2. Run the unit and integration tests of the ticket (`npm test`, `npm run backend -- test-integration`) and `npm run check` for the whole pipeline.
3. For UI behaviour, run the Playwright spec of the ticket (`npm run e2e -- e2e/<area>/<ticket>-<slug>.spec.ts`); every spec has one `test()` per criterion, titled `AC<n>: ...`.
4. Pipeline criteria (lint, type check, CI time, secret scan) are verified by running the same commands (`npm run check`) and by a real GitHub run, which is an owner step after the branch is pushed.
5. Keep evidence (command output, screenshots) in `.work/EA-<n>/` (git-ignored scratch space).
6. `npm run down` when finished.

## Writing isolation tests

Tenant isolation (D46) is a gate, not a review item. The suite lives in `backend/tests/integration/isolation/` (plus the FND-01 database tests, which carry the same `isolation` marker) and runs with one command, locally and in the CI job `tenant-isolation` (5 minute limit):

```
npm run backend -- test-isolation     # starts db and valkey, applies the migrations, then pytest -m isolation
```

It proves four things. **Every route is covered:** the routes of the real app are discovered, and a route without a declaration fails the build with `route has no isolation test declared: <METHOD> <path>` (a declaration for a route that no longer exists fails too). **No route leaks:** each authenticated route is called as a user of Organization A with the ids of Organization B and the other way round; nothing of the other Organization may come back, appear in headers or logs, or change in the database. **Jobs run in their own tenant context.** **Every Valkey key carries the Organization.** The suite proves that it bites: `test_suite_catches_leaks.py` mounts deliberately leaky probe routes and jobs (test-only, never part of `create_app()`) and requires each leak to be reported.

### Adding a route

Add one line to `ROUTE_CASES` in `backend/tests/integration/isolation/cases.py`, choosing the kind:

| Kind | Use it when | What the suite does |
|---|---|---|
| `ResourceRoute(method, path, resources, body=None, ok_status=200)` | a path parameter (or an id query parameter: typed `UUID`, or named `id`, `*_id`, `*Id` whatever its type) names a tenant resource; `resources` maps each one to a fixture table (`"workspaces"`, ...) | the other Organization uses the route first (so a cache or store without the Organization is filled), then calls it with the other Organization's ids: must answer 403 or 404, **the same status and body as for an unknown id**; then with its own ids: `ok_status` |
| `OwnTenantRoute(method, path, query_resources={}, body=None, ok_status=200)` | no resource id in the path (the Organization comes from the token only) | calls it with the other Organization's id in every `X-Org-Id`-style header and `org_id`-style query parameter: `ok_status`, the caller's own data, nothing of the other Organization |
| `PublicRoute(method, path, reason, resources={})` | no identity required (`/healthz`); `reason` is required; `resources` maps path and id query parameters to fixture tables, and each parameter must be called `<table singular>_id` (`workspace_id` for `workspaces`) so a wrong mapping cannot make the check vacuous | not an exemption: called once per Organization, claiming to be it (its id in every Organization header and query parameter, its ids in the path), and nothing of either Organization may come back; fails if the route actually needs an identity |

Every case also checks that the other Organization's rows **and Valkey keys** (`org:<other>:*`, values included) are unchanged afterwards and that none of its data landed in the caller's own rows (a route that copies across Organizations), that logs, headers and body hold nothing of it, that a call without credentials answers 401, and that an authenticated route depends on `require_tenant`. `body` builds the JSON body from the fixture rows (`OrgRows`); `ok_status` is the success status of the route (for example 201 for a create). The body builder runs for every request of the check (warm-up, cross call, positive control, anonymous call), so a create route with a unique constraint needs a body that differs per call, for example `body=lambda rows: {"name": f"ws-{uuid4()}"}`. The suite fails when a request model declares `id` (the database generates ids) or any field that names an Organization (`org_id`, `orgId`, `X-Tenant-Id`, ...). Answer an id of another Organization exactly like an unknown id (404 `{"detail": "not_found"}` is recommended) and never put ids in error bodies.

### Adding a table

A new table needs `org_id`, the standard policy and grants (see `docs/architecture/data-model.md`). Also add it to the fixtures: `create_org_rows`, `OrgRows` and `DELETE_ORDER` in `backend/tests/support/tenants.py`, so the cross-Organization tests, the snapshots and the cleanup include it.

### Adding a background job

Register the handler with `@JOBS.register("kind")` (`ei_ai.jobs`), queue it with `envelope_for(tenant, kind, payload)` (the Organization comes from the verified tenant context, never from the payload) and run it only through `run_tenant_job(engine, envelope)`, which opens the tenant transaction and gives the handler a session and no engine. Import the handler module in `backend/src/ei_ai/jobs/__init__.py` (`import ei_ai.<area>.jobs  # noqa: F401`): handlers register when their module is imported, and the worker and the suite both import `ei_ai.jobs`, so a handler module that nothing imports is invisible to both. Add a `JobCase(kind, payload)` to `JOB_CASES` in `cases.py`; without it `job has no isolation test declared: <kind>` fails the build. The suite runs the job for one Organization with a payload that names the other Organization's rows, then with its own rows.

### Caching

Get the client with `create_valkey_client(settings.valkey_url)` from `ei_ai.cache` (create it once, close it with `await client.aclose()`), then use `TenantCache(client, tenant)` (`ei_ai.cache`). Any new public name that `ei_ai.cache` exports must be added to `CACHE_PUBLIC_API` in `backend/tests/test_valkey_access.py`, otherwise the import scan rejects code that uses it. Valkey is reached only through `TenantCache`, built from the verified `TenantContext` of the route (or the `JobContext` of the job), never from an id; a test fails when any other code constructs those contexts: keys are `org:<org_id>:<namespace>:<part>...`, no method accepts a raw key and every key needs a TTL. A unit test fails when any module under `backend/src` outside `ei_ai/cache/` imports `redis` or `valkey`, takes a client name (`aioredis`, `Redis`) from another module, imports anything but the public API from `ei_ai.cache`, or imports a client with `importlib` / `__import__`. In the isolation suite every test is followed by a scan of the whole Valkey database that fails on any key outside the `org:<uuid>:` prefix and deletes it, so one raw key is one failure (`assert_only_tenant_keys` in `tests/support/isolation/valkey.py`; the keys of a run must be written through `TenantCache`). The import scan is an accident-catcher, not a barrier against someone determined to get around it (for example a client reached through a helper that builds the import at run time); the runtime scan and the check that the other Organization's keys do not change are the backstop.

### Reuse and limits

Later stories reuse the helpers: `assert_route_isolated`, `assert_public_route_clean` and `assert_job_isolated` in `backend/tests/support/isolation/` (WGT-03 widget identity spoofing, SKL-02 Tools). Side paths that do not exist yet (files, export, webhooks, D46) add their own case kind to this suite when they are built. Known limitation: primary keys are global, so a cross-Organization INSERT with a known id hits the unique index; ids are database-generated and unguessable, and the suite requires equal answers for foreign and unknown ids (see `docs/architecture/data-model.md`).

## CI

`.github/workflows/ci.yml` runs on every push to any branch (ticket branches and `main`) and manually, so a branch is checked without opening a pull request. A push to `main` skips the check jobs when it is a merge with the same tree as the merged branch head and that head already passed CI (a small `gate` job decides, `scripts/ci-gate.mjs`); any other push to `main` runs them. Five jobs run in parallel on `ubuntu-24.04`, each with a 10 minute limit (the suite step of `tenant-isolation` has 5); a newer push to the same branch cancels the older run. Every step calls the same task runner as `npm run check`.

| Job | Steps |
|---|---|
| `frontend` | `npm ci`, lint, type check, unit tests, build, API types in sync |
| `backend` | ruff, ruff format, mypy, pytest with coverage gate, OpenAPI in sync |
| `checks` | all Node checks (design, licence review, ADR, EVL-01, compose structure, README, CI file), actionlint, gitleaks over the full history |
| `tenant-isolation` | `npm run backend -- prepare` (pulls and builds the images), then `npm run backend -- test-isolation` (starts the database and Valkey, applies the migrations, runs the suite) with a 5 minute limit on that step, so a slower suite fails the check while a slow registry or image build cannot; the job itself is capped at 10 minutes; `npm run down`. Measured locally (Docker Desktop on Windows): about 13 seconds on a warm image including the stack start (3 seconds of that is `prepare`), about 45 seconds when the image is rebuilt; the GitHub duration is recorded after the first run |
| `stack` | Compose 2.20.3 (the minimum), `npm run up -- --no-model` (applies the migrations and runs the schema guard), smoke test, `npm run seed` twice, integration tests, `npm run down` |

Any failing step fails the job and the commit status (also shown on a pull request for that commit). **Owner step:** in the GitHub repository settings (Branch protection or a ruleset for `main`), require the five checks `frontend`, `backend`, `checks`, `stack` and `tenant-isolation` before merging (a check name appears in GitHub's picker only after its first run); this cannot be set from the repository.

The model is not started in CI (download and RAM); it is verified locally with `npm run up`.

## Memory budget

Hard limits in `compose.yaml` (the model server is the large one) and what Docker reported with `docker stats` after the seed on the 16 GB development machine:

| Service | Limit | Measured |
|---|---|---|
| `model` | 6g | 3.4-4.7 GiB (varies with the page cache) |
| `db` | 1g | 68 MiB |
| `valkey` | 256m | 18 MiB |
| `api` | 512m | 52 MiB |
| `admin` | 64m | 11 MiB |
| `widget` | 64m | 12 MiB |
| `migrate` | 256m | one-shot, exits after migrating (not started by `up`) |

The limits add up to about 7.9 GB, more than the 6.7-7.2 GB that Docker Desktop gives WSL2 by default; the measured use is lower (see Prerequisites for `.wslconfig`).

## Troubleshooting

- **Git Bash rewrites container paths** (`-w /repo` becomes `C:/Program Files/Git/repo`): prefix manual commands with `MSYS_NO_PATHCONV=1`. The npm commands are not affected (they start Docker without a shell).
- **Line endings:** `.gitattributes` forces LF. If shell scripts fail in containers with `\r` errors, run `git add --renormalize .` and re-checkout the files.
- **Port already in use** (3000, 3001, 8000): stop the other program, or stop another copy of the stack (`npm run down`). For the admin UI you can instead move it with `ADMIN_PORT=<free port>` in `.env`; the other ports are fixed on purpose.
- **The migrate step fails with `password authentication failed for user "ei_ai_migrator"` (or the role does not exist):** the database volume was created before FND-01, so it has no migration role. Run `npm run reset` once (it deletes only the local database; nothing is lost yet) and then `npm run up`.
- **Password errors after deleting `.env`:** the database volume keeps the passwords of its first start. Either restore the old `.env` or run `npm run reset` (this deletes the local database).
- **The model exits with `model file sha256 mismatch: expected …, got …`:** the cached file is not the pinned one (a changed `LLM_MODEL_URL`/`LLM_MODEL_FILE`, a corrupted download, or a wrong `LLM_MODEL_SHA256` in `.env`). The file is kept for inspection. Fix the setting, or remove the cached file so the next start downloads it again: `docker run --rm -v <model volume>:/models alpine rm /models/<file>` (the volume is `MODEL_CACHE_VOLUME`, default `ei-ai-model-cache`). Hashing the 2.5 GB file adds a few seconds to every model start.
- **The model never becomes healthy:** its check passes only when `/v1/models` lists the configured model alias with the `@sha256-<12 hex>` suffix the start script adds. Look at `npm run logs -- model`: a first start downloads about 2.5 GB, a download error or too little memory (see `.wslconfig`) shows there. `npm run up -- --no-model` skips it.
- **Slow first model download:** below about 3.8 MB/s the 2.5 GB download needs more than the 10 minute start period, so `npm run up` can stop waiting after about 11 minutes (and report a failure) while the download goes on in the background. Check progress with `npm run logs -- model`; when the download has finished and the model has loaded, run `npm run up` again.
- **Docker is not available:** start Docker Desktop (or the Docker service) and run the command again.
- **Compose too old:** update Docker Desktop (or the Docker Compose plugin on Linux). `node scripts/install-compose.mjs` is for CI and for trying the minimum version: pass `--dest <folder>` and point `DOCKER_CONFIG` there, because without `--dest` it installs into `~/.docker/cli-plugins`, which overrides the Compose that comes with Docker Desktop.

## Conventions

- Branch per ticket: `feature/EA-<n>-<slug>`; commits `[EA-<n>] type(scope): summary`; no AI attribution lines in commit messages.
- Tenant isolation, identity from the verified token, masked logs, no secrets in the repository, a test for every acceptance criterion, i18n for every user-facing string: `CLAUDE.md` and `docs/dev/coding-rules.md`.
- Pin exact versions. Python pins and container images are enforced by the licence check (`docs/architecture/oss-license-review.md`: a pin or image without a row fails it). npm packages are not checked yet: they are covered by SET-06 (EA-86), so add a row by hand when you add an npm dependency.
