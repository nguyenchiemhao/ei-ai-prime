# EA-37 [KB-06] RAG answers with citations, strict mode and "Ask this collection" — QA cases

Black-box checks of `POST /api/workspaces/{workspace}/collections/{collection}/ask` (SSE stream) and of the "Ask this collection" panel of the console (Knowledge → collection). Written from the ticket contract only. Deferred by the owner and not tested here: the AC3 ratio on the real EVL-03 set and the AC5 "first token ≤ 3 s" gate on the reference configuration (both via EVL-02, EA-17 / EA-30); the "invalid citations are removed" half of AC2 is a backend unit test.

## Preconditions and test data

- Stack with the `model` profile (services `model` = chat model, `embedding`, `api`): `npm run up`, then `npm run seed`. The chat model needs about 4 GB of RAM: run one Playwright file at a time.
- Accounts of the demo seed (password `EI_AI_SEED_PASSWORD`, see `docs/dev/seed-data.md`): Thao Nguyen (Knowledge Editor), Minh Pham (Builder), Linh Tran (Org + Workspace Admin) may ask; Son Hoang (Viewer) and Ha Vu (Reviewer) get 403; Ngân Trịnh and Quang Le provide other-scope collections.
- The specs create their own data, all named `qa-EA37-<run> ...`: `Public` (Public, `Office Hours.md`), `Handbook` (Authenticated, `Leave Policy 2026.md`), `Managers` (Restricted `managers`, `Salary Review.md`), `Probe` (Authenticated, a sentinel file and an injection file), and empty `Bare ...` collections for the fast tier. `afterAll` deletes everything and proves that the row counts equal the counts before the run and that no row carries the marker.
- Sign-ins of a run add `admin_sessions` and `user.signed_in` audit rows (like every other spec). They carry no marker: delete the ones created since the start of the run (see the hygiene script).

## How to run

```
npm run e2e -- e2e/knowledge/EA-37-ask-collection.spec.ts                 # fast, about 1 min (stand-in for the ask route; real route for validation / permissions)
npm run e2e:full -- e2e/knowledge/EA-37-ask-collection-slow.spec.ts       # @slow, real chat model, about 7 min; stops and starts the model services (AC7)
npm run e2e:perf -- e2e/knowledge/EA-37-ask-collection-perf.spec.ts       # @perf, AC5 timings -> .work/EA-37/perf-ac5.json
npm run e2e:full -- e2e/knowledge/EA-37-ask-collection-explore.spec.ts    # exploratory flows X1-X9 -> .work/EA-37/explore-results.json + screenshots
node e2e/knowledge/scripts/EA-37-ask-collection-hygiene.mjs [before.txt]  # row count of every table, marker rows, orphan vectors
node e2e/knowledge/scripts/EA-37-ask-collection-one-ask.mjs <ws> <col> "<question>" [kind] [groups]   # one ask, frames with timing, answer_done log lines
```

Helpers: `e2e/support/ea37.ts` (ask client with SSE frame timing, stream and citation checks, fixtures, hygiene, stand-ins for the ask route). The AC3 ratio is written to `.work/EA-37/ac3-result.json`.

## Cases

Specs: `F` = `EA-37-ask-collection.spec.ts`, `S` = `...-slow.spec.ts`, `P` = `...-perf.spec.ts`, `X` = `...-explore.spec.ts`.

