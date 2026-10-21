# EA-32 [KB-01] Collections and Folders with 3 access levels and "Local model only"

Black-box QA from the ticket and its test contract. Admin UI in English.

## Purpose and preconditions

- Create, edit, search and delete Collections; Folders nested 1-3 levels; three access levels (Public, Authenticated, Restricted by groups) with badges that always carry text; the "Local model only" flag; audit of access, groups, flag and deletes.
- Rules under test: only a Workspace Admin changes who can read a collection, creates a Public one or switches local-only off; everything is scoped by Organization and Workspace (foreign ids answer an identical 404); names, subtitles and groups never appear in errors, audit values or logs.
- Stack: `npm run up -- --no-model`, then `npm run seed`. Admin URL `http://localhost:<ADMIN_PORT>` (3100 in this repo's `.env`), API under `/api`.
- Test data: every spec creates its own Workspaces (`QA22 qa-EA32-<run> ...`), users (`qa22.qa-ea32-<run>.<label>@mekongdevworks.example`) and a second Organization; collection names carry `qa-EA32-<run>` (exception: "Employee Handbook" in an empty own Workspace, as AC1 says). People Ops seed rows are only read. Teardown removes everything; `afterAll` compares row counts of `collections`, `folders` and collection/folder audit events with the counts before the run and checks that no row holds the marker.
- Do not run two QA specs of different tickets at once, and do not run a spec while exploring in the browser: `cleanup()` of `e2e/support/ea22.ts` removes every `qa22.*` user and `QA22 *` Workspace.

## How to run

```
npm run e2e -- e2e/knowledge/EA-32-collections.spec.ts           # fast tier, 34 tests, about 1.5 min
npm run e2e:perf -- e2e/knowledge/EA-32-collections-perf.spec.ts  # @perf, NFR 100 collections <= 1 s
node e2e/knowledge/scripts/EA-32-collections-explore-data.mjs setup     # accounts for the exploratory flows (prints JSON)
node e2e/knowledge/scripts/EA-32-collections-explore-data.mjs bulk <email> <password> <workspaceId> 100
node e2e/knowledge/scripts/EA-32-collections-explore-data.mjs cleanup   # removes everything setup/bulk created
```

The specs are serial (shared state); the first failure skips the rest, so known failures that should not hide others are collected and asserted in the last test (TC-A11Y-1).

## Cases

| TC | AC | Type | Steps | Expected | Spec or script |
|---|---|---|---|---|---|
| TC-1-1 | AC1 | automated | KE: empty Workspace, New collection, "Employee Handbook", Authenticated, Create | 201; row with Authenticated badge, 0 documents, "No documents"; audit created NULL to authenticated | spec `AC1:` |
| TC-1-2 | AC1 | automated | API: normalisation (trim, subtitle null, groups NFC/lower/dedupe), ordering, 200-char limits | item shape, ordered by name ignoring case | `AC1 TC-1-2` |
| TC-1-3 | AC1 | automated | API: 19 invalid bodies (incl. control characters in name/subtitle), duplicates (case-insensitive), same name in another Workspace | 422 `invalid_request` with no echo; 409 `name_taken`; 201 elsewhere | `AC1 TC-1-3` |
| TC-1-4 | AC1 | automated | UI: Escape/Cancel, helper texts, empty name, duplicate, markup name, Vietnamese name and subtitle | nothing sent on cancel; alert on duplicate; text shown literally | `AC1 TC-1-4` |
| TC-1-5..7 | AC1 | exploratory | Double submit, 200-char texts, keyboard flow of the dialog (flows 1-2 below) | one collection, layout holds, Tab order and trap, Escape returns focus to the trigger | flows below |
| TC-2-1..3 | AC2 | automated | Restricted without groups (UI and API), group validation, invalid-group message | `groups-error` "At least one group is required" (announced, focus on Groups), no request; 422 `groups_required` / `invalid_group` | `AC2:`, `AC2 TC-2-2`, `AC2 TC-2-3` |
| TC-3-1, 3-2 | AC3 | automated | KE/Builder cannot change access (UI disabled + note, API 403); admin can; audit old to new; groups_changed; no event on same value | 403 `forbidden`; badge "Restricted · managers"; audit rows as in the contract | `AC3:`, `AC3 TC-3-2` |
| TC-4-1, 4-2 | AC4 | automated | Public needs the confirmation (change and create); Cancel sends nothing; KE cannot choose Public | `confirm-public-dialog` before any request; audit; 403 for KE/Builder | `AC4:`, `AC4 TC-4-2` |
| TC-4-3 | AC4 | exploratory | Confirmation dialog by keyboard | Focus on Cancel, trapped, Escape closes the confirmation only | flow 2 |
| TC-5-1 | AC5 | automated | Local model only on create, KE cannot switch off, admin can, anyone switches on; audit | Data handling "Local model only"; 403; audit `local_only_changed` | `AC5:` |
| TC-6-1, 6-2 | AC6 | automated | Typed-name delete, wrong values keep the button disabled, Escape, exact name deletes; after 204 collection and folders gone; audit | 204; "<name> was deleted."; detail 404; no rows left; audit `collection.deleted` | `AC6:`, `AC6 TC-6-2` |
| TC-7-1 | AC7 | automated | Workspace with no collections | empty state, exactly one New collection, legend and footnote kept | `AC7:` |
| TC-8-1..3 | AC8 | automated | Seeded People Ops list, search with diacritics, detail page structure | headers, legend, 6 seed rows, badges with text and contrast, footnote | `AC8:`, `AC8 TC-8-2`, `AC8 TC-8-3` |
| TC-8-4, 8-5 | AC8, NFR | exploratory | Compare list with `docs/design/canvas/Collections.dc.html`; grayscale screenshot | see qa-report round 1 | flow 1 |
| TC-F-1, F-2 | scope | automated | Folders UI (3 levels, rename, delete rules) and API (depth, duplicates, 404s, audit) | as in the contract | `Folders TC-F-1`, `Folders TC-F-2` |
| TC-8-4 (auto) | AC8 | automated | Legend as three bordered cards in one row, accent-colour links (list and breadcrumb), full-width search, muted "Any allowed model" | as the artboard | `AC8 TC-8-4` |
| TC-Q1-2/3 | AC1, AC4, AC6 | automated | Escape (and Cancel) returns focus to the opener in every dialog; after a 409 the folder delete dialog keeps Escape and its Tab trap; Public confirmation Escape/Cancel keeps focus in the form | focus on the opener / inside the dialog | `Q1-2 / Q1-3` |
| TC-6-3 | AC5, AC6 | automated | Save settings, change access, delete or add a folder on a collection that was deleted elsewhere | Not found page, no generic error | `AC6 TC-6-3 / AC5` |
| TC-A11Y-1 | NFR (DSN-01) | automated | Folder action buttons are at least 24 x 24 px | no button smaller | `TC-A11Y-1` |
| TC-ROLE-1, 2 | roles | automated | Viewer gets No access; unknown, foreign Workspace and foreign Organization ids give the same Not found page | identical pages | `TC-ROLE-1`, `TC-ROLE-2` |
| ATTACK-1..7 | attack list | automated | 401 everywhere; Viewer 403; foreign ids 404 identical; role attacks leave nothing; mass assignment and `?org_id`; no leaks into errors, audit, logs; group case | as in the contract | `ATTACK-1` ... `ATTACK-7` |
| TC-NET-1 | all | automated | Console, failed requests, identity query parameters, slow requests | clean | `TC-NET-1` |
| TC-NFR-1, 2 | NFR | automated @perf | 100 collections: list API and screen to the 100th row | median <= 1000 ms (measured 52-59 ms API, 123-242 ms screen) | perf spec |
| TC-NFR-3 | NFR | exploratory | DevTools trace of the 100-row list; typing in search | LCP 142 ms, CLS 0.02; 11-16 ms per keystroke | flow 3 |

## Exploratory flows (numbered, for a person)

Setup: run the `setup` script and sign in with the printed admin (and editor) account; the script also made an empty Workspace "QA22 qa-EA32-... Explore". Cleanup at the end.

1. Visual comparison. As the admin open People Ops, Knowledge, at 1440 x 900. Open `docs/design/canvas/Collections.dc.html` in a second tab at the same size. Compare header, legend, search, six columns, badges, local-model chip, footnote. Then apply `document.documentElement.style.filter = "grayscale(1)"` and check that every badge is still readable from its text. Record deviations.
2. Dialogs by keyboard. In the Explore Workspace open New collection with the mouse; press Tab five times (Subtitle, access radios, Local model only, Cancel, Create) and once more (focus must return to Name); press Escape (dialog closes; focus should return to "New collection"). Create a collection, open its detail, add folder "Quy trình", add subfolder "2026", delete the parent (expect "Delete its subfolders first."; the dialog must still close with Escape and keep focus inside). Choose Public in a new collection and press Create: the confirmation opens with focus on Cancel; Tab stays inside; Escape returns to the form without saving.
3. Performance. Run `bulk` for 100 collections; in DevTools record a trace with reload on the Explore Knowledge list (LCP, CLS) and type "bulk 042" into the search box while timing each key (target well under 200 ms).
4. Responsive. Resize to 1280, 1024 and 768 px on the list and the detail page: the table scrolls inside its card, dialogs fit.
5. Console and network. On list and detail check the console (no errors) and the request list (no 4xx/5xx, nothing above 1 s, no `user_id`, `org_id`, `workspace_id`, `groups` or `role` parameters).
6. Cleanup: run the `cleanup` script and check it prints "no row with the marker is left".

Tool note: the DevTools `fill` tool can set a long value without the page noticing; type long values with `type_text` instead.
