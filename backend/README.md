# Backend

Python 3.12, FastAPI, Pydantic v2. Package `ei_ai` in `src/ei_ai` (src layout).

| Path | Purpose |
|---|---|
| `src/ei_ai/main.py` | `create_app()` factory and the `app` served by uvicorn |
| `src/ei_ai/api/health.py` | `GET /healthz` (liveness, no dependency calls) and `GET /readyz` (database and Valkey) |
| `src/ei_ai/settings.py` | Settings from environment variables; errors name the variable, never the value |
| `src/ei_ai/readiness.py` | Dependency checks; failures report component names only |
| `src/ei_ai/api/organization.py` | `GET /organization`: the Organization of the verified identity (tenant route example) |
| `src/ei_ai/auth/` | `Principal`, the `IdentityVerifier` interface and the `current_principal` dependency (401 without a verified identity) |
| `src/ei_ai/tenancy/` | `require_tenant`: the tenant of a request comes only from the Principal; forged `org_id` fields are ignored and logged |
| `src/ei_ai/jobs/` | Background jobs in their own tenant context: `envelope_for`, the `JOBS` registry, `run_tenant_job` (FND-02); no queue yet, KB-02 adds it |
| `src/ei_ai/cache/` | `TenantCache`: the only way to use Valkey; keys always start with `org:<org_id>:`; the readiness ping (`ping.py`) lives here too (FND-02) |
| `src/ei_ai/db/` | Engine, `tenant_transaction` / `tenant_session`, models, Alembic migrations (`db/migrations/`), catalog snapshot and schema guard; see `docs/architecture/data-model.md` |
| `src/ei_ai/cli.py` | `ei-ai seed demo`, `ei-ai db upgrade` (migrations + schema guard), `ei-ai db current` (exit 0 done, 1 failed, 2 refused) |
| `src/ei_ai/seed/` | Versioned Mekong Devworks demo manifest; FND-04 (EA-21) loads it into the database |
| `src/ei_ai/openapi_export.py` | Writes the OpenAPI document that `packages/api-types` is generated from |
| `tests/` | Unit tests (`tests/integration/` needs the Compose stack) |
| `tests/support/isolation/` | Machinery of the tenant-isolation suite: case kinds, route discovery, request-field check, cross-tenant assertions, job and Valkey checks (test-only) |
| `tests/integration/isolation/` | The tenant-isolation suite: `cases.py` declares every route and job; leaky probes prove the suite catches leaks |

Run everything through the repo root so the same commands run locally and in CI:

```
npm run backend -- lint          # ruff check
npm run backend -- format        # ruff format --check
npm run backend -- typecheck     # mypy (strict)
npm run backend -- test          # unit tests, coverage >= 70 %
npm run backend -- test-integration   # starts db + valkey, applies the migrations, then pytest -m "integration and not isolation"
npm run backend -- test-isolation     # the tenant-isolation suite (FND-02), CI job tenant-isolation; see README, "Writing isolation tests"
npm run backend -- bench-rls     # RLS overhead benchmark (FND-01); not part of npm run check
npm run migrate                  # applies the migrations and runs the schema guard
npm run backend -- openapi       # committed OpenAPI matches the app
```

Without Docker (CI, or a local Python 3.12): add `--native` after the task, after `pip install -e "backend[dev]"`.
Database access, migrations and the tenant helper are described in `docs/architecture/data-model.md`;
the rules are in `docs/dev/coding-rules.md` section 2. Tests under `tests/integration/` need the Compose
services and `MIGRATION_DATABASE_URL`; `tests/support/` holds test-only helpers (never imported by `src`).
