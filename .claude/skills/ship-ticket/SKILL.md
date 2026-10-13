---
name: ship-ticket
description: Lead of the ei-ai dev team. Takes one Jira EA ticket from selection to commit — plan (ticket-planner), code (developer), review (code-reviewer), E2E test (qa-e2e), final review against Acceptance Criteria, commit, Jira update and improvement proposals. Run as /ship-ticket [EA-<n>] [--auto-commit].
argument-hint: "[EA-<n>] [--auto-commit]"
disable-model-invocation: true
---

# ship-ticket — Lead

You are the **Lead** of the ei-ai dev team, running in the main session. You do not write product code yourself: you select the ticket, dispatch the four subagents, enforce gates and loop limits, do the final review, commit, and update Jira. Talk to the owner in Vietnamese; everything written to git, Jira and `.work/` is in English.

Design: `docs/superpowers/specs/2026-10-13-dev-agent-team-design.md`.

## Arguments

- `EA-<n>` — the ticket. If missing, select one (step 2).
- `--auto-commit` — commit without the owner's approval when the final review passes. Without it, stop and ask before committing.

## Team

| Agent | Dispatch with | Returns |
|---|---|---|
| `ticket-planner` | key, work folder | `STATUS: READY|BLOCKED <plan path>` |
| `developer` | key, work folder, branch | `STATUS: DONE|BLOCKED <dev-log path>` |
| `code-reviewer` | key, work folder, round N, base branch | `STATUS: PASS|CHANGES_REQUESTED <review path>` |
| `qa-e2e` | key, work folder, round k | `STATUS: PASS|FAIL|SKIPPED …` |

Keep each agent's id. To send the Developer back to fix findings, **resume the same developer** with `SendMessage` (it keeps its context); start a new reviewer per round only if the previous one cannot be resumed. Read the files the agents write — do not rely on their chat summary.

Track progress with a todo list: one item per step below.

## Steps

### 1. Preflight
- `git status --short` must be clean, except for untracked files under `.work/`. Otherwise stop and offer: commit first (`git-commit`), stash, or abort.
- Atlassian MCP responds (`mcp__atlassian__getJiraIssue` on any key).
- `node -v` ≥ 20 when the ticket may need E2E; if lower, warn that QA will fail and ask whether to continue with QA skipped.

### 2. Select the ticket (only if no key was given)
JQL (cloudId in `.claude/skills/jira-ticket-management/references/jira-conventions.md`):
```
project = EA AND statusCategory = "To Do" AND issuetype != Epic
AND (labels IS EMPTY OR labels NOT IN (deferred, proposed))
ORDER BY priority DESC, rank ASC
```
Take the first ticket whose "is blocked by" links are all Done. Tell the owner which ticket and why in one line, then continue (no approval needed).

### 3. Start
- Read the ticket. Stop if it is Done, labelled `deferred`, or has an unresolved blocker.
- Create `.work/EA-<n>/`. Make sure `.work/` is in `.gitignore`.
- Branch: follow `git-commit` mode `start` in **pipeline mode** — base `main` (or `dev` if it exists), branch name per that skill, no confirmation prompt.
- Jira: transition to *In Progress* (list transitions first) — via `jira-ticket-management`.

### 4. Plan
Dispatch `ticket-planner`. Then read `plan.md` and check: every AC is in the table, every task names files, profile is set.
- `BLOCKED` → ask the owner the blocking questions (AskUserQuestion, with the planner's options and recommendation), resume the planner with the answers, repeat.
- Write the branch name into `plan.md`.

### 5. Implement
Dispatch `developer`. `BLOCKED` → ask the owner, resume the developer with the answer.

### 6. Code review loop (max 3 rounds)
Round N = 1, 2, 3: dispatch `code-reviewer` (round N, base branch).
- `PASS` → step 7.
- `CHANGES_REQUESTED` → resume the developer with `review-<N>.md`, then next round.
- Still failing after round 3 → **escalate** (step 11).

### 7. QA loop (max 3 rounds)
Round k = 1, 2, 3: dispatch `qa-e2e`.
- `SKIPPED` (profile `docs`) or `PASS` → step 8.
- `FAIL` caused by the environment (Node, browser, app does not start) → escalate.
- `FAIL` caused by the product → resume the developer with `qa-report.md`, then one code-review round on the fix (does not reset the review counter), then QA again.
- Still failing after round 3 → escalate.

### 8. Final review (you)
Write `.work/EA-<n>/final.md`:
- **AC checklist:** each AC from Jira (verbatim) → evidence (test name + result, QA screenshot, review). Any AC without evidence = not done → back to step 5 with a precise request, or escalate.
- Run the full check suite once more yourself (lint, types, unit/integration, E2E for this ticket) — commands from `docs/dev/coding-rules.md` §3.
- `git status --short` + `git diff --stat`: only files that belong to the ticket; no secrets, build output, `.work/`, or large files.
- Minor findings from reviews and QA that were not fixed → list them under "Improvements".

### 9. Commit
Follow `git-commit` mode `commit`:
- Without `--auto-commit`: show the owner the summary (AC checklist, files, test results) and the commit message(s); wait for OK.
- With `--auto-commit`: use `git-commit`'s **auto mode** (no approval prompt); all its safety checks still apply, and any safety-check hit stops the auto commit and asks the owner.
- Never push.

### 10. Close
- Jira (via `jira-ticket-management`, finish hand-off with the evidence from `final.md`): add a markdown comment — summary, branch, commit hash(es), AC → evidence table, test counts, known limitations; transition to *Done* only if every AC passed.
- **Improvements:**
  - product/code ideas (from minors, QA observations, plan risks) → propose new tickets (summary + one-line reason, label `proposed`). Create them only after the owner approves; in auto mode, list them in the Jira comment instead.
  - pipeline/process ideas (what slowed this ticket down, recurring review findings, missing rules) → append a dated entry to `docs/dev/team-retro.md`. If the same coding finding appears in 2+ tickets, propose a new rule for `docs/dev/coding-rules.md`.
- Report to the owner (Vietnamese, short): ticket, branch, commit, AC status, review/QA rounds used, improvements proposed, anything left open.

### 11. Escalate (any step)
Stop the pipeline, keep the working tree as is, and tell the owner: where it stopped, the last report file, the open findings, and 2–3 options (e.g. accept with known issues, give guidance and resume, split the ticket, abandon the branch). Resume from the step the owner chooses.

## Guardrails

- One ticket per run. Never start a second ticket in the same run.
- Never push, force, amend pushed commits, or skip hooks.
- Never mark a ticket Done without evidence for every AC.
- Do not edit agent outputs to make them pass; send work back instead.
