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

> Filled when SET-01 (EA-11) records the stack decision in an ADR. Proposed stack: Python/FastAPI + PostgreSQL (RLS) + pgvector + React/Preact. Until then, the Developer follows the general rules and the conventions of any code already in the repo.

### Backend
- Language/version, formatter, linter, type checker:
- Test runner and layout:
- DB access and migrations (RLS policy per table):

### Frontend (admin + widget)
- Framework, formatter, linter:
- i18n library:
- Component test runner:

### E2E
- Playwright Test (`@playwright/test`), specs in `e2e/<area>/<ticket-key>-<slug>.spec.ts`.
- Selectors: `getByRole` / `getByLabel` / `getByTestId` — no CSS/XPath tied to layout.
- One spec file per ticket; one `test()` per Acceptance Criterion, titled `AC<n>: <criterion>`.

## 3. Commands

Fill in once the stack exists; agents run exactly these.

| Purpose | Command |
|---|---|
| Install | |
| Lint + format check | |
| Type check | |
| Unit/integration tests | |
| Start app locally | |
| E2E tests | `npx playwright test` |
