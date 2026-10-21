# Proposed tickets and follow-ups

Collected on 2026-10-21 from every `.work/EA-*/final.md` (EA-11, 12, 13, 16, 18, 19, 22, 24, 85), `docs/dev/team-retro.md` and the Jira `proposed` label. Nothing in sections 1–2 exists in Jira yet: the owner reviews this list first, and approved items are created with label `proposed` through jira-ticket-management.

Status values: **new** (not in Jira), **in Jira** (already created), **hand-off** (belongs to an existing ticket, add a note there), **dropped** (already resolved).

## 1. New product / code tickets (not in Jira)

| # | Proposed summary | Source | Why | Relates to |
|---|---|---|---|---|
| P1 | Add a total-call deadline to Model Gateway streams | EA-24 R1-6 | Only per-read timeouts exist, so a slow-drip upstream can hold a call and its connection open indefinitely. | FND-10 (EA-27), PIPE-07 (EA-57) |
| P2 | Align Platform Operator CLI exit codes for argument errors | EA-24 Lead review | `ei-ai org create` (EA-21) exits 1 on a bad `--org`, `ei-ai model …` (EA-24) exits 2. Pick one convention for every command. | EA-21, EA-24 |
| P3 | Check the answering model on rerank before adding a cloud rerank provider | EA-24 Lead review | Rerank pins only through the local `/v1/models` check; a cloud rerank provider would have no snapshot check (D18). | ADM-04 (EA-70) |
| P4 | Harden admin sign-in (final-review follow-ups) | EA-22 final review M2, M3, M4, M7, M8, M9 + Task 3/5/6 minors | Includes a trusted-proxy peer check, last `X-Forwarded-For` value, residual rejection timing, eager `dummy_verify` (one-time timing leak per process), an index on `users(email)`, client password length in code points, a stale cached CSRF token, purging idle-expired sessions, a rate limit on `/auth/set-password`, deleting the previous session only after a successful sign-in, a 500 on `/auth/*` that bypasses no-store, and origin normalisation in CSRF. | EA-22 |
| P5 | Answer 503 with an error code when the database is down | EA-18 QA, EA-22 Q2-1 | A DB outage gives a bare 500, and session-checked routes answer 401, which sends users back to `/sign-in`. | EA-22, MVP resilience |
| P6 | Make the admin shell responsive at phone width (390 px) | EA-22 Q1-3 | Outside EA-22's contract; the shell breaks on narrow screens. | EA-22, DSN-02 (EA-92) |
| P7 | Fix admin console frontend robustness gaps | EA-22 Task 10–12 minors | `signOut` clears the local session even when the request failed; a malformed non-JSON 200 becomes an unhandled rejection on the sign-in page; a failed `refresh()` leaves a blank page; choosing the current Workspace does not return focus; `useMenu` keyboard and outside-click paths are untested. | EA-22 |
| P8 | Close tenant-isolation hardening gaps | EA-18 R2-1, R2-2; EA-11 R3-5; EA-22 Task 2; EA-19 R3-1, R3-2 | Global UUID keys reveal whether an id exists in another Organization (documented limitation); restrictive policies are not checked for the `NULLIF` form; PUBLIC default grants (TEMP, EXECUTE) contradict the sign-in role docs; the TenantContext construction test misses `dataclasses.replace`/aliases; the `<table>_id` naming rule cannot express non-row public ids (WGT-03 Channel keys). | EA-18, EA-19, EA-22 |
| P9 | Clean up the EA-22 auth test suite | EA-22 Task 1–9, 11–12 minors (test-only) | Includes the untested `UNIQUE(org_id, token_hash)`, the 15-minute lock duration and lockout boundary, the `LIMIT 10` cap, a contention test that does not force a race, `test_dummy_verify_runs` asserting nothing, the never-log check that skips tracebacks, no cross-org cases for credentials, a fixed 20 ms sleep and an English-only permission message match. Tests only, no product change. | EA-22 |
| P10 | Fix local environment and dev tooling papercuts | EA-13 R1-10, Q1-3, R1-9, R3-1; EA-11 | `--native test-integration` cannot reach the DB (refuse it), the reused model volume warning (mark it `external`), pin the Compose checksum instead of downloading it, run the AC1 E2E on Compose 2.20.x for real, document `.wslconfig` memory (VM 7.2 GB vs 7.25 GiB limits). | SET-03 (EA-13) |
| P11 | Restrict admin nginx `/api/*` forwarding to the routes the console uses | EA-13 Q1-2 | `/api/docs` and `/api/openapi.json` are reachable through the admin nginx. Check first whether EA-22 already closed this. | EA-13, EA-22 |
| P12 | Finish the bilingual test set | EA-16 plan + review 3 | Owner review of every item, a human cross-labelling pass, a second sample richer in `data`/`task`, outsider-written groups A/B, a guide check that also catches curly quotes/backticks, checksum-pinned archive files. | EA-16, EVL-02 (EA-30) |
| P13 | Make CI fail when a test suite collects 0 tests | EA-16 | A suite that finds no tests currently passes. | SET-03 (EA-13) |
| P14 | Fix design canvas consistency items | EA-85, EA-13, EA-22 Task 11–12 | CH-17 avatar colour rule, X16 hit areas re-check, the Members artboard's 7th member (An Do) missing from the seed manifest, VI wording of the shell ("Không gian làm việc" vs "Workspace") for the owner to confirm, px literals and missing error/font tokens. | DSN-02 (EA-92) |
| P15 | Fix small docs and check nits | EA-11 R3-6; EA-12 R2-1, R2-2 | The ADR docs test should reject "pending"; MariaDB row 12.3.3 vs 13.0.2; the psycopg Conditions cell should name the LGPL-2.1 text. | — |

