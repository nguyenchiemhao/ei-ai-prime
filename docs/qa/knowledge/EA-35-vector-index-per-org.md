# EA-35 [KB-04] Vector index per Organization — QA cases

Thin slice (owner decision 2026-10-23): vectors only. Deferred and not covered here: AC2 (accent-stripped keyword search), AC5 (segmentation report and ADR), the keyword half of AC1, hybrid fusion, the 300 ms p95 NFR over 50,000 chunks. No UI change and no new HTTP route: the index is observed through the operator CLI `ei-ai index`, the EA-32/EA-33 routes and SQL on `chunk_embeddings`.

## Purpose

Prove that every Ready document gets one vector per chunk (within 2 minutes for a 50-page document), that each vector carries collection id, access level and groups (kept in step with access changes), that one Organization's vectors never show up for another, and that each vector stores the embedding model name and version with a whole-Organization reindex command.

## Preconditions and test data

- Stack running with the model profile: `npm run up` (the `embedding` service, bge-m3, must be `healthy` in `docker compose ps embedding`; first start downloads about 0.6 GB), then `npm run seed`.
- Accounts (seed, see `docs/dev/seed-data.md`): Linh Tran (Mekong org admin), Thao Nguyen (Mekong knowledge editor), Ngân Trịnh (Sông Hàn Retail org admin). Password: `EI_AI_SEED_PASSWORD` from `.env`.
- Every spec creates its own folders, collections and files named `qa-EA35-<run>` (Vietnamese NFC/NFD text, a second topic, a scanned PDF, a 50-page PDF, a 150 KB TXT), uploads only there and deletes them in teardown (documents first, so their vectors go too). Seed rows are never changed. Each spec proves in `afterAll` that the row counts of `chunk_embeddings`, `document_chunks`, `documents`, `folders`, `collections` and the document/folder/collection audit rows equal the counts before the run and that no row carries the marker.
- Operator CLI: `docker compose exec -T api ei-ai index status|reindex|search ...` (exit 0 done, 1 failed, 2 bad argument). SQL: `docker compose exec -T db psql -U postgres -d ei_ai -c "..."`.

## How to run

```
npm run e2e -- e2e/knowledge/EA-35-vector-index.spec.ts                 # fast tier, about 4 minutes
npm run e2e:full -- e2e/knowledge/EA-35-vector-index-slow.spec.ts       # @slow: large document, logs, embedding stopped (about 6 minutes)
npm run e2e:perf -- e2e/knowledge/EA-35-vector-index-perf.spec.ts       # @perf: 50-page PDF
node e2e/knowledge/scripts/EA-35-vector-index-access-lock.mjs [--direct] [--kb 150]   # how long PUT access blocks behind an index job
```

The slow spec stops the `embedding` service in its last test and always starts it again (waits for healthy). Run it only on a stack nobody else is using.

## Cases

