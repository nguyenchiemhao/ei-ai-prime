# EA-20 — Per-Organization encryption keys, encrypted files, per-Organization vector partitions

Profile `api`: no HTTP route and no UI. Everything is observed through the Platform Operator CLI, SQL (`psql` as `postgres` / `ei_ai_app`), the backend test suites and the container logs.

## Purpose

Check, from the requirements only, that
- every Organization has its own data key, stored wrapped (60 bytes) and never in plaintext (AC1);
- original files are stored encrypted and decrypt byte-for-byte for the right Organization (AC2);
- decrypting with another Organization's context fails without returning data (AC3);
- a vector query in Organization A's context scans only A's partition (AC4);
- a destroyed key makes the Organization's files unreadable (AC5);
- encrypting or decrypting a 50 MiB file takes less than 1.5 s (NFR1).

There is no upload route yet (KB-02): "through the API" means the backend library, shown by the backend integration suites.

## Preconditions

- Docker, Node >= 22.12; `npm run up -- --no-model` (a stack built from the ticket's final commit: run `npm run up` again after pulling, the `api` image carries the CLI), then `npm run migrate` (head `0009`) and `npm run seed`.
- `.env` holds a generated `EI_AI_MASTER_KEY` (64 hex characters; written by `npm run up` / `npm run migrate`). Never copy it anywhere.
- Playwright browsers are not needed (no page is opened).

## Test data

Every spec creates its Organizations with `org create` and a marker `qa-EA20-<run>-<tag>` (owner `qa-ea20-<run>-<tag>@example.com`), creates vector partitions with `db vector-partition`, and removes them in `afterAll` as `postgres` (partitions dropped, rows deleted children first, RLS untouched). The last step of the spec proves that the row counts of `organizations, workspaces, users, memberships, workspace_memberships, set_password_tokens, user_credentials, admin_sessions, audit_events, organization_keys, chunk_embeddings` and the number of partitions equal the counts taken at the start. The demo Organizations are only read; `npm run seed` is idempotent and leaves them as they are.

## How to run

```
npm run e2e -- e2e/foundation/EA-20-org-encryption-vectors.spec.ts        # fast tier (17 tests)
npm run e2e:full -- e2e/foundation/EA-20-org-encryption-vectors.spec.ts   # adds TC-1-3 and TC-4-7 (@slow)
npm run e2e:perf -- e2e/foundation/EA-20-crypto-perf.spec.ts              # NFR1 (@perf)
npm run e2e -- e2e/foundation/EA-18-multi-tenant-rls.spec.ts e2e/foundation/EA-21-cli-organizations-seed.spec.ts e2e/foundation/EA-94-demo-seed.spec.ts   # existing specs updated for head 0009
node e2e/foundation/scripts/EA-20-org-encryption-vectors-explore.mjs      # exploratory checks (TC-1-9, TC-4-8), cleans up after itself
node e2e/foundation/scripts/EA-20-org-encryption-vectors-check-state.mjs [--cleanup]   # read-only hygiene and invariants check
```

Backend suites by hand (AC2, AC3, AC5):

```
docker compose --profile tools run --rm backend-tools pytest tests/integration/storage tests/integration/crypto -m integration -v --no-cov
npm run backend -- bench-crypto
```

## Cases

| TC | AC | Type | Steps | Expected | Spec / script |
|---|---|---|---|---|---|
| TC-1-1 | AC1 | automated | `org create` for A and B; read `organization_keys` as `postgres` | 4 output lines unchanged, 5 audit events each; one key row each, 60 bytes, different `wrapped_key`, same 16-hex `kek_id`; the master key (hex and raw bytes) in no column of any tenant table and not in the CLI output | `EA-20-org-encryption-vectors.spec.ts` › `AC1` |
| TC-1-2 | AC1 | automated | `docker compose` config of all profiles as JSON | the master key value and the name `EI_AI_MASTER_KEY` appear in `api` and `backend-tools` only | spec › `AC1 TC-1-2` |
| TC-1-3 | AC1 | automated (`@slow`) | `git check-ignore .env`, `git grep` for the key, `npm run migrate` again | `.env` ignored, key in no tracked file, `.env.example` holds `__GENERATED_KEY__`, key unchanged after migrate | spec › `AC1 TC-1-3` |
| TC-1-4 | AC1 | automated | `org create` with `EI_AI_MASTER_KEY` empty / `abc` / 64×`g` / 63×`a` / 65×`a`, both variables set, key file missing / a directory / with invalid content | exit 1, empty stdout, one exact stderr line from the contract (`... is required`, `... must be 64 hexadecimal characters`, `set only one of EI_AI_MASTER_KEY and EI_AI_MASTER_KEY_FILE`, `EI_AI_MASTER_KEY_FILE cannot be read`, `EI_AI_MASTER_KEY_FILE must hold 64 hexadecimal characters`), value, path and file content never printed, nothing written | spec › `AC1 TC-1-4` |
| TC-1-5 | AC1 | automated | write a key file in the `api` container, `org create` with only `EI_AI_MASTER_KEY_FILE` | exit 0; same `kek_id` and 60-byte key as with the variable | spec › `AC1 TC-1-5` |
| TC-1-6 | AC1 | automated | `npm run seed` three times | each demo Organization keeps exactly one key row, identical after re-runs; no vectors, no partition; audit counts unchanged | spec › `AC1 TC-1-6` |
| TC-1-7 | AC1, AC5 | automated | catalog SQL on `organization_keys` | contract columns, RLS enabled and forced, second key for one Organization fails with 23505, `destroyed_at` set iff `wrapped_key` NULL, live key 60 bytes, `kek_id` 16 hex | spec › `AC1 TC-1-7` |
| TC-1-8 | AC1 | automated | sweep of every captured output and of `docker compose logs` | the master key appears nowhere | spec › `AC1 TC-1-8` (last test) |
| TC-1-9 | AC1 | exploratory | `org create` with the upper-case form of the key | record: accepted or rejected, same `kek_id`; the value is never echoed | explore script |
| TC-2-1 | AC2 | automated | backend suites storage + crypto | `test_file_on_disk_is_unreadable_and_decrypts_byte_for_byte` and `test_file_permissions_are_private` PASSED | spec › `AC2` |
| TC-3-1 | AC3 | automated | same run | `test_other_orgs_file_id_is_not_found`, `test_foreign_blob_under_own_directory_fails_to_decrypt`, `test_decrypt_with_another_orgs_context_fails_without_data`, `test_context_of_a_with_session_of_b_finds_no_key`, `test_wrapped_key_copied_to_another_org_does_not_unwrap` PASSED | spec › `AC3` |
| TC-3-3 | AC3 | automated | as `ei_ai_app` in A's context, read/insert/update/delete B's key row | 0 rows; insert and "move to B" fail with 42501 (no key value in the message); B's key byte-identical afterwards | spec › `AC3 TC-3-3` |
| TC-4-1 | AC4 | automated | A and B with partitions, vectors for both (B's is nearest), `explain (format json)` in A's context with `plan_cache_mode = force_custom_plan` | plan names only `chunk_embeddings_<A hex>`; results contain only A's ids, with and without the `org_id` predicate; B's context sees only B | spec › `AC4` |
| TC-4-2 | AC4 | automated | catalog SQL | parent `p`, `LIST (org_id)`, RLS forced; partition owner `ei_ai_migrator`, `FOR VALUES IN (...)`, `hnsw` index, no grant to `ei_ai_app` / `ei_ai_signin`; no DEFAULT partition; 3-dimension vector rejected | spec › `AC4 TC-4-2` |
| TC-4-3 | AC4 | automated | `db vector-partition` in `api` (no migrator credentials), in `migrate`, repeated, unknown id, `not-a-uuid`, missing `--org`, SQL injection text | `configuration error: MIGRATION_DATABASE_URL is required` exit 1; `vector partition created: <id>`; `vector partition already present: <id>`; `error: Organization not found` exit 1; usage error exit 2; nothing created by a refused command | spec › `AC4 TC-4-3` |
| TC-4-4 | AC4 | automated | as `ei_ai_app` in A's context insert a vector for B; no / empty / forged context | 42501, B's partition unchanged; 0 rows in `chunk_embeddings` and `organization_keys` without a valid context; insert without context 42501 | spec › `AC4 TC-4-4` |
| TC-4-5 | AC4 | automated | as `ei_ai_app` select / insert / update / delete on the partition, `create table ... partition of`, `truncate chunk_embeddings`, `drop table <partition>` | all fail with 42501; the partition still exists with its rows | spec › `AC4 TC-4-5` |
| TC-4-6 | AC4 | automated | Organization C without a partition: insert and query in its context | insert fails (no DEFAULT partition), query returns no rows | spec › `AC4 TC-4-6` |
| TC-4-7 | AC4 | automated (`@slow`) | `npm run migrate` while partitions exist | exit 0, `database revision: 0009`, `schema guard: 0 violations` | spec › `AC4 TC-4-7` |
| TC-4-8 | AC4 | exploratory | prepared statement with `force_generic_plan`, `explain (analyze, format json)` | informational: other partitions pruned at run time (never executed) | explore script |
| TC-5-1 | AC5 | automated | backend suites with `-k destroyed` | `test_destroyed_key_blocks_encrypt_and_decrypt`, `test_destroyed_key_makes_files_unreadable` PASSED | spec › `AC5` |
| TC-N-1 | NFR1 | automated (`@perf`) | `npm run backend -- bench-crypto` | exit 0; exactly one line `file crypto 50 MiB: put_median_ms=<n.n> get_median_ms=<n.n> runs=5`, both medians < 1500.0; no row left | `EA-20-crypto-perf.spec.ts` |

## Exploratory flows

TC-1-9, upper-case master key
1. Read the key from `.env` (do not print it).
2. `docker compose exec -T -e EI_AI_MASTER_KEY=<UPPER-CASE KEY> api ei-ai org create --name "qa-EA20-manual-uc" --owner qa-ea20-manual-uc@example.com`.
3. Note exit code, whether the Organization was created and whether its `kek_id` (SQL on `organization_keys`) equals the `kek_id` of another Organization.
4. Check that the output never contains the key; delete the Organization afterwards with the check-state script (`--cleanup` removes everything whose name contains `qa-ea20-`).

TC-4-8, runtime partition pruning
1. Create two Organizations, run `db vector-partition` for both, insert one vector each as `ei_ai_app` in its own context.
2. In A's context: `set local plan_cache_mode = force_generic_plan; prepare q(uuid, vector) as select id from chunk_embeddings where org_id = $1 order by embedding <=> $2 limit 5; explain (analyze, format json) execute q('<A>', '<vector>');`.
3. Expect B's partition to be listed but never executed; A's partition has actual loops 1.
4. Clean up (the explore script does all of this and the cleanup itself).

## Notes for later regressions

- Organizations created before migration 0008 without a key stay without a key until `npm run seed` runs (demo ones) or `npm run reset`.
- `docker compose config` and `logs` list only the services of the active profiles: use `--profile core --profile model --profile tools` to cover them all.
