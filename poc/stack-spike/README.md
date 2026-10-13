# Stack spike PoC (EA-11 / SET-01)

Throwaway proof for [ADR-001](../../docs/architecture/adr-001-tech-stack.md). It shows two things:

1. **Two-layer tenant isolation (D46, F1, F2).** PostgreSQL row-level security on regular tables, plus one pgvector partition with its own HNSW index per Organization. With the tenant context set to Organization A, queries return 0 rows of Organization B, for tables and for vectors.
2. **The infrastructure of the chosen stack starts with one command on the dev machine** (Ryzen 5 5600G, 16 GB RAM, no GPU): PostgreSQL 16 + pgvector, Valkey, and an opt-in ~4B model on CPU behind an OpenAI-compatible API.

SET-03 (EA-13) and FND-01 (EA-18) absorb the RLS pattern into the real backend migrations and then delete or archive this folder. Do not build on it.

## Prerequisites

- Docker Desktop running (Compose v2.17 or newer works; the file only uses older features).
- No Python on the host is needed: everything runs in containers.
- Run every command from the repository root. `$POC` below means:

```bash
POC="docker compose -f poc/stack-spike/compose.yaml run --rm poc"
```

## Commands

| Purpose | Command |
|---|---|
| Validate the compose file | `docker compose -f poc/stack-spike/compose.yaml config` |
| Build the tools image | `docker compose -f poc/stack-spike/compose.yaml build poc` |
| Lint | `$POC ruff check .` |
| Format check | `$POC ruff format --check .` |
| All tests (isolation + ADR structure + core services; model tests skipped) | `$POC pytest -v` |
| Isolation tests only (AC3) | `$POC pytest tests/isolation -v` |
| ADR structure tests only (AC1, AC2, AC5, AC6) | `$POC pytest tests/docs -v` |
| Start db + valkey | `docker compose -f poc/stack-spike/compose.yaml up -d` |
| **One command: db + valkey + model** | `docker compose -f poc/stack-spike/compose.yaml --profile model up -d` |
| Wait for the model (first run downloads ~2.5 GB) | `docker compose -f poc/stack-spike/compose.yaml ps` until `model` is `healthy` |
| Model tests + TTFT / tokens per second (`-s` shows the metrics) | `docker compose -f poc/stack-spike/compose.yaml run --rm -e CHECK_MODEL=1 poc pytest tests/stack -v -s` |
| Memory per container | `docker stats --no-stream` |
| Stop (keeps the downloaded model) | `docker compose -f poc/stack-spike/compose.yaml --profile model down` |
| Stop and delete the model cache | `docker compose -f poc/stack-spike/compose.yaml --profile model down -v` |

The database keeps its data in `tmpfs`, so every `down` followed by `up` starts from a clean schema (`db/init/001_schema.sql`). Test fixtures create fresh Organizations with random ids, so re-running the tests on a live database also works.

## Model

Default: `unsloth/Qwen3-4B-Instruct-2507-GGUF`, file `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` (Apache-2.0, non-thinking), downloaded by Hugging Face commit so the file cannot change. The model test hashes the cached file and compares it with `MODEL_SHA256`. To try another model, set `LLM_MODEL_URL` (a `resolve/<commit>/<file>` URL), `LLM_MODEL_SHA256` and `LLM_ALIAS`, and run `down -v` first so the cache holds a single GGUF. The server image tag, the model file and its sha256 are recorded in ADR-001 section 8.

## RAM notes

Docker Desktop with WSL2 gives its VM about 50% of the host RAM (about 8 GB here) by default. The services in this PoC have hard limits (db 1 GB, valkey 256 MB, model 6 GB) and fit in that cap. For the full application stack (SET-03), create `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=10GB
```

then run `wsl --shutdown` and restart Docker Desktop. Quality and latency are never judged on this machine (D4, R8); the model run only proves that it starts and streams.

## PoC-only shortcuts (do not copy to the product)

- PostgreSQL uses `trust` authentication on the compose-internal network and publishes no ports, so no password exists anywhere. SET-03 uses credentials from environment variables.
- The superuser `postgres` is the provisioning role (`provision_org`); the product uses a dedicated migration role and the FND-04 CLI.
- Vectors have 8 dimensions (the ADR records 1024 for bge-m3).
- Valkey and the model server have no authentication and no published ports.
