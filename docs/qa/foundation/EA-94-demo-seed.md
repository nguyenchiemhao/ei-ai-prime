# EA-94 [FND-14] Realistic demo seed, shared test password, test-accounts README

Black-box QA from the ticket and its test contract. Profile: api + CLI + docs (no new screen; sign-in uses the existing admin UI).

## Purpose and preconditions

- `npm run seed` creates two fictional Organizations (Mekong Devworks with People Ops and Engineering, Sông Hàn Retail with Customer Care), 12 users in 11 sign-in accounts (the sysadmin is a member of both Organizations; only the Mekong membership has a password), 9 collections with 36 folders, and gives every seeded account one shared test password.
- Rules under test: every account signs in with the shared password and lands on its default Workspace without a set-password link; a user who sets a password still needs 12 characters; roles (Org Owner, Org Admin, six Workspace roles, one person with different roles in two Workspaces); folders as on the CollectionDetail artboard, no placeholder text; tenant isolation between the two Organizations; idempotent seed that never overwrites a changed password; non-local environments refused (exit 2); the password never printed or stored in plain text; `docs/dev/seed-data.md` agrees with the manifests (check `scripts/checks/seed-data.test.mjs`).
- Stack: `npm run up -- --no-model`, then `npm run seed`. Admin URL `http://localhost:<ADMIN_PORT>` (3100 in this repo's `.env`), API under `/api`. Optional for a clean start: `npm run reset` first (deletes the local database).
- The shared password is the value of `EI_AI_SEED_PASSWORD` (shell, then `.env`, then the default in `.env.example`). Specs and scripts read it from there; it is not written in this file.
- Test data: the fast spec purges both demo Organizations once (fresh-database scenario) and re-seeds them, so the developer's demo is re-created by the run (the ids of the Workspaces change). Accounts it creates itself are `qa22.qa-ea94-<label>.<run>@mekongdevworks.example` and are deleted afterwards. A scenario that changes or deletes a seeded credential saves the whole `user_credentials` row and restores it exactly, and deletes only the audit rows it caused. At the end the spec proves both Organizations are back to the seeded row counts, sign-in sessions and `user.signed_in`/`user.signed_out` events are removed, rows outside the demo are unchanged, and no row carries the `qa-ea94-` marker.
- Do not run two QA specs of different tickets at once: `cleanup()` of `e2e/support/ea22.ts` removes every `qa22.*` user and `QA22 *` Workspace. Never send more than 4 wrong passwords in a row to a seeded account (5 lock it).

## How to run

```
npm run e2e -- e2e/foundation/EA-94-demo-seed.spec.ts          # fast tier, 23 tests, about 1.7 min (sign-ins are paced by the rate-limit budget)
npm run e2e:perf -- e2e/foundation/EA-94-seed-perf.spec.ts      # @perf, NFR: fresh seed <= 10 s
node --test scripts/checks/seed-data.test.mjs                   # README check (SEED_README_FILE=<copy> to try a mutated copy)
node e2e/foundation/scripts/EA-94-demo-seed-explore.mjs         # exploratory flow EX-1/EX-2 as a script (prints what each account sees, saves screenshots)
node e2e/foundation/scripts/EA-94-demo-seed-check-state.mjs     # read-only SQL check of both Organizations against the contract counts
```

## Cases

| TC | AC | Type | Steps | Expected | Spec or script |
|---|---|---|---|---|---|
| TC-1-1 | AC1 | automated | Purge both Organizations, `npm run seed`; sign in over the API with all 11 accounts and the shared password; read the session | 200 `{"default_workspace_id"}` of the landing Workspace; session user, Organization, org role right; no `set_password_tokens`; no `#token=` or `set-password` in the output | `AC1:` |
| TC-1-2 | AC1 | automated | Wrong password for Linh Tran; unknown email | Both 401 `invalid_credentials`, same body, no cookie | `AC1 TC-1-2` |
| TC-1-3 | AC1 | automated + exploratory EX-1 | UI sign-in ("Work email", "Password", "Sign in") for Linh Tran, Duy Lâm, Vy Huỳnh, the sysadmin, Ngân Trịnh | URL `/w/<landing>/dashboard`, H1 Dashboard, no set-password text, no unexpected console error | `AC1 TC-1-3`, explore script |
| TC-1-4 | AC1 | automated | Invite a user; sign in with the shared password; set-password with the 8-character shared value, an 11-character value, then 12 characters | 401; 422 `password_too_short` twice; 204 and sign-in works | `AC1 TC-1-4` |
| TC-1-5 | AC1 | automated | Compare the fresh `npm run seed` output (UUIDs masked), stderr, exit code, row counts and audit actions with the contract | Identical text, exit 0, empty stderr, counts of both Organizations, 11 `$argon2id$` credentials | `AC1 TC-1-5` |
| TC-1-6 | AC1 | exploratory EX-6 | On a database seeded before EA-94 run the new seed | Adds Engineering, people, collections, folders, Sông Hàn, passwords; existing rows unchanged | manual |
| TC-2-1 | AC2 | automated | SQL: org roles and Workspace roles per email | Exactly the documented roles; sysadmin `org_owner` + `workspace_admin` in three Workspaces; Quang Le `developer` / `workspace_admin`; no stored `platform_admin` | `AC2:` |
| TC-2-2 | AC2 | automated | Per account: session Workspaces and roles, `GET /api/workspaces/<id>` | Roles and permissions follow the EA-23 matrix; a Workspace without a role is 403/404 | `AC2 TC-2-2` |
| TC-2-3 | AC2 | exploratory EX-2 | Sidebar and user menu per account | Areas per EA-23 persona; user menu shows name and role | explore script |
| TC-3-1 | AC3 | automated | Collections and detail API per Workspace; SQL folder counts; placeholder regex | 9 collections with the listed attributes, 36 folders, one at depth 3, nested folders present, no `test`/`foo`/`lorem` | `AC3:` |
| TC-3-2 | AC3 | automated | Read Vietnamese names | Stored and returned unchanged | `AC3 TC-3-2` |
| TC-3-3 | AC3 | automated + exploratory EX-3 | Open Employee Handbook as the sysadmin / Linh Tran | 14 folder rows (Policies, Benefits, Onboarding & offboarding, Templates and children) | `AC3 TC-3-3` |
| TC-4-1..3 | AC4 | automated + exploratory EX-4 | Mekong accounts: session, `/api/organization`, foreign Workspace/collection ids, Workspace and Organization switchers; Ngân Trịnh the reverse | Own Organization only, foreign ids 404 `not_found`, no foreign names in bodies or pages, no identity parameters | `AC4:` |
| TC-4-4 | AC4 | automated | Sysadmin: Songhan membership has no credential; delete and restore the Mekong credential; sign in | 401 without the Mekong credential, never Sông Hàn; restore exact | `AC4 TC-4-2` |
| TC-5-1 | AC5 | automated | `npm run seed` twice more | Same output, 17 `already present` lines, `Audit events written: 0`, no row changes | `AC5:` |
| TC-5-2 | AC5 | automated | Change Son Hoang's password through set-password, seed, sign in | Hash kept, new password works, shared one fails; restored | `AC5 TC-5-2` |
| TC-5-3 | AC5 | automated | Delete Phúc Lương's credential, seed | `applied to 1 of 10`, only that credential created, others unchanged; restored | `AC5 TC-5-3` |
| TC-5-4 | AC5 | automated | Seed with an invited non-manifest user | No credential for that user, nothing written | `AC5 TC-5-4` |
| TC-5-5 | AC5 | automated | `EI_AI_ENV` production/staging/empty/Production (password set, empty, 200 chars); local and test | Exit 2, stderr `refused: ...`, nothing written; local/test run | `AC5 TC-5-5` |
| TC-5-6 | AC5 | automated | Empty, 129 and 128 character password | Exit 1 with the two documented messages and no echo; 128 accepted | `AC5 TC-5-6` |
| TC-5-7 | AC5 | exploratory EX-5 | `npm run reset && npm run up && npm run seed` | Fresh output; demo works | manual |
| TC-6-1 | AC6 | automated | Search all seed outputs, api/admin logs and tenant rows for the password; read hashes | Absent everywhere; `$argon2id$`, distinct, same parameters as a user-set hash | `AC6:` |
| TC-6-2 | AC6 | automated | `.env.example` default; `git grep` product files; `.env` untracked | One assignment, shorter than 12, no hard-coded value | `AC6 TC-6-2` |
| TC-7-1 | AC7 | automated | Parse `docs/dev/seed-data.md` | Every Organization, Workspace, account, collection and folder as seeded; sections present; root README link | `AC7:` |
| TC-7-2 | AC7 | automated | `node --test scripts/checks/seed-data.test.mjs` on the real README and on copies with a changed role, a missing account, a missing/extra folder, a renamed collection | Exit 0; each copy fails and names the row | `AC7 TC-7-2` |
| TC-7-3 | AC7 | automated | Config, `npm test` script, CI | The check is part of `npm test` and CI | `AC7 TC-7-3` |
| TC-7-4 | AC7 | exploratory EX-7 | Follow the README as a newcomer | Documented accounts sign in and match "What it can do" | manual |
| TC-N-1 | NFR | automated `@perf` | Purge both Organizations, time `npm run seed`, then a repeat | <= 10 s each | `NFR:` |

## Exploratory flows (Chrome DevTools MCP or the script)

1. EX-1 sign-in per account: open `/sign-in`, fill "Work email" and "Password" with the shared password, click "Sign in". Expect the dashboard of the landing Workspace, no set-password page; a wrong password shows "Invalid email or password". Sign out between accounts.
2. EX-2 roles: for each account read the sidebar and the user menu (Linh Tran, Duy Lâm, Trung Võ and Ngân Trịnh see Organization; Minh Pham: build, deploy and members; Thao Nguyen and Phúc Lương: knowledge areas; Hà Vũ: conversations and unanswered; Son Hoang: dashboard and members; Quang Le: Developer in People Ops, Workspace Admin in Engineering after switching).
3. EX-3 folders: as Linh Tran open Knowledge, Employee Handbook; compare the 14 folders with the CollectionDetail artboard.
4. EX-4 isolation: open the Workspace and Organization switchers for the sysadmin (one Organization, two Workspaces); open another Organization's `/w/<id>/dashboard` by URL (expect "Page not found", no data); repeat as Ngân Trịnh.
5. EX-5 reset: `npm run reset && npm run up -- --no-model && npm run seed` (destroys the local database).
6. EX-6 upgrade: on a database seeded before EA-94 run `npm run seed` and compare with the upgrade rules.
7. EX-7 README: follow `docs/dev/seed-data.md` from the top.
