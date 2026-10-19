# Dev agent team — retro log

The Lead (`/ship-ticket`) appends one entry per ticket about the **pipeline itself**: what slowed it down, recurring review/QA findings, missing rules or tools. Product ideas go to Jira as `proposed` tickets instead.

Format:

```markdown
## YYYY-MM-DD — EA-<n>
- Rounds: review <N>, QA <k>; escalations: <none | where>
- Tokens: <the two lines printed by .claude/skills/ship-ticket/scripts/token-report.mjs>
- What went well:
- What slowed us down:
- Proposed change: <agent / skill / rule file> — <change>
```

When the same finding shows up in two or more tickets, propose a rule for `docs/dev/coding-rules.md`.

## 2026-10-13 — EA-11
- Rounds: review 2, QA 0; escalations: environment (Docker Desktop cannot start: AMD SVM off in BIOS, Virtual Machine Platform disabled, Docker Desktop 4.18 outdated). Ticket flagged Impediment, work committed as WIP.
- What went well: review round 1 caught a real tenant-isolation bug (tenant context set inside a savepoint leaks across nested blocks) and a pinning claim the PoC did not prove.
- What slowed us down: preflight checked `docker --version` (client only), not the engine, so the blocker surfaced after planning; all review was static.
- Proposed change: `.claude/skills/ship-ticket/SKILL.md` preflight — run `docker version --format '{{.Server.Version}}'` (engine) when the plan needs containers, and stop early with the fix steps if it fails.

## 2026-10-13 — EA-12
- Rounds: review 2, QA 0 (SKIPPED, profile docs); escalations: none.
- What went well: the test-first Node check with mutation proofs made the document reviewable; branch stacked on EA-11 so AC4 (ADR reference) could be met.
- What slowed us down: round 1 minors exposed blind spots in the check (non-commercial model licences, cross-table consistency, substring matching).
- Proposed change: `.claude/agents/code-reviewer.md` — for document tickets with a structural check, always try 3–4 mutations and report which stay green.

## 2026-10-13 — EA-85
- Rounds: review 0 (Lead reviewed directly), QA 0 (SKIPPED, profile docs); escalations: none.
- What went well: the planner's review plan was precise enough to finish without the developer; Node checks on the canvas files caught a section-numbering gap and short table cells.
- What slowed us down: subagents cannot write to claude.ai artifacts, so the first run kept edits in a local copy and the owner could not see progress on the canvas.
- Proposed change: `.claude/skills/ship-ticket/SKILL.md` — for design tickets on the claude.ai canvas, the Lead edits and publishes the canvas directly (no developer/reviewer subagents), publishes early, and mirrors the files to `docs/design/canvas/` in the same commit.

## 2026-10-14 — EA-16
- Rounds: review 3, QA 0 (SKIPPED, profile docs); cross-labelling runs 3 (2 superseded); escalations: none. One developer run stopped on an API rate limit and was resumed.
- What went well: the reviewer's mutation runs on scratch copies (tree checksummed before/after) found real gaps: an always-green README regex, a blind sheet whose row order leaked the group, and guide examples that gave away labels.
- What slowed us down: the developer cannot launch subagents, so the independent second labeller had to be run by the Lead between developer phases; two "blind" runs had to be redone because blindness was not checked before running them. The selection JQL also returns `Blocked` tickets (status category To Do).
- Proposed change: `.claude/agents/ticket-planner.md` — for any blind/independent human-or-LLM step, plan a leak check (no ids, ordering or examples that reveal labels) that must pass before the step runs, and assign the step to the Lead up front. `.claude/skills/ship-ticket/SKILL.md` step 2 — add `AND status != Blocked` to the selection JQL.

## 2026-10-14 — Retro changes applied
Applied after owner approval: EA-11 (Docker engine preflight), EA-12 (reviewer mutation proofs), EA-85 (design tickets on the canvas run by the Lead), EA-16 (Lead-run steps with a leak check first; selection JQL excludes `Blocked`), plus the owner's run rules: ask before picking a ticket from another epic, Blocked rule with an owner-action comment, `--merge` / `--push` arguments, *Human Review* when an AC or the DoD still needs a person, resume agents after API errors. Files: `.claude/skills/ship-ticket/SKILL.md`, `.claude/agents/ticket-planner.md`, `.claude/agents/code-reviewer.md`, `.claude/skills/jira-ticket-management/references/jira-conventions.md`.

