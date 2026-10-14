# Coding rules

Used by the Developer and Code Reviewer agents and by humans. The short, non-negotiable list lives in `CLAUDE.md`; this file adds detail.

## 1. General (any stack)

### Structure
- One responsibility per module. A file that grows past ~300 lines is a signal to split.
- Follow the existing pattern in the area you touch before introducing a new one. New patterns need a one-line reason in the dev log.
- No dead code, commented-out code or speculative abstractions (YAGNI).

### Naming
- Use the product terms from the docs exactly: Organization, Workspace, Channel, Assistant, Collection, Answer Script, Skill, Connector, Tool, Draft/Published.
- Names say what, not how (`find_published_scripts`, not `query_helper2`).

### Errors
- Fail loudly on programmer errors; return typed, user-safe errors at API boundaries.
- Never swallow exceptions silently. Every `catch`/`except` either handles, re-raises with context, or logs (masked) and returns a defined error.
- User-facing error messages are translatable and never leak internals (stack traces, SQL, tenant ids).

### Security and privacy
- Tenant isolation (D46), identity from token only (D32), masked logs (D52) — see `CLAUDE.md`.
- Validate all external input at the boundary (HTTP, widget postMessage, Connector responses, model output used as data).
- Treat model output and retrieved documents as untrusted (prompt-injection blast radius, D51).
- Outbound HTTP from Tools/Connectors: HTTPS only, timeouts set, response size limited.

### Tests
- Every Acceptance Criterion maps to at least one test; the plan's AC → test table is the contract.
- Write the failing test first (TDD) for logic; E2E specs for UI behaviour live under `e2e/`.
- Tests are deterministic: no real network, no real clock, no shared state between tests. LLM calls are stubbed except in eval suites.
- Name tests after behaviour: `rejects_request_without_org_claim`, `shows_streamed_answer_in_widget`.

### Git
- Branches and commit messages follow the `git-commit` skill. One concern per commit.

## 2. Stack-specific

> Decided in ADR-001 (`docs/architecture/adr-001-tech-stack.md`), accepted by the owner on 2026-10-14; these rules apply now. Follow the conventions of any code already in the repo.

### Backend
- Language/version, formatter, linter, type checker: Python 3.12, FastAPI (Pydantic v2); ruff for lint and format; mypy in strict mode for new modules.
- Test runner and layout: pytest (+ pytest-asyncio), tests under `tests/` mirroring the package layout; database tests run against a real PostgreSQL 16 + pgvector from Docker Compose, never a mock of the database.
- DB access and migrations (RLS policy per table): SQLAlchemy 2 (async, psycopg 3) and Alembic. Every table has `org_id`, and its RLS policy (`ENABLE` + `FORCE ROW LEVEL SECURITY`) is created in the same migration as the table. The application role is never a table owner, superuser or BYPASSRLS role. Tenant context is set at the start of a top-level transaction with `set_config('app.current_org', <org id from the verified token>, true)`; the helper must refuse to run when a transaction is already open (a nested call only creates a SAVEPOINT and the setting would outlive it), and policies read it through `NULLIF(current_setting('app.current_org', true), '')::uuid` (the setting reads `''` after a transaction ends). The real implementation (FND-01): `ei_ai.db.tenant` (`tenant_transaction`, `tenant_session`), `ei_ai.db.migrations.rls` (`enable_tenant_rls`, `grant_dml`: use them in every migration), `ei_ai.tenancy.context` (`require_tenant`), the schema guard `ei_ai.db.schema_guard` (runs after every migration and fails on a table without `org_id` or a correct policy), and the full description in `docs/architecture/data-model.md`. Use composite foreign keys `(org_id, id)`; no grants on vector partitions; views use `security_invoker = true`; no `SECURITY DEFINER` functions; the application role never gets TRUNCATE.
- Tenant routes depend on `require_tenant` and get their database session only through `TenantSession` (`ei_ai.api.deps`: function-scoped, so the transaction commits before the response is sent); the Organization comes only from the verified `Principal`. Every table, `users` included, belongs to one Organization (`org_id`); never alter row-level security in code or in test cleanup (a test fails on `NO FORCE`/`DISABLE ROW LEVEL SECURITY` under `backend/src`). Request models never declare `org_id`, and a client-sent `org_id` (header, query, body) is never used.
- Migrations run only as `ei_ai_migrator` (`npm run migrate`, `ei-ai db upgrade`); the application role `ei_ai_app` is never an owner. A new table is also added to the cross-org fixtures in `backend/tests/integration/db/`.
- Models: call them only through the OpenAI-compatible gateway (official `openai` SDK with `base_url`); never import an engine-specific client.

### Frontend (admin + widget)
- Framework, formatter, linter: React (admin) and Preact (widget), both TypeScript in strict mode, built with Vite; ESLint and Prettier.
- i18n library: `react-i18next` in the admin; a small dictionary-based `t()` in the widget; both read the shared VI/EN message JSON. No hard-coded user-facing strings.
- Component test runner: Vitest with Testing Library.
- Styling: only the shared design-token CSS variables (DSN-01); IBM Plex through the self-hosted `@fontsource` packages (Vietnamese subset included).

### E2E
- Playwright Test (`@playwright/test`), specs in `e2e/<area>/<ticket-key>-<slug>.spec.ts`.
- Selectors: `getByRole` / `getByLabel` / `getByTestId` — no CSS/XPath tied to layout.
- One spec file per ticket; one `test()` per Acceptance Criterion, titled `AC<n>: <criterion>`.

## 3. Commands

Agents run exactly these, from the repository root (details and prerequisites: `README.md`). "make up" in older tickets means `npm run up`.

| Purpose | Command |
|---|---|
| Install | `npm ci` (Node dependencies; the Docker images are built by `npm run up` and the backend tools image by `npm run backend -- <task>`) |
| Lint + format check | `npm run lint` (frontend) and `npm run backend -- lint` + `npm run backend -- format` (backend) |
| Type check | `npm run typecheck` (frontend) and `npm run backend -- typecheck` (backend) |
| Unit/integration tests | `npm test` (frontend + Node checks + backend unit tests); `npm run backend -- test-integration` (needs db and valkey, started by the command) |
| Start app locally | `npm run up` (add `-- --no-model` to skip the model; it applies the database migrations first); `npm run seed` for the demo data; `npm run down` to stop |
| Database migrations | `npm run migrate` (starts the database if needed, applies the migrations and runs the schema guard; safe to repeat) |
| RLS overhead benchmark | `npm run backend -- bench-rls` (FND-01 NFR; not part of `npm run check`) |
| E2E tests | `npm run e2e` (one-time browser install: `npx playwright install chromium`; the stack must be running) |
| All CI checks | `npm run check` (`-- --skip-stack` without Docker services) |
