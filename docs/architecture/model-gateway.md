# Model Gateway and model catalog

Status: built in FND-07 (EA-24), 2026-10-20. Implements D4 (OpenAI-compatible API), D17 (cloud models only BYOK, off by default), D18 (pinned versions, one retry, never a local→cloud fallback), D33 (egress through a proxy), D46 (tenant isolation), D52 (masked logs) and F8/F10/F11 of ADR-001.

Every AI feature (RAG, classifier, matcher, evaluation) calls models only through `ei_ai.model_gateway.ModelGateway` (`gateway.py`), never through an engine-specific client (coding rules, Backend). Changing a model is configuration: a catalog row and, for a local model, the model server's environment.

## Pieces

| Module | Responsibility |
|---|---|
| `refs.py` | `ModelRef` `<model_id>@<version>`, with the same patterns as the catalog CHECKs |
| `catalog.py` | `DbCatalog.resolve`: the requested ref, in the caller's Organization, in one short tenant transaction; `record_cloud_block` (audit) |
| `manifest.py`, `data/local-models.json` | The platform's local models (code-reviewed, no tenant data), copied into an Organization's catalog |
| `providers.py` | Provider key → base URL. A catalog row never holds a URL (SSRF, P35) |
| `transport.py` | The only module that imports `openai` and its HTTP client `httpx2` (the egress seam) |
| `pinning.py` | The served id of a row and the pin checks |
| `retry.py` | The retry rule |
| `observer.py` | `ModelCallRecord`, the observer hook, the metadata-only log line |
| `gateway.py` | `stream_chat`, `chat`, `embed`, `rerank` |
| `factory.py` | `build_gateway(settings, engine, credentials, observers)` |
| `commands.py`, `try_command.py`, `cli_common.py` | `ei-ai model add` and `ei-ai model try` |

Callers pass a `ModelCallContext(org_id, actor, assistant_id=None, channel_id=None)`. `org_id` comes only from the verified identity (`ModelCallContext.from_tenant(TenantContext)`) or the Platform Operator's `--org` (D32). FND-12/ADM-02 store the pinned ref on the Assistant version and pass it in; until then the ref is a call argument.

## Call flow and error codes

Each step that fails raises `ModelError(code)` and nothing after it runs. Messages are fixed text plus the ref; no exception carries an SDK error, a URL, a key or an upstream body (transport failures are raised outside the `except` block, so `__cause__` and `__context__` are empty too).

1. **Resolve** the requested ref once, in the caller's Organization (the explicit `org_id` filter and RLS), for the requested kind (`chat`, `embedding`, `rerank`).
   - `MODEL_NOT_FOUND`: `no <kind> model <ref> in this Organization's catalog` (also a ref of another Organization, or of another kind).
   - `MODEL_RETIRED`: `model <ref> is retired` (status `retired`, or a `retirement_date` today or earlier, UTC).
2. **Cloud switch**: a cloud row while `organizations.allow_cloud_models` is false writes the audit event `model.cloud_call_blocked` (actor = caller, target = the catalog row) in its own committed transaction, then `CLOUD_DISABLED`: `cloud models are off for this Organization`. No network access.
3. **Provider**: an unknown provider key, or a provider whose deployment differs from the row's, gives `MODEL_UNAVAILABLE`. A local provider without a base URL gives `MODEL_UNAVAILABLE`; a cloud provider without `EGRESS_PROXY_URL` or without the Organization's key gives `CLOUD_NOT_CONFIGURED`: `cloud model calls are not configured`. No network access.
4. **Attempts** (at most two, see Retry): a local server must list the pinned served id in `GET /v1/models`, then the request is sent with exactly that id; a cloud answer (or every chunk of a cloud stream) must name the pinned snapshot id. Otherwise `PINNED_VERSION_UNAVAILABLE`: `pinned version unavailable: <ref>`, never retried and with no text yielded. A failed attempt that may not be retried gives `MODEL_UNAVAILABLE`: `model <ref> is unavailable`.
5. **Record**: exactly one `ModelCallRecord` goes to the observers, on success and on every failure.

There is no code path that picks another catalog row.

## Pinning

