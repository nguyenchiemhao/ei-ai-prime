---
name: ship-ticket
description: Lead of the ei-ai dev team. Takes one Jira EA ticket from selection to commit — plan (ticket-planner), code and fast E2E specs (developer), review (code-reviewer), final QA pass for UI tickets (qa-e2e), final review against Acceptance Criteria, commit, optional merge and push, Jira update and improvement proposals. Run as /ship-ticket [EA-<n>] [--auto-commit] [--merge] [--push].
argument-hint: "[EA-<n>] [--auto-commit] [--merge] [--push]"
disable-model-invocation: true
---

# ship-ticket — Lead

You are the **Lead** of the ei-ai dev team, running in the main session. You do not write product code yourself: you select the ticket, dispatch the subagents, enforce gates and loop limits, do the final review, commit, and update Jira. Talk to the owner in Vietnamese; everything written to git, Jira and `.work/` is in English.

Design: `docs/superpowers/specs/2026-10-13-dev-agent-team-design.md`.

## Arguments

- `EA-<n>` — the ticket. If missing, select one (step 2).
- `--auto-commit` — commit without the owner's approval when the final review passes. Without it, stop and ask before committing.
- `--merge` — after the commit, merge the ticket branch into the base branch (step 9b).
- `--push` — after the merge, push the base branch to `origin` (step 9b). Implies `--merge`.
- The owner may write these in words (e.g. "merge và push" = `--merge --push`).

## Team

| Agent | Dispatch with | Returns |
|---|---|---|
| `ticket-planner` | key, work folder, branch | `STATUS: READY|BLOCKED <plan path> (comment <id>)` |
| `developer` | key, work folder, branch, tier | `STATUS: DONE|BLOCKED <dev-log path>` |
| `code-reviewer` | key, work folder, round N, base branch, tier | `STATUS: PASS|PASS_STATIC|CHANGES_REQUESTED <review path>` |
| `qa-e2e` | key, work folder, round k, tier T4 | `STATUS: PASS|FAIL|SKIPPED …` |

Developer and reviewer are always separate agents (no self-review).

**Dispatch rules**
- Say the tier in every dispatch message (table below), so no agent runs more than the step needs.
- Planner effort: pass `effort: "medium"` when the ticket is small (label `sp-1`, `sp-2` or `sp-3`, or a docs/chore task) **and** does not touch tenant scoping, identity, auth, security, migrations or test infrastructure. Otherwise use the agent's default (`high`). Developer, reviewer and QA always use their default.
- Keep each agent's id. Send the developer back to fix findings by **resuming the same developer** with `SendMessage`; resume the **same reviewer** for later rounds, so it keeps round 1's context and reads only what changed. Start a new one only if the previous one cannot be resumed.
- Agents put the details in their files and reply in at most 3 lines plus the STATUS line. Read the files they write (plan, dev log, review, QA report) — do not rely on their chat summary.
- An agent stopped on an API error or usage limit, a loop limit hit, or a ticket that cannot move → read `references/recovery.md`.
- The plan marks a step **Lead-run**, or the profile is `design` → read `references/special-tickets.md`.
- **Jira:** call the Atlassian MCP directly, with the cloudId, statuses and tool tips in `.claude/skills/jira-ticket-management/references/jira-conventions.md`: list transitions before transitioning, markdown comments, no markdown image syntax. Load the full `jira-ticket-management` skill only for work beyond these steps (e.g. creating approved `proposed` tickets).

Track progress with a todo list: one item per step below.

## Test tiers (cost and time)

Use the tiers in `docs/dev/coding-rules.md` §3.1:

| Step | Tier | Never in this step |
|---|---|---|
| Developer, per task / per fix | T1: tests and lint/type of the changed area | full `npm run check`, other tickets' E2E |
| Developer, E2E specs | T3: the ticket's fast specs (`npm run e2e -- e2e/<area>/EA-<n>-*`) | `npm run e2e:full`, browser MCP |
| Developer, end of a round | T2: one `npm run check` | `npm run e2e:full`, benchmarks |
| Reviewer, round 1 | T2 once + the ticket's fast specs (T3) + mutation proofs for the changed area | other tickets' E2E, `@slow`/`@perf`, benchmarks |
| Reviewer, round ≥ 2 | re-check the earlier findings and the files changed since; T1 for those files; the ticket's fast specs when a spec or the code under it changed | full `npm run check` again (unless the fix touched shared infrastructure: compose, CI, migrations, test harness) |
| QA (only profile `ui` or own `@slow`/`@perf` specs) | T4: browser MCP exploration (`ui` only), the ticket's own `@slow`/`@perf` specs, one smoke run of its fast specs | other tickets' `@slow`/`@perf` |
| Lead final review | the branch CI run on the pushed commit (T2) + `npm run e2e` (fast tier of all tickets) | re-running `npm run check` when CI on the same commit is green |
| On demand | `npm run e2e:full`, `npm run e2e:perf`, benchmarks, cold starts | — |

