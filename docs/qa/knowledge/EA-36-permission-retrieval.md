# EA-36 [KB-05] Permission-filtered retrieval, then rerank — QA cases

Black-box checks of `ei-ai index retrieve` (no UI, no new HTTP route). Retrieval is vector-only in this ticket; the AC6 hit@3 measurement and the 800 ms p95 NFR are deferred and are not tested.

## Preconditions and test data

- Stack up with the model profile (the `embedding` service healthy; the chat model is not needed): `docker compose --profile core --profile model up -d --build --wait api admin embedding`, then `npm run seed`.
- Accounts: Linh Tran (org admin, Mekong Devworks), Ngân Trịnh (org admin, Sông Hàn Retail), Quang Le (Engineering). Password: `EI_AI_SEED_PASSWORD` (`docs/dev/seed-data.md`).
- The spec builds its own data in `beforeAll` and removes it in `afterAll`, all named `qa-EA36-<run>-...`: P (public, EN + VI file), A (authenticated), M (restricted `Managers`), H (restricted `hr`), X (authenticated, folders `f1`/`f1a`/`f2`), bait collections in Sông Hàn and in Mekong Engineering, and (TC-4-2) a 100+ chunk restricted flood. Seed rows are never changed.

## How to run

```
npx playwright test e2e/knowledge/EA-36-permission-retrieval.spec.ts --grep-invert "@slow|@perf"   # 28 tests, about 4.5 min
npx playwright test e2e/knowledge/EA-36-permission-retrieval.spec.ts --grep "@slow"                 # 8 tests: TC-1-5, 3-5, 3-6, 4-2, 5-4, 5-8..10; about 5.5 min
QA_RERANK_FROM_ENV=1 npx playwright test e2e/knowledge/EA-36-permission-retrieval.spec.ts --grep "TC-6-5"   # only with RERANK_MODEL_REF=bge-reranker-v2-m3@2026.10 in .env and api recreated; restore .env afterwards
node e2e/knowledge/scripts/EA-36-permission-retrieval-hygiene.mjs [before.txt]                      # row counts, marker rows, orphan vectors
```

Run the file on its own (RAM). Helpers: `e2e/support/ea36.ts` (command parser, output-format checks, SQL oracle, cleanup).

## Cases