## 2. Pipeline / process changes (not Jira; owner decides, then the Lead edits the files)

| # | Change | Source | Status |
|---|---|---|---|
| X1 | Agents read the ticket from `.work/EA-<n>/ticket.md` that the Lead writes; the Lead posts the plan comment; drop `mcp__claude_ai_Atlassian__*` from `ticket-planner`, `developer` and `code-reviewer` | retro EA-21, EA-24 (recurring) | not applied; it hit both runs |
| X2 | Planner: `Developer model: opus` only when a design decision is open; `plan.md` ≤ ~25 KB, long contract tables in `contract.md` | retro EA-21 | not applied (EA-24 plan was ~26 k tokens; developer 63 % of cost) |
| X3 | Coding rule: a shared HTTP client used for more than one Organization keeps no cookies and no per-tenant headers, proven by a two-Organization test | retro EA-24 | not applied |
| X4 | Merge flow: push the ticket branch and wait for its CI before any merge, also manual ones | retro EA-24 (EA-21 and EA-22 merges left `main` red for 3 merges) | not applied |
| X5 | deliver-ticket: grep the code a new contract line constrains before adding it; designer keeps an sp-8 plan at ≤ 8 tasks and lists dependent minors under the later task | retro EA-22 | not applied |
| X6 | Test portability: no OS-specific absolute paths in Node tests (CI is Linux, dev is Windows) | EA-24 CI fix (`303bd0a`) | proposed |

## 3. Already in Jira with label `proposed` (To Do)

| Key | Summary |
|---|---|
| EA-86 | [SET-06] Enforce the approved licence list in CI and ship a NOTICES file with every image (also takes EA-13 R1-7: npm dev tools without licence rows) |
| EA-87 | [KB-09][Spike] Decide how Vietnamese keyword search tokenises text without an unlicensed word segmenter |
| EA-88 | [WGT-12] Let signed-in members chat with an Assistant on the console Chat page, with citations, Sources panel and Skill results |
| EA-89 | [FND-13] Add the Member role, per-member knowledge groups and an External user ID to Members & roles |
| EA-90 | [WGT-13] Provide a built-in Console chat Channel per Workspace that runs the pipeline with the signed-in member's identity |
| EA-91 | [WGT-14] Keep and search each member's console chat history with 90-day retention and rated-only reviewer access |
| EA-92 | [DSN-02] Define the UI style rules and apply them across the canvas |
| EA-93 | [ADM-10] Show Console chat as its own channel on the Dashboard (also covers EA-85 GL-17) |

## 4. Hand-offs to existing tickets (add a note, no new ticket)

| Item | Target ticket |
|---|---|
| Run the embedding and reranker model servers in compose (artefacts already pinned in the EA-24 manifest) | KB-04 (EA-35) |
| Map the gateway error codes (`MODEL_UNAVAILABLE`, `PINNED_VERSION_UNAVAILABLE`, …) to bilingual widget messages | WGT-02 (EA-41) |
| Move `model_gateway/transport.py` behind the `egress` module and its lint rule | FND-10 (EA-27) |
| Move the gateway's metadata log line onto the masked logger | FND-08 (EA-25) |
| Implement a `ModelCallObserver` that writes the trace span and the usage event | FND-09 (EA-26) |
| Add GPU models (qwen3-8b/14b) with `ei-ai model add` once measured | SET-04 (EA-14), EVL-02 (EA-30) |

## 5. Dropped (already resolved)

- EA-11 R3-2, R3-3 and EA-13 R1-15 (model healthcheck, start-up checksum, PoC model tests): done in EA-24.
- EA-11 R3-4 (`LLAMA_CACHE`): removed from compose in EA-24.
- EA-12 proposed tickets: created as EA-86 and EA-87.
- EA-18 "choose the Organization at sign-in": done in EA-22.
- EA-19 slow E2E: done by the 2026-10-15 test tiers (`@slow`/`@perf`).
- EA-24 "CI on main is red": fixed by `303bd0a`; CI green on `main` (run 39528955547).