| TC | AC | Kind | Steps | Expected | Spec |
|---|---|---|---|---|---|
| TC-1-1 | AC1 | automated `@slow` | Thao, `Handbook`, Signed-in user, ask "How many days of paid leave do I get when I marry?" | answered, contains "3", ≥ 1 `[n]`, row "Leave Policy 2026 · §4.1 Personal leave", scores `d.dd`, cited row `data-cited=true` | S `AC1` |
| TC-1-2 | AC1 | automated `@slow` | same in Vietnamese | answered, `data-language=vi`, §4.1 row | S `AC1 TC-1-2` |
| TC-1-3 | AC1 | automated | stream stand-in: answered; rows with page, section null, section null + page | rows `[n]` only when cited; "Title", "Title · p. N", "Title · Section · p. N" | F `AC1 TC-1-3` |
| TC-1-4 | AC1 | automated `@slow` | API ask on `Handbook` | passages frame keys/shape, no document text, §4.1 first, answer cites it | S `AC1 TC-1-4` |
| TC-1-6 | AC1 | automated | what the UI sends | body keys exactly `question`, `principal`; CSRF header | F `AC1 TC-1-6` |
| TC-1-7 | AC1 | automated | Thao, Minh, Linh ask on an empty collection | 200 stream, no passages, `done not_found` | F `AC1 TC-1-7` |
| TC-1-8 | AC1 | automated | HTML / Markdown in answer and titles | plain text, no XSS | F `AC1 TC-1-8` |
| TC-1-9 | AC1 | automated | Son (Viewer), Ha (Reviewer) ask | 403 `forbidden`, no stream | F `AC1 TC-1-9` |
| TC-1-10 / 1-11 | AC1 | automated | odd questions; 5 parallel asks | never 5xx; well-formed streams | F `AC1 TC-1-10`, `TC-1-11` |
| TC-1-12 | AC1 | exploratory | big collection, broad question | ≤ 3 rows, best first | not run in this ticket |
| TC-2-1 | AC2 | automated `@slow` | 5 answerable questions (API) | every `[n]` in deltas and `done.answer` ∈ 1..passages; `done.citations` ⊆ passages | S `AC2` |
| TC-2-2 | AC2 | automated | stand-in with guesses and invalid `[7]` in deltas | `done` replaces the text; no invalid `[n]`, no guess | F `AC2 TC-2-2` |
| TC-2-2b | AC2 | automated `@slow` | cut the connection after the first delta, ask again | next ask is a valid stream | S `AC2 TC-2-2` |
| TC-3-1 | AC3 | automated `@slow` | the 10 unanswerable questions on `Handbook` | ≥ 8 `done not_found` (result 10/10) | S `AC3` |
| TC-3-2 | AC3 | automated `@slow` | UI, one English and one Vietnamese not-found | message in the question's language, rows uncited | S `AC3 TC-3-2` |
| TC-3-3 | AC3 | automated | stand-in: not-found (en, vi, no passages) | messages; no-passages text only when 0 passages | F `AC3 TC-3-3` |
| TC-3-4 | AC3 | automated `@slow` | gibberish, `?`, facts of other collections | `done not_found` | S `AC3 TC-3-4` |
| TC-4-1 | AC4 | automated `@slow` | vi then en question in the UI; vi not-found | vi answer with diacritics / en answer without; vi not-found message | S `AC4` |
| TC-4-2 | AC4 | automated `@slow` | API language field | `vi` / `en` per question; mixed → `vi` | S `AC4 TC-4-2` |
| TC-4-3 / 4-4 | AC4 | automated | language detection without a chat model; Vietnamese rendering | `vi` for diacritics (NFC and NFD), `en` otherwise | F `AC4 TC-4-3`, `TC-4-4` |
| TC-5-1 | AC5 | automated `@perf` | cold + 3 warm API asks, then UI | several deltas before done; UI text grows while `answering`; times saved | P `AC5` |
| TC-5-3 | AC5 | automated | timed stand-in stream | `aria-busy`, button disabled, Enter does nothing while answering, grows, settles | F `AC5 TC-5-3` |
| TC-5-4 | AC5 | automated | leave the page mid-answer | connection closed | F `AC5 TC-5-4` |
| TC-5-6 | AC5 | automated | headers of the stream | `Cache-Control: no-store` via the admin origin; `X-Accel-Buffering: no` on the API port (nginx consumes it) | F `AC5 TC-5-6` |
| TC-6-1 | AC6 | automated `@slow` | UI: Anonymous on `Handbook`; Public as Anonymous; `Managers` without / with `managers` | no passages / passages as expected | S `AC6` |
| TC-6-2 | AC6 | automated `@slow` | access matrix through the API (levels, groups case-insensitive, no partial match) | the principal in the body decides | S `AC6 TC-6-2` |
| TC-6-3 | AC6 | automated | Ask as / Groups behaviour and request body | Groups hidden for Anonymous and never sent; commas split | F `AC6 TC-6-3` |
| TC-6-4 | AC6 | automated | invalid principals incl. missing principal | 422 `invalid_request` | F `AC6 TC-6-4` |
| TC-6-5 / 6-6 | AC6 | automated | bad group names; groups optional, 21 and 100 names accepted, 101 → `invalid_group`, more than 100 items → `invalid_group` even when they dedupe to ≤ 100 | as listed | F `AC6 TC-6-5`, `TC-6-6` |
| TC-6-7 | AC6 | exploratory | change the access level of a collection between two asks | the next ask reflects it | not run in this ticket |
| TC-7-1 | AC7 | automated | stand-in: 503, error frames, 500, 502 HTML, network | friendly alert, no technical text, partial answer removed, passages stay | F `AC7 TC-7-1` |
| TC-7-2 | AC7 | automated `@slow` | stop the chat model, ask | `passages`, then `error {"code":"model_unavailable"}`; UI alert | S `AC7` |
| TC-7-3 | AC7 | automated `@slow` | stop both model services | 503 `model_unavailable`; 422 and 403 still win | S `AC7 TC-7-3` |
| TC-7-4 | AC7 | automated `@slow` | after restart | normal answer | S `AC7 TC-7-4` |
| TC-7-6 / 7-7 | AC7 | automated | 403, 404, `invalid_group` in the UI (message: "…at most 100 groups."); real expired session | existing messages; sign-in page | F `AC7 TC-7-6`, `TC-7-7` |
| TC-8-1 | AC8 | automated | Restricted collection page | panel texts, controls, order, artboard styles | F `AC8` |
| TC-8-2 | AC8 | automated | browser language `vi-VN` | console stays English (no switch); answer texts follow the question | F `AC8 TC-8-2` |
| TC-8-3 / 8-4 | AC8 | automated | keyboard; answer, citation and row styles | as the artboard | F `AC8 TC-8-3`, `TC-8-4` |
| TC-8-5 | AC8 | exploratory | X2 | computed styles of the artboard and of the live panel | X `X2` |
| TC-N-1 | NFR | automated `@slow` | 3 asks | no table changes its row count; exactly one `answer_done` line per ask with `outcome=`, `rule=`, `passages=`, `cited=` | S `NFR TC-N-1` |
| TC-A-1 | attack | automated | other Organization, other Workspace, deleted, random id | identical 404 `not_found` | F `Attack TC-A-1` |
| TC-A-3 / A-8 / A-13 | attack | automated | identity fields; question limits; order of checks | 422; 403 before body; 422 before 404 | F `Attack TC-A-3`, `TC-A-8`, `TC-A-13` |
| TC-A-5 / A-7 / A-12 | attack | automated | no session; no CSRF; rejected requests leave no trace | 401; 403; no `answer_done`, no rows | F `Attack TC-A-5`, `TC-A-7`, `TC-A-12` |
| TC-A-9 | attack | automated `@slow` | secrets in the question and in a retrieved document | not in logs or in the passages frame | S `Attack TC-A-9` |
| TC-A-11 | attack | automated `@slow` | "ignore all previous instructions" in a document | normal answer with citations, not "PWNED" | S `Attack TC-A-11` |

