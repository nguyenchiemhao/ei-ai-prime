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

> Decided in ADR-001 (`docs/architecture/adr-001-tech-stack.md`). The ADR stays "Proposed" until the owner approves it; these rules apply from approval. Follow the conventions of any code already in the repo.

### Backend
- Language/version, formatter, linter, type checker: Python 3.12, FastAPI (Pydantic v2); ruff for lint and format; mypy in strict mode for new modules.
- Test runner and layout: pytest (+ pytest-asyncio), tests under `tests/` mirroring the package layout; database tests run against a real PostgreSQL 16 + pgvector from Docker Compose, never a mock of the database.
- DB access and migrations (RLS policy per table): SQLAlchemy 2 (async, psycopg 3) and Alembic. Every table has `org_id`, and its RLS policy (`ENABLE` + `FORCE ROW LEVEL SECURITY`) is created in the same migration as the table. The application role is never a table owner, superuser or BYPASSRLS role. Tenant context is set at the start of a top-level transaction with `set_config('app.current_org', <org id from the verified token>, true)`; the helper must refuse to run when a transaction is already open (a nested call only creates a SAVEPOINT and the setting would outlive it), and policies read it through `NULLIF(current_setting('app.current_org', true), '')::uuid` (the setting reads `''` after a transaction ends). Origin of the pattern, with tests: `poc/stack-spike/src/stack_spike/tenant.py` (to be replaced by the real helper in FND-01). Use composite foreign keys `(org_id, id)`; no grants on vector partitions; views use `security_invoker = true`.
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

Fill in once the stack exists; agents run exactly these. Filled by SET-03 (EA-13) when the skeleton exists; the EA-11 PoC commands are in `poc/stack-spike/README.md`.

| Purpose | Command |
|---|---|
| Install | |
| Lint + format check | |
| Type check | |
| Unit/integration tests | |
| Start app locally | |
| E2E tests | `npx playwright test` |