- **Catalog**: a row pins `kind`, `model_id`, `version`, `digest` (`sha256:<64 hex>` of the GGUF file, required for local rows), `source_revision` (`<repo>@<40-hex commit>/<file>`), `deployment` and `provider`. The trigger `model_catalog_pin_immutable` rejects an UPDATE of any of them for every role (`model_catalog pin columns are immutable`); a new file is always a new row with a new `version` (a `YYYY.MM` label, for example `2026.10`).
- **Model server**: `infra/model/start-model.sh` downloads the file by Hugging Face commit when it is missing, refuses to start when `sha256sum` differs from `LLM_MODEL_SHA256` (`model file sha256 mismatch: expected …, got …`, exit 1, the file is kept), and serves the model as `<LLM_ALIAS>@sha256-<first 12 hex of the file's actual sha256>`. The healthcheck waits for that id in `/v1/models`. Hashing the 2.5 GB file adds about 4 s per start on the dev machine.
- **Gateway**: the served id of a local row is `<model_id>@sha256-<first 12 hex of the row's digest>`. A server running another build of the same model lists another id, so the call fails with `PINNED_VERSION_UNAVAILABLE` before any completion request. llama.cpp echoes whatever model name is requested, so its answers are not proof; the listing is. Cloud rows are served under their `model_id` (a dated snapshot such as `gpt-4.1-2025-04-14`), and the answer's `model` must equal it.
- There is no result cache: the check runs on every call, so no TTL race and no cross-tenant cache question.

## Retry and timeouts

One retry, only after a 5xx, a timeout or a connection error, and in a stream only before the first text delta was yielded (a retry after text would duplicate it). 4xx, 429 included, is never retried ("busy → report at once", D57). A `GET /v1/models` failure counts as the attempt. The SDK's own retries are off (`max_retries=0`). Settings: `MODEL_CONNECT_TIMEOUT_SECONDS` (default 5), `MODEL_READ_TIMEOUT_SECONDS` (60), `MODEL_RETRY_DELAY_SECONDS` (0.25), `MODEL_MAX_TOKENS` (512, the default `max_tokens`). The context budget (D57) is the orchestrator's job (PIPE-07); the catalog stores `context_window`.

## No fallback

The gateway resolves only the requested ref. When the local model fails, the answer is `MODEL_UNAVAILABLE` for that ref, even if the Organization allows cloud models, has a cloud row, a key and a proxy (`tests/model_gateway/test_no_cloud_fallback.py`). A local row whose provider key names a cloud provider is refused as well.

## Cloud switch, keys and audit

`organizations.allow_cloud_models` (default false, D17) is read in the caller's tenant transaction; it is never a call parameter (the public methods take no `cloud`/`allow`/`fallback` argument, tested). Keys come from a `CloudCredentials` store (`api_key(org_id, provider)`); until ADM-04 builds BYOK storage the default store returns none, so every cloud call fails closed with `CLOUD_NOT_CONFIGURED`. ADM-04 builds the switch UI; tests set it as `postgres`.

## Egress (D33, FND-10)