| TC | AC | Type | Steps | Expected | Spec or script |
|---|---|---|---|---|---|
| TC-1-1 | AC1 | automated | Thao uploads a 2-page Vietnamese TXT, waits for Ready, polls `index status --org A --document <id>` every 2 s | `indexed=1 not_indexed=0 stale=0 model=bge-m3@2026.10` within 120 s of Ready; vectors = chunk count; document stays `ready`; collection `documents.ready` +1 | `EA-35-vector-index.spec.ts` AC1 TC-1-1 |
| TC-1-2 | AC1 | automated | Upload a TXT containing only `Đơn xin nghỉ phép năm` | 1 chunk, 1 vector | same, TC-1-2 |
| TC-1-3 | AC1 | automated | Upload a scanned PDF (ends `not_supported`/`failed`) | no vectors; org `ready_documents` and `vectors` unchanged | same, TC-1-3 |
| TC-1-4 | AC1 | automated | Delete an indexed document | 204; 0 vectors for it right after; org `vectors` drops by its count | same, TC-1-4 |
| TC-1-5 | AC1 | automated | `index search` with Vietnamese questions on two topics, `--k 1/5/40` | right document first; hit lines only (no text); ranks consecutive, distances non-decreasing | same, TC-1-5 |
| TC-1-6 | AC1 | automated | Same text uploaded NFC and NFD, search | distances per chunk equal within 0.005 (the embedding server is not bit-exact: re-embedding the same text moved distances by about 0.0007) | same, TC-1-6 |
| TC-1-7 | AC1 | automated @perf | 50-page text PDF: time from Ready to `indexed=1` | at most 120 s (measured 88.8 s, 100 chunks); stays `ready` | `EA-35-vector-index-perf.spec.ts` |
| TC-1-8 | AC1 | automated @slow | Stop `embedding`, upload, `index status/reindex/search`, start, reindex | document Ready, `not_indexed=1`; model commands exit 1 with `failed:`/`error: <CODE>: ...` and no traceback; after restart `indexed:` and exit 0 | `EA-35-vector-index-slow.spec.ts` TC-1-8 |
| TC-3-1 | AC3 | automated | Linh: restricted collection `["HR-Team"]`, upload, SQL on its vectors | every row has org, collection, workspace, folder, document ids, `restricted`, `{hr-team}` | fast spec TC-3-1 |
| TC-3-2 | AC3 | automated | `PUT access` public, authenticated, restricted (2 groups), restricted (1 group); SQL right after each answer | vectors follow at once; other collections' and Sông Hàn vectors unchanged | fast spec TC-3-2 |
| TC-3-3 | AC3 | automated | New document after an access change | new vectors carry the new level/groups; old ones too | fast spec TC-3-3 |
| TC-3-4 | AC3 | automated | SQL rules over the whole table | no null ids, level in the 3 values, restricted has groups, others none, groups lower case | fast spec TC-3-4 |
| TC-3-5 | AC3 | automated @slow | 150 KB document Ready, change access 3 times through the admin origin while it indexes | every change answered 200/204 within normal request time (no 504); vectors end equal to the collection's access (passes since the Q1-1 fix; before, the first PUT returned 504 after 60 s) | slow spec TC-3-5, `EA-35-vector-index-access-lock.mjs` |
| TC-3-6 | AC3 | automated @slow | Same, three overlapping PUTs straight at the API port | all 200/204; vectors end equal to the collection's access | slow spec TC-3-6 |
| TC-4-1 | AC4 | automated | Same text in both Organizations; `index search --org B --k 40` and for A | only the own Organization's documents/collections in the output | fast spec TC-4-1 |
| TC-4-2 | AC4 | automated | `reindex`/`status` with the other Organization's document id | `error: document not found`, exit 1, empty stdout, same as a random id; nothing changes | fast spec TC-4-2 |
| TC-4-3 | AC4 | automated | Query in B for text that exists only in A, `--k 40` | no A id | fast spec TC-4-3 |
| TC-4-4 | AC4 | automated | `--collection` of the other Organization | no hit; own collection gives hits of that collection only | fast spec TC-4-4 |
| TC-4-5 | AC4 | automated | SQL join to documents and collections | `org_id` always equal | fast spec TC-4-5 |
| TC-4-6 | AC4 | automated | `npm run seed` again | two lines `vector partition already present: <id>`; no row changes | fast spec TC-4-6 |
| TC-4-7 | AC4 | automated | `org_id`/`X-Org-Id` in query, headers and body of upload and access routes | ignored; vectors only in the signed-in Organization | fast spec TC-4-7 |
| TC-4-8 | AC4 | automated | `docker compose --profile model config` | `embedding` has no published port, no secrets, no credential-like env key | fast spec TC-4-8 |
| TC-4-9 | AC4 | automated @slow | Sentinel string in a document; `index search/reindex/status`; API logs | sentinel and text never in CLI output or API logs | slow spec TC-4-9 |
| TC-6-1 | AC6 | automated | SQL distinct model per document | exactly `bge-m3` / `2026.10` | fast spec TC-6-1 |
| TC-6-2 | AC6 | automated | `index reindex --org A` | one `indexed:` line per Ready document, `done: ... failed=0 model=bge-m3@2026.10`, exit 0, same counts, new vector ids and `created_at`, Sông Hàn untouched | fast spec TC-6-2 |
| TC-6-3 | AC6 | automated | `index reindex --org A --document <id>` twice | vectors replaced, no duplicates | fast spec TC-6-3 |
| TC-6-4 | AC6 | automated | `-e EMBEDDING_MODEL_REF=qwen3-4b-instruct-2507@2026.10` / `no-such-model@1` | `configuration error: ...`, exit 1, no vector changed | fast spec TC-6-4 |
| TC-6-5 | AC6 | automated | SQL changes `model_version`/`model_id` of two documents (simulated old model); status; per-document reindex | `stale=1 indexed=0`, org `stale` +2; after reindex current model again | fast spec TC-6-5 |
| TC-6-6 | AC6 | automated | Bad `--org`, `--document`, `--k`, missing action, unknown Organization | exit 2 with the documented messages; unknown Organization exit 1 `error: Organization not found` | fast spec TC-6-6 |

Not covered (needs a second embedding model in the manifest): a real switch to a different model. The command and its error path are covered by TC-6-4 and TC-6-5.

## Exploratory flow (no UI; by hand with the CLI)

1. Sign in as Linh and create a public collection with a folder. Upload a 150 KB TXT file.
2. As soon as the document is Ready, run `docker compose exec -T api ei-ai index status --org 0192a000-0000-7000-8000-00000000ea21 --document <id>`: `not_indexed=1`.
3. Change the collection access to restricted with group `race-one` (admin UI "Access & settings", or `PUT .../access`).
4. Note how long the change takes. Expected: an answer within a few seconds. Today: the answer waits until the index job ends (about 45 s for 60 KB, about 100 s for 150 KB) and the admin origin answers 504 after 60 s.
5. Run the status command until `indexed=1`; then `SELECT access_level, groups, count(*) FROM chunk_embeddings WHERE document_id = '<id>' GROUP BY 1, 2`: all `restricted {race-one}`.
6. Delete the document, folder and collection.