| TC | AC | Kind | Steps | Expected | Spec |
|---|---|---|---|---|---|
| TC-1-1 | AC1 | automated `@slow` `@slow` `@slow` `@slow` `@slow` `@slow` `@slow` | 5 topic questions, scope P,A,M,H,X, `--as anonymous --k 10` | only P searched; A,M,H,X `skipped no_access`; passages only from P | `AC1` |
| TC-1-2 | AC1 | automated | 5 more (confidential wording, injection sentence, Vietnamese) | same | `AC1 TC-1-2` |
| TC-1-3 | AC1 | automated | Vietnamese query in NFC and NFD | P only, VI file found | `AC1 TC-1-3` |
| TC-1-4 | AC1 | automated | 1 char, 2000 chars, SQL/shell/HTML metacharacters | exit 0, P only | `AC1 TC-1-4` |
| TC-1-5 | AC1 | automated `@slow` | invalid `--org/--workspace/--collection/--folder/--k/--as/--query` | exit 2, exact message, empty stdout | `AC1 TC-1-5` |
| TC-1-6 | AC1 | automated | unknown Organization / Workspace | exit 1, exact message | `AC1 TC-1-6` |
| TC-2-1 | AC2 | automated | 5 topics, `--as authenticated --k 10` | P, A, X searched; M, H skipped; never Restricted | `AC2` |
| TC-2-2 | AC2 | automated | unrelated groups | same passages as no group | `AC2 TC-2-2` |
| TC-2-3 | AC2 | automated | default k, `--k 1` | 4 passages; k=1 is the best one | `AC2 TC-2-3` |
| TC-3-1 | AC3 | automated | "salary review bands" as Managers / no group / hr | only Managers get M passages | `AC3` |
| TC-3-2 | AC3 | automated | `Managers`, `MANAGERS`, `mAnAgErS` | same as `managers` | `AC3 TC-3-2` |
| TC-3-3 | AC3 | automated | near-miss groups | M stays skipped | `AC3 TC-3-3` |
| TC-3-4 | AC3 | automated | hr, managers, both | each sees only its own | `AC3 TC-3-4` |
| TC-3-5 | AC3 | automated `@slow` | forged/invalid group names, limits (64 chars, 100 values) | exit 2 + exact message, or exit 0 with right `groups=<n>` | `AC3 TC-3-5` |
| TC-3-6 | AC3 | automated `@slow` | injection-style group values | literal names, never open Restricted | `AC3 TC-3-6` |
| TC-3-7 | AC3 | automated | change M's access (public, authenticated, other groups, back) | the next run reflects it at once | `AC3 TC-3-7` |
| TC-3-8 | AC3 | automated | `--as anonymous --collection M --collection H` | `searched=0 skipped=2 candidates=0 passages=0`, exit 0 | `AC3 TC-3-8` |
| TC-4-1 | AC4 | automated | M's exact sentence as the query, k=4 | full 4 permitted passages, candidates = min(20, permitted) | `AC4` |
| TC-4-2 | AC4 | automated `@slow` | restricted flood with 100+ matching chunks | no group/anonymous/hr: 4 passages from P; managers: flood on top; access change at once | `AC4 TC-4-2` |
| TC-5-1..3 | AC5 | automated | `--collection`, `--folder` (sub-folders), union and duplicates | only the scope | `AC5`, `AC5 TC-5-2`, `AC5 TC-5-3` |
| TC-5-4 | AC5 | automated `@slow` | default scope | every People Ops collection on one line; no id of other Workspace/Organization | `AC5 TC-5-4` |
| TC-5-5 | AC5 | automated | folder of a Restricted collection; folder/collection id confusion | `no_access` / `not_found` with the right kind | `AC5 TC-5-5` |
| TC-5-6 | AC5 | automated | empty scopes | exit 0, 0 passages | `AC5 TC-5-6` |
| TC-5-7 | AC5 | automated | delete a document | none of its chunks retrieved | `AC5 TC-5-7` |
| TC-5-8..10 | AC5 | automated | ids of another Organization / Workspace / unknown | identical `not_found` output; no foreign id printed | `AC5 TC-5-8`..`TC-5-10` |
| TC-6-1 | AC6 | automated | AC2 run with and without `RERANK_MODEL_REF=bge-reranker-v2-m3@2026.10` | `rerank=off` vs `rerank=unavailable`, same passages | `AC6` |
| TC-6-2 | AC6 | automated | wrong `RERANK_MODEL_REF` | configuration error, exit 1 | `AC6 TC-6-2` |
| TC-6-3 | AC6 | automated | unavailable reranker with anonymous/no group | permission filter unchanged | `AC6 TC-6-3` |
| TC-6-4 | AC6 | automated | reranker configured, zero permitted candidates (unknown id; restricted-only scope) | `rerank=off`, exit 0; control with candidates stays `unavailable` | `AC6 TC-6-4` |
| TC-6-5 | AC6 | automated (opt-in env) | RERANK_MODEL_REF set in .env, no `-e` | api container has it: `unavailable` with candidates, `off` with none | `AC6 TC-6-5` |
| TC-7-1..3 | AC7 | automated | run report; sentinel in a Restricted doc and the query; ids and numbers only | trace lines complete; no sentinel/query/text in CLI output or `api` logs | `AC7`, `AC7 TC-7-2`, `AC7 TC-7-3` |

There are no exploratory flows (profile `api`).

## Data hygiene check

Save the counts before (`node e2e/knowledge/scripts/EA-36-permission-retrieval-hygiene.mjs > before.txt`), run the specs, then `node e2e/knowledge/scripts/EA-36-permission-retrieval-hygiene.mjs before.txt`: exit 0 means equal counts, no `qa-ea36` row and no orphan vector.