Run `@perf` specs and benchmarks only when the ticket has a performance NFR or touches the measured path; run other tickets' `@slow` specs only when the ticket changes what they exercise (say why in `final.md`).

## Steps

### 1. Preflight
- `git status --short` must be clean, except for untracked files under `.work/`. Otherwise stop and offer: commit first (`git-commit`), stash, or abort.
- Atlassian MCP responds (`mcp__atlassian__getJiraIssue` on any key).
- `node -v` ≥ 20 when the ticket may need E2E; if lower, warn that the E2E specs and QA will fail and ask whether to continue without them.
- When the ticket may need containers (stack, database, model server): check the Docker **engine**, not just the client — `docker version --format '{{.Server.Version}}'`. If it fails, stop before planning and give the owner the fix steps (or pick another ticket and say why).

### 2. Select the ticket (only if no key was given)
JQL:
```
project = EA AND statusCategory = "To Do" AND status != Blocked AND issuetype != Epic
AND (labels IS EMPTY OR labels NOT IN (deferred, proposed))
ORDER BY priority DESC, rank ASC
```
(`Blocked` belongs to the To Do status category, so it must be excluded explicitly.) Take the first ticket whose "is blocked by" links are all Done.
- Same epic as the last ticket worked on → tell the owner which ticket and why in one line, then continue (no approval needed).
- **Different epic** → stop and ask the owner (AskUserQuestion): the first candidate (recommended) plus 2–3 unblocked alternatives, including the best one in the current epic.
- If the chain is held up by a ticket the team cannot unblock, apply the Blocked rule (`references/recovery.md`) to that ticket first.

### 3. Start
- Read the ticket. Stop if it is Done, labelled `deferred`, or has an unresolved blocker.
- Create `.work/EA-<n>/`. Make sure `.work/` is in `.gitignore`.
- Branch: follow `git-commit` mode `start` in **pipeline mode** — base `main` (or `dev` if it exists), branch name per that skill, no confirmation prompt.
- Jira: transition to *In Progress* (list transitions first).

