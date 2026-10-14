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

On the first run `npm run up` creates `.env` with generated passwords (git-ignored; keep it, the database volume uses these passwords), builds the images, starts every service and waits until all are healthy. It prints the elapsed time and the URLs:

| What | URL |
|---|---|
| Admin UI | http://localhost:3000 |
| Widget | http://localhost:3001 |
| API health | http://localhost:8000/healthz (readiness: `/readyz`) |

All ports are fixed and bound to `127.0.0.1` only. The database, Valkey and the model server have no published port.

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

Runs `ei-ai seed demo` inside the API container. It refuses to run unless the environment is `local` or `test` (exit code 2), validates the versioned Mekong Devworks manifest (Organization "Mekong Devworks", Workspace "People Ops", six members), checks that the application database role can connect, and prints the same summary on every run. It writes no rows yet: the tables arrive with FND-01 and ticket FND-04 (EA-21) loads this manifest into the database and keeps the same command.

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
| `npm run backend -- test-integration` | Starts the database and Valkey, then runs the integration tests against them |
| `node scripts/run-node-checks.mjs` | Document and repository checks (design tokens, licence review, ADR, EVL-01 data set, packages, scripts); fails when a pattern matches no file or a check runs 0 tests |
| `npm test` | Frontend tests, Node checks and backend unit tests |
| `npm run check` | **Everything CI runs**, in four jobs (frontend, backend, checks, stack), with PASS/FAIL and the duration of each step. `-- --skip-stack` skips the Docker stack job; the stack job starts the stack without the model and stops it at the end. |

Add `--native` after a backend task (`npm run backend -- lint --native`; not for `test-integration`, which needs the Compose services) to run it on the host with Python 3.12 (`pip install -e "backend[dev]"`), as CI does.

Playwright end-to-end tests live in `e2e/` (specs `e2e/<area>/<ticket>-<slug>.spec.ts`; configuration in `playwright.config.ts`). They run against an already running stack:

```
npx playwright install chromium     # once per machine: downloads the test browser
npm run up && npm run seed          # the stack the specs talk to
npm run e2e                         # all specs; or: npm run e2e -- e2e/<area>/<ticket>-<slug>.spec.ts
```

`ADMIN_URL` (default `http://localhost:3000`) is the base URL; the HTML report goes to `.work/playwright-report/` and traces of failed tests to `.work/playwright-results/` (git-ignored). `npm run lint` and `npm run typecheck` cover the specs and the config too.

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
| `infra/` | Infrastructure files mounted into containers (database init script) |
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

## CI

`.github/workflows/ci.yml` runs on every pull request, on pushes to `main` and manually. Four jobs run in parallel on `ubuntu-24.04`, each with a 10 minute limit; a newer push to the same branch cancels the older run. Every step calls the same task runner as `npm run check`.

| Job | Steps |
|---|---|
| `frontend` | `npm ci`, lint, type check, unit tests, build, API types in sync |
| `backend` | ruff, ruff format, mypy, pytest with coverage gate, OpenAPI in sync |
| `checks` | all Node checks (design, licence review, ADR, EVL-01, compose structure, README, CI file), actionlint, gitleaks over the full history |
| `stack` | Compose 2.20.3 (the minimum), `npm run up -- --no-model`, smoke test, `npm run seed` twice, integration tests, `npm run down` |

Any failing step fails the job and the pull request. **Owner step:** in the GitHub repository settings (Branch protection or a ruleset for `main`), require the four checks `frontend`, `backend`, `checks` and `stack` before merging; this cannot be set from the repository.

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

The limits add up to about 7.9 GB, more than the 6.7-7.2 GB that Docker Desktop gives WSL2 by default; the measured use is lower (see Prerequisites for `.wslconfig`).

## Troubleshooting

- **Git Bash rewrites container paths** (`-w /repo` becomes `C:/Program Files/Git/repo`): prefix manual commands with `MSYS_NO_PATHCONV=1`. The npm commands are not affected (they start Docker without a shell).
- **Line endings:** `.gitattributes` forces LF. If shell scripts fail in containers with `\r` errors, run `git add --renormalize .` and re-checkout the files.
- **Port already in use** (3000, 3001, 8000): stop the other program, or stop another copy of the stack (`npm run down`). The ports are fixed on purpose.
- **Password errors after deleting `.env`:** the database volume keeps the passwords of its first start. Either restore the old `.env` or run `npm run reset` (this deletes the local database).
- **The model never becomes healthy:** its check passes only when `/v1/models` lists the configured model alias. Look at `npm run logs -- model`: a first start downloads about 2.5 GB, a download error or too little memory (see `.wslconfig`) shows there. `npm run up -- --no-model` skips it.
- **Slow first model download:** below about 3.8 MB/s the 2.5 GB download needs more than the 10 minute start period, so `npm run up` can stop waiting after about 11 minutes (and report a failure) while the download goes on in the background. Check progress with `npm run logs -- model`; when the download has finished and the model has loaded, run `npm run up` again.
- **Docker is not available:** start Docker Desktop (or the Docker service) and run the command again.
- **Compose too old:** update Docker Desktop (or the Docker Compose plugin on Linux). `node scripts/install-compose.mjs` is for CI and for trying the minimum version: pass `--dest <folder>` and point `DOCKER_CONFIG` there, because without `--dest` it installs into `~/.docker/cli-plugins`, which overrides the Compose that comes with Docker Desktop.

## Conventions

- Branch per ticket: `feature/EA-<n>-<slug>`; commits `[EA-<n>] type(scope): summary`; no AI attribution lines in commit messages.
- Tenant isolation, identity from the verified token, masked logs, no secrets in the repository, a test for every acceptance criterion, i18n for every user-facing string: `CLAUDE.md` and `docs/dev/coding-rules.md`.
- Pin exact versions. Python pins and container images are enforced by the licence check (`docs/architecture/oss-license-review.md`: a pin or image without a row fails it). npm packages are not checked yet: they are covered by SET-06 (EA-86), so add a row by hand when you add an npm dependency.