- Cloud calls always use the explicit forward proxy `EGRESS_PROXY_URL`; with no proxy they are refused before any network access, and a proxy that is down is a connection error (then `MODEL_UNAVAILABLE`), never a direct connection.
- Every HTTP client is built with `trust_env=False`: `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and `NO_PROXY` can neither bypass nor redirect anything.
- Local model servers are platform-internal services on the private network, not outbound calls, so they do not use the proxy (assumption, the owner may overrule).
- One `httpx2.AsyncClient` per provider, shared by every Organization: a connection pool that keeps no credentials and no per-call state. Its cookie jar refuses every cookie (`DefaultCookiePolicy(allowed_domains=[])`), so a `Set-Cookie` on one Organization's answer (for example a CDN cookie such as `_cfuvid`) is never sent on a later call of any Organization (tested for the cloud and the local pool). A per-call `AsyncOpenAI` carries the calling Organization's key (tested: a key is only ever sent on its own Organization's call); local servers take no key, so their client is reused.
- Cloud base URLs are fixed in `providers.py` and must be https in production.
- `tests/model_gateway/test_transport_imports.py` fails when a module under `src` other than `transport.py` imports `openai`, `httpx`, `httpx2`, `httpcore`, `requests` or `aiohttp`. FND-10 replaces this seam with its `egress` module (allowlist, IP rules, size limits) and its lint rule then covers `transport.py`.
- The SDK fills `OpenAI-Organization`/`OpenAI-Project` from `OPENAI_ORG_ID`/`OPENAI_PROJECT_ID` when no value is passed; the transport drops both headers, so the platform's environment never reaches an Organization's call (tested). Still do not set `OPENAI_*` variables in the platform: the SDK also reads `OPENAI_CUSTOM_HEADERS`. The SDK's `X-Stainless-*` platform headers (OS, architecture, runtime version) are sent on every call; FND-10 decides whether the egress module strips them.

## Observer hook (FND-09) and logs (FND-08)

`ModelCallRecord` holds the Organization, actor, Assistant, Channel, kind, `model_ref` (`model_id@version`), digest, deployment, provider, outcome (`ok`, `cancelled`, `error` or the code), attempts, prompt and completion tokens, latency and first-token time. FND-09 adds an observer that writes the trace span (`model@version`, EA-26 AC2) and the usage event (EA-26 AC4). An observer must not block; one that raises is logged as `observer failed (<ClassName>)` and never changes the call's result.

The default `LoggingObserver` writes one line per call on logger `ei_ai.model_gateway`, message `model call`, metadata fields only (INFO, WARNING on failure). Never: messages, deltas, the answer, embedding inputs, the rerank query or documents, a key, a URL or an upstream body (`tests/model_gateway/test_gateway_logs.py` puts a sentinel in each and checks every log record at DEBUG for every logger, every exception in the chain and every record). FND-08 moves the line onto its masked JSON logger.

## Operator commands

```bash
docker compose exec -T api ei-ai model add --org <ORG_ID> --model qwen3-4b-instruct-2507@2026.10
docker compose exec -T api ei-ai model try --org <ORG_ID> --model qwen3-4b-instruct-2507@2026.10 [--prompt TEXT] [--max-tokens N]
```

- `model add` copies a manifest entry into the Organization's catalog with the audit event `model.catalog_entry_added`: `added: <ref> (<kind>, <deployment>)`; `already present: <ref>` when the ref is there (no new row, no audit). `error: unknown model <ref>; known: …` lists the manifest.
- `model try` streams the answer to stdout, then prints `done: model=<ref> digest=<sha256:12 hex|none> prompt_tokens=… completion_tokens=… attempts=… first_token_ms=… total_ms=…`. A gateway error prints exactly `error: <CODE>: <message>` on stderr (exit 1). The default prompt is `Xin chào, hãy giới thiệu ngắn gọn về bạn.`, the default `--max-tokens` 64.
- Exit codes: 0 done, 1 failed, 2 bad argument. Environment overrides per run (`docker compose exec -T -e K=V api …`): `MODEL_LOCAL_BASE_URL`, `EGRESS_PROXY_URL`, `MODEL_CONNECT_TIMEOUT_SECONDS`, `MODEL_READ_TIMEOUT_SECONDS`.
- The demo seed (`npm run seed`) inserts the three manifest rows into the demo Organization, without audit events and without new output lines.

## Adding a model to the catalog

1. Pick the artefact: the official publisher or `ggml-org` first, otherwise a well-known converter. Record its 40-hex revision and the file's sha256 from the Hugging Face file metadata (`https://huggingface.co/api/models/<repo>/revision/<rev>?blobs=true`, LFS `sha256`), and add the licence rows (`docs/architecture/oss-license-review.md` sections 2 and 3).
2. Add an entry to `backend/src/ei_ai/model_gateway/data/local-models.json` (kind, display name, `model_id`, a new `version` label, `digest` `sha256:<hex>`, `source_revision` `<repo>@<rev>/<file>`, provider, labels). The manifest is validated at load (`tests/model_gateway/test_manifest.py`).
3. For a new local chat model, point the model service at the file: `LLM_MODEL_URL` (the resolve URL at the commit), `LLM_MODEL_FILE`, `LLM_MODEL_SHA256` and `LLM_ALIAS` (= `model_id`) in `.env`, and update the defaults in `compose.yaml` together with the manifest (`scripts/checks/model-manifest.test.mjs` keeps them equal).
4. Copy it into each Organization that should use it: `ei-ai model add --org <ORG_ID> --model <model_id>@<version>`.
5. Never edit a pin: a new file is always a new version (the database refuses the UPDATE). To retire a version, give 30 days' notice (D18): `UPDATE model_catalog SET status = 'retiring', retirement_date = '<date>' WHERE …`; from that date the gateway answers `MODEL_RETIRED`, and it never substitutes another version.

GPU models (qwen3-8b/14b) are added the same way when SET-04/EVL-02 pin and measure them. The embedding and reranker rows are in the catalog, but their servers (`MODEL_EMBEDDING_BASE_URL`, `MODEL_RERANK_BASE_URL`) start with KB-04 (EA-35); until then `embed`/`rerank` answer `MODEL_UNAVAILABLE` without network access.

## Measured overhead

NFR: the gateway adds less than 20 ms per call. `npm run backend -- bench-gateway` (`tests/perf/test_gateway_overhead.py`) sends the same non-streaming request 100 times (after 10 warm-up calls), alternating between the OpenAI SDK straight to a loopback fake server and `ModelGateway` with the real `DbCatalog` (tenant transaction on PostgreSQL), the `GET /v1/models` pin check and the `LoggingObserver`.

Measured on the dev machine (Ryzen 5 5600G, Docker Desktop VM), 2026-10-20: `median_direct_ms=2.46 median_gateway_ms=7.66 median_overhead_ms=5.20 p95_overhead_ms=6.90` (earlier runs the same day: 4.0 and 4.7 ms median). The added time is the catalog read, the listing request and the per-call client.