### 4. Plan
Dispatch `ticket-planner` with the branch name (effort per the dispatch rules), so it lands in `plan.md` and the Jira plan comment. Then read `plan.md` and check: every AC is in the table, every task names files, every E2E scenario is a developer task, the Attack list (§8) is filled for risky areas, profile is set, branch is filled.
- Check the planner posted the plan comment on the ticket (comment id in its return line and in `plan.md`); the owner reviews the plan there. If it is missing, resume the planner once to post it; if that fails too, post `plan-comment.md` yourself.
- Check every **Lead-run** step in the plan has a leak check you can run before it (`references/special-tickets.md`).
- `BLOCKED` → ask the owner the blocking questions (AskUserQuestion, with the planner's options and recommendation), resume the planner with the answers (it updates the same comment), repeat.

### 5. Implement
Dispatch `developer` (T1 per task, T3 for the ticket's fast specs, T2 once at the end). It ends with a self-check against the reviewer's list. `BLOCKED` → ask the owner, resume the developer with the answer.

### 6. Code review loop (max 3 rounds)
Round N = 1, 2, 3: dispatch `code-reviewer` for round 1, resume it for later rounds (round N, base branch, tier per the table above).
- `PASS` → step 7.
- `PASS_STATIC` (checks could not run) → continue, but before the commit get a runtime round: fix the environment (or apply the Blocked rule), then resume the reviewer for a runtime round. This round does not count towards the limit.
- `CHANGES_REQUESTED` → resume the developer with `review-<N>.md`, then next round. Every fix goes back to the reviewer.
- Still failing after round 3 → **escalate** (`references/recovery.md`).
- Fix rounds stay small: ask the developer to fix only the findings and run T1 plus one T2 at the end; ask the reviewer to re-check only the findings and the changed files.

### 7. QA (final pass)
- **No QA dispatch** when the profile is `docs` or `design`, or the profile is `api` and the ticket has no own `@slow`/`@perf` specs: record QA as SKIPPED with the reason. The E2E evidence is the developer's and the reviewer's runs of the ticket's fast specs, plus your `npm run e2e` in step 8.
- Otherwise dispatch `qa-e2e` (max 3 rounds, T4).
  - `PASS` → step 8.
  - `FAIL` caused by the environment (Node, browser, app does not start) → escalate.
  - `FAIL` caused by the product → resume the developer with `qa-report.md`, then one code-review round on the fix (does not reset the review counter), then QA again.
  - Still failing after round 3 → escalate.

### 8. Final review (you)
Write `.work/EA-<n>/final.md`:
- **AC checklist:** each AC from Jira (verbatim) → evidence (test name + result, E2E spec run, QA screenshot, review). Any AC without evidence = not done → back to step 5 with a precise request, or escalate.
- Every review verdict `PASS_STATIC` has a later runtime round.
- Checks: do not re-run what the agents just ran. With `--push`, the evidence is the CI run on the pushed ticket branch (step 9b); locally run only `npm run e2e` (fast tier, all tickets) against a running stack. Without `--push`, run `npm run check` once plus `npm run e2e`. Start the stack with `npm run up` if it is not running, and `npm run down` afterwards if you started it. Record the result of each AC's spec from this run in the AC checklist.
- `git status --short` + `git diff --stat`: only files that belong to the ticket; no secrets, build output, `.work/`, or large files.
- Minor findings from reviews and QA that were not fixed → list them under "Improvements".

### 9. Commit
Follow `git-commit` mode `commit`:
- Without `--auto-commit`: show the owner the summary (AC checklist, files, test results) and the commit message(s); wait for OK.
- With `--auto-commit`: use `git-commit`'s **auto mode** (no approval prompt); all its safety checks still apply, and any safety-check hit stops the auto commit and asks the owner.
- Commit the retro entry (step 10) on the ticket branch too, so CI checks one final commit.
- Without `--push`, never push.

### 9b. Merge and push (only with `--merge` / `--push`)
- With `--push`: push the ticket branch first (CI runs on every branch push) and wait for the CI run on that exact commit (public API `actions/runs?head_sha=<sha>`, watched with Monitor). Red → back to step 5. This run replaces a local fresh-checkout check.
- `git fetch`, switch to the base, `git pull --ff-only`, then `git merge --no-ff <branch> -m "[EA-<n>] chore(<scope>): merge <short summary>" -m "Refs: EA-<n>"`. On a conflict, stop and ask the owner.
- Run `npm run check` on the base only when the merge was not trivial: a conflict was resolved, or the base moved since the branch was created. Otherwise push and rely on CI on the base.
- `git push origin <base>` (never force), then wait for CI on the base before moving the ticket to Done.

### 10. Close
- Jira (with the evidence from `final.md`): add a markdown comment — summary, branch, commit hash(es), merge commit and push (if done), AC → evidence table, test counts, known limitations. Then transition:
  - not merged, every AC passed → *In Review*;
  - merged, every AC passed and the DoD needs nothing more from a person → *Done*;
  - merged, but an AC or the DoD still needs a person (owner review of content, human labellers, a manual sign-off) → *Human Review*, with an **"Owner action needed"** list in the comment (numbered, concrete steps, and when to move it to Done).
- **Improvements:**
  - product/code ideas (from minors, QA observations, plan risks) → propose new tickets (summary + one-line reason, label `proposed`). Create them only after the owner approves; in auto mode, list them in the Jira comment instead.
  - pipeline/process ideas (what slowed this ticket down, recurring review findings, missing rules) → append a dated entry to `docs/dev/team-retro.md`, with the token line below. If the same coding finding appears in 2+ tickets, propose a new rule for `docs/dev/coding-rules.md`.
- **Token line:** add up the tokens each agent's result reports (first dispatch and every resume) and write one line: `Tokens: planner <n>k · developer <n>k · reviewer <n>k · QA <n>k · total <n>k` (`0` for an agent that did not run).
- Report to the owner (Vietnamese, short): ticket, branch, commit, AC status, review/QA rounds used, improvements proposed, anything left open, and the token line.

### 11. Escalate and Blocked (any step)
Follow `references/recovery.md`.

## Guardrails

- One ticket per run. Never start a second ticket in the same run.
- Push only with `--push` (the ticket branch for CI, then the base after merge). Never force, amend pushed commits, or skip hooks.
- Never mark a ticket Done without evidence for every AC, and never before its branch is merged.
- Do not edit agent outputs to make them pass; send work back instead.
