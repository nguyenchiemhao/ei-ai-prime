# Backend

Python 3.12, FastAPI, Pydantic v2. Package `ei_ai` in `src/ei_ai` (src layout).

| Path | Purpose |
|---|---|
| `src/ei_ai/main.py` | `create_app()` factory and the `app` served by uvicorn |
| `src/ei_ai/api/health.py` | `GET /healthz` (liveness, no dependency calls) and `GET /readyz` (database and Valkey) |
| `src/ei_ai/settings.py` | Settings from environment variables; errors name the variable, never the value |
| `src/ei_ai/readiness.py` | Dependency checks; failures report component names only |
| `src/ei_ai/cli.py` | `ei-ai seed demo` (exit 0 done, 1 failed, 2 refused) |
| `src/ei_ai/seed/` | Versioned Mekong Devworks demo manifest; FND-04 (EA-21) loads it into the database |
| `src/ei_ai/openapi_export.py` | Writes the OpenAPI document that `packages/api-types` is generated from |
| `tests/` | Unit tests (`tests/integration/` needs the Compose stack) |

Run everything through the repo root so the same commands run locally and in CI:

```
npm run backend -- lint          # ruff check
npm run backend -- format        # ruff format --check
npm run backend -- typecheck     # mypy (strict)
npm run backend -- test          # unit tests, coverage >= 70 %
npm run backend -- test-integration   # starts db + valkey, then pytest -m integration
npm run backend -- openapi       # committed OpenAPI matches the app
```

Without Docker (CI, or a local Python 3.12): add `--native` after the task, after `pip install -e "backend[dev]"`.
Database access, migrations and the tenant helper arrive with FND-01; the RLS pattern to adopt is
described in `docs/dev/coding-rules.md` section 2.