## Exploratory flows (script X, or by hand in the browser)

The Chrome DevTools tools were not available in the QA session of EA-37, so the flows are automated in `EA-37-ask-collection-explore.spec.ts`; a person can follow the same steps.

1. **X1 happy path.** Sign in as Thao, open Knowledge → a collection holding `Leave Policy 2026.md`. Scroll to "Ask this collection". Ask "Kết hôn được nghỉ mấy ngày?" with Enter, then "How many days of paid leave do I get when I marry?" with the Ask button. Check: the answer streams in, `[1]` is teal, the row of §4.1 is numbered `[1]`, the other rows have no number, Tab from the input reaches Ask with a visible focus ring.
2. **X2 artboard.** Open `docs/design/canvas/CollectionDetail.dc.html` next to the live panel at 1440 px with the same content. Compare heading, helper, input + Ask on one row, grey answer box, "Passages found", number column, source, mono score, uncited rows in the secondary colour.
3. **X3 console and network.** Open DevTools on the collection page, ask once. Check: no console error or warning; the ask request is a POST to `/api/workspaces/<ws>/collections/<col>/ask` on the admin origin only, body only `question` and `principal`, an `X-CSRF-Token` header, response `text/event-stream` with `Cache-Control: no-store`; `passages` arrives within about 100 ms and the first text before the end; no other request over 1 s.
4. **X4 performance.** Record a trace while asking: LCP of the page, no long task while the answer grows, event duration of the Ask click.
5. **X5 input.** In the question input: compose a Vietnamese word with an IME and press Enter (nothing is sent); paste 3 000 characters (limit 2 000); double-click Ask; hold Enter while an answer runs (one request).
6. **X6 state changes.** While an answer runs change Ask as; leave to another collection and come back (panel empty); open two tabs and ask in both; reload.
7. **X7 roles.** Sign in as Son (Viewer) and Ha (Reviewer), open the collection URL: the "No access" page, no panel.
8. **X8 responsive.** Widths 1440, 1024, 768, 375 and a 200 % zoom with a long document name and a long answer: no horizontal scroll, controls 44 px high.
9. **X9 model dies mid-answer.** Ask a broad question, run `docker compose stop model` after the first words: friendly alert, no answer box, passages stay; `docker compose start model`, wait until healthy, ask again.

## Data hygiene check

`node e2e/knowledge/scripts/EA-37-ask-collection-hygiene.mjs > before.txt` before a run and `... before.txt` after: the row count of every table must be unchanged and no row may carry `qa-ea37`. The only expected difference are the sign-ins of the run (`admin_sessions`, audit `user.signed_in`); remove those created since the start of the run with SQL as the database superuser.
