# Permission-filtered retrieval (EA-36, KB-05)

`ei_ai.knowledge.retrieval.service.retrieve()` is the one retrieval API that answers, chat and
evaluation share. It returns the top-k passages a principal may read, best first, and a trace of
ids and numbers (never text). This run is vector-only; keyword search and RRF come with EA-95.

## Who may read what

| Principal | Access levels matched | Groups matched |
|---|---|---|
| Anonymous | `public` | none |
| Authenticated | `public`, `authenticated` | the principal's groups (case-insensitive) |

`restricted` is never an allowed level by itself: a restricted collection matches only when the
principal's groups overlap its groups. Group membership is not stored yet (EA-89), so a real
session has no groups; only the operator simulator sets them. The same rule exists twice, in SQL
(inside the index query, so the filter runs before top-k) and in Python (`can_read`, used for the
searched/skipped list and the passage load).

## Scope to filter

| Scope | `collection_ids` | `folder_ids` | Vector query |
|---|---|---|---|
| Whole collections | the readable ones | `()` | yes |
| Folders (with sub-folders) | `()` | the readable folders and descendants | yes |
| Both | the readable ones | the readable folders | yes |
| Nothing readable, or empty | `()` | `()` | no (empty result, fail closed) |

An id that is unknown, in another Workspace or in another Organization is `not_found`, identical
in all three cases (no existence oracle, D46). An unreadable collection, and a folder in one, is
`no_access`. `nearest` never receives `collection_ids=None` from this package.

## Trace

`RetrievalTrace`: principal kind, `simulated`, group count (not names), `retrieval=vector`,
embedding model, `rerank` (`off` | `applied` | `unavailable`) and rerank model, searched
collection ids, skipped ids with reason, the permitted candidates (at most 20) with vector and
rerank scores, the top-k chunk ids and timings. No question, text, names or user id (D52).

## Reranker

`RERANK_MODEL_REF` unset means `rerank=off`. Set, it must name a local `rerank` model of the
platform manifest; the reranker sees only permitted passages. If it fails, the vector order is
kept and the trace says `unavailable`. `applied` means the reranker scored at least one passage: with
zero permitted candidates the model is not called and the trace says `off` (`rerank_model` stays set).

## Locks

`retrieve` runs in the caller's tenant transaction with plain SELECTs: ACCESS SHARE table locks, no
row locks. It never blocks or waits on indexing, uploads or access changes (MVCC). Only ACCESS
EXCLUSIVE DDL (migrations, creating a vector partition) waits for it. The question is embedded
before the first statement, so the model call adds no hold time; a rerank call does.

## Operator command

`ei-ai index retrieve` runs `retrieve` as a simulated person; see the README. There is no
similarity threshold: passages = min(k, permitted candidates). "Not found" decisions belong to KB-06.

## EA-95 seam and follow-ups

`service._candidates` is the single place EA-95 adds keyword candidates and RRF. Follow-ups: member
groups (EA-89), the trace store (FND-09), the hit@3 measurement (EVL-03), the 800 ms p95 NFR.