## 2026-10-14 — EA-11 (resumed)
- Rounds: review 3 (round 3 = first runtime review), QA 1 (PASS, pytest in Docker); escalations: none this run (unblocked after the owner enabled virtualization and updated Docker Desktop).
- What went well: the opt-in model tests caught a real llama.cpp bug (router mode, no model loaded, `/health` still 200) that two static reviews had passed; reviewer mutations on a separate compose project proved the RLS tests bite.
- What slowed us down: review 2 was a PASS on static reading only, so the ticket looked review-complete while its riskiest part had never run. A Bash safety check rejected `docker compose run --rm poc sh -c "…"` as an unchecked `rm`.
- Proposed change: `.claude/agents/code-reviewer.md` — when the checks cannot run (environment down), the verdict is `PASS (static)` and the Lead must schedule a runtime round before commit. Lead/agents: run container commands without `sh -c` after `--rm` (one `run --rm poc <cmd>` per command).

## 2026-10-14 — EA-13
- Rounds: review 3 (R1 2 major), QA 2 (R1 FAIL on a README check broken by QA's own new e2e/ folder); escalations: none. The developer was cut once by the account session limit and resumed from its per-task dev-log checkpoints without loss.
- What went well: per-task checkpoints made the resume exact; reviewer mutations on scratch clones and throwaway Compose projects found a `reset` that could delete the main database and an `.env` merge bug before commit.
- What slowed us down: the Lead's turn ended with the rate-limited subagent and nothing re-armed it, so the run waited for the owner. A multi-path `git add` that included an already-deleted directory failed as a whole, and the following commit silently held only the pre-staged files (fixed by amending the unpushed commit).
- Proposed change: `.claude/skills/ship-ticket/SKILL.md` — when an agent stops on a rate limit that names a reset time, start a background wait until shortly after the reset and resume the same agent automatically. `.claude/skills/git-commit/SKILL.md` — check `git add` exit status and compare `git diff --cached --stat` with the intended file list before committing; stage deletions with `git add -A -- <path>` or `git rm`.

## 2026-10-14 — EA-18
- Rounds: review 2 (R1: 1 blocker, 2 majors), QA 1 (PASS); escalations: two owner decisions (NFR restated to an absolute budget; users belong to one Organization).
- What went well: the security review in round 1 found a real cross-tenant read (a membership in org A pointing at org B's user through a plain foreign key, which RLS does not check) and a schema guard that accepted widening policies; both were proven with attacks on a separate compose project and are now pinned by tests.
- What slowed us down: the plan accepted a platform-level table as a reasonable default for an open question, so the leak was only caught at review. A percentage NFR on millisecond queries could not be met and needed an owner decision mid-run.
- Proposed change: `docs/dev/coding-rules.md` §2 — no table without `org_id` and the standard policy unless the owner approves it after a security review; every foreign key to a tenant table includes `org_id`. `.claude/agents/ticket-planner.md` — any open question that would exempt a table from tenant isolation is BLOCKING, not an assumption. Write performance NFRs as absolute budgets (or relative only above a minimum duration).

## 2026-10-15 — EA-19
- Rounds: review 3 (R1 5 major, R2 1 major, R3 PASS), QA 1 (PASS); escalations: none. QA was cut once by the account session limit; it resumed from its logs after the owner said "continue" (the main session was limited too, so no background wait could run).
- What went well: the reviewer attacked the test suite itself with realistic leaks (org-less cache, header-trusting public route, read-B-write-A job, other-org Valkey writes) and each gap became a permanent leaky-probe self-test.
- What slowed us down: a first-draft isolation suite that checked only the obvious path needed two extra review rounds; the new EA-19 e2e spec builds scratch copies and made `npm run e2e` take about 10 minutes.
- Proposed change: `.claude/agents/ticket-planner.md` — for any test-infrastructure ticket ("suite X catches Y"), plan the leaky probes (one per leak kind) up front as acceptance evidence. `docs/dev/coding-rules.md` §3 — keep `npm run e2e` under ~3 minutes; slow scratch-copy specs go behind a separate tag.

## 2026-10-15 — Flow cost review (owner request)
- Trigger: the owner asked to cut cost and time; EA-19 was the reference run.
- Measured on EA-19:
  - `npm run e2e` ran every spec, 20 tests in 10.4 min; 6 copy the repository or re-run task suites and 1 is a benchmark.
  - `npm run check` (about 2 min) ran roughly ten times per ticket: each developer round, each review round, QA, the Lead's final review and again on `main` after the merge. Reviewers repeated the whole mutation set in every round.
  - Subagent tokens were about 1.1 M: planner ~0.19 M, developer ~0.44 M over 4 rounds, reviewer ~0.29 M over 3 rounds, QA ~0.16 M.
  - QA used browser MCP tools on an `api` ticket and ran the slow specs while fixes were still coming.
- Changes applied (owner decision 2026-10-15):
  - **Test tiers.** New `docs/dev/coding-rules.md` §3.1 defines five levels: T1 inner loop, T2 round gate, T3 fast E2E, T4 completion, and on demand.
  - **Tags and commands.** Playwright tags `@slow` and `@perf`. `npm run e2e` is now the fast tier: 13 tests in 23 s. `npm run e2e:full` runs everything and `npm run e2e:perf` only the `@perf` specs.
  - **QA modes.** `fast` runs every round with Playwright specs only. `final` runs once, after a fast PASS, and only for `ui` tickets or tickets with their own `@slow`/`@perf` specs; browser MCP exploration happens only there.
  - **Developer.** T1 per task and one `npm run check` per round.
  - **Reviewer.** Round 1 runs T2 and mutations on the changed areas. Later rounds re-check findings and changed files only; the full check reruns only when shared infrastructure changed.
  - **Lead.** Uses the CI run on the pushed ticket branch instead of a local full check and a fresh-checkout worktree. Locally it runs only `npm run e2e`. After a trivial merge it skips the local check on `main` and waits for CI on `main`.
  - **Planner.** Tags every E2E scenario with its tier and prefers unit/integration evidence.
- Expected effect per ticket:
  - Local full checks drop from about ten to three or four.
  - The Lead's E2E drops from about 10 min to about 0.5 min.
  - Browser MCP sessions run once, and only for `ui` tickets.
  - Review rounds after the first cost much less.
- Watch next tickets: whether a defect slips past fast QA and is only found in the final pass or on CI. If that happens, move that check up a tier.

## 2026-10-19 — EA-21 (first run of flow F)
- Rounds: verify 2 (round 1 review CHANGES_REQUESTED: 1 blocker, 1 major, 10 minor; QA run deferred because the fix changed the test contract; round 2 review PASS, QA PASS 21/21 + updated EA-13/EA-18 specs); escalations: none. Two owner decisions mid-run: free port 3000 by making the admin port configurable (`ADMIN_PORT`), and continue after the usage-limit reset.
- Tokens: lead 22.4M $5.71 · planner 4.4M $3.55 · developer 37.7M $14.09 · qa 8.6M $3.05 · reviewer 12.0M $4.69 · other 1.2M $0.70 · total 86.4M $31.78
  Rounds: planner R1 3.5M $1.97, R2 274k $0.76, R3 569k $0.82 · developer R1 20.8M $7.76, R2 6.7M $2.69, R3 281k $1.40, R4 9.9M $2.24 · qa R1 1.2M $0.75, R2 1.2M $0.27, R3 124k $0.31, R4 2.9M $0.66, R5 3.2M $1.06 · reviewer R1 8.2M $2.74, R2 3.9M $1.95 · other R1 1.2M $0.70
- What went well: the reviewer proved at runtime that the set-password secret in the query string landed in the admin nginx access log (blocker) and that the import guard missed relative imports; the fragment link fixed the log leak at the source. QA designed 23 black-box tests from the plan alone and found the contract gaps (missing-flag exit code, printed name, ADMIN_BASE_URL in production) before the code was finished; all were settled in the plan, so the developer and QA never diverged. `npm run e2e` stays under 3 minutes with 34 tests.
- What slowed us down: the claude.ai Atlassian connector tools are not available inside subagents, so the planner could not read the ticket or post its comment (the Lead did both). Port 3000 was held by another project's container. Both agents stopped on the account usage limit in the middle of round 2. The token report counted every agent as one round, because SendMessage resumes are written as meta lines (fixed in this ticket's chore commit).
- Cost: the real cost (~$31.8 API-equivalent) is about 4.5x the flow-F estimate (~$7). The developer on Opus was 44% of it (37.7M tokens over 4 rounds), driven by a 50 KB plan and 143 tool calls in round 1.
- Proposed change: `.claude/skills/ship-ticket/SKILL.md` — the Lead reads the Jira ticket and passes its text to the planner, and posts the plan comment itself (drop the Atlassian tools from the agents while the connector is not exposed to subagents). `.claude/agents/ticket-planner.md` — choose `Developer model: opus` only when a design decision is truly left open, and keep `plan.md` under ~25 KB (move long contract tables into a separate `contract.md` the developer reads on demand). Re-estimate flow F costs from the next two token reports before tuning further.
