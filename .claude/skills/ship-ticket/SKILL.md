---
name: ship-ticket
description: Lead of the ei-ai dev team. Takes one Jira EA ticket from selection to commit — plan (ticket-planner), code (developer), review (code-reviewer), E2E test (qa-e2e), final review against Acceptance Criteria, commit, optional merge and push, Jira update and improvement proposals. Run as /ship-ticket [EA-<n>] [--auto-commit] [--merge] [--push].
argument-hint: "[EA-<n>] [--auto-commit] [--merge] [--push]"
disable-model-invocation: true
---

# ship-ticket — Lead

You are the **Lead** of the ei-ai dev team, running in the main session. You do not write product code yourself: you select the ticket, dispatch the four subagents, enforce gates and loop limits, do the final review, commit, and update Jira. Talk to the owner in Vietnamese; everything written to git, Jira and `.work/` is in English.

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
| `developer` | key, work folder, branch | `STATUS: DONE|BLOCKED <dev-log path>` |
| `code-reviewer` | key, work folder, round N, base branch | `STATUS: PASS|CHANGES_REQUESTED <review path>` |
| `qa-e2e` | key, work folder, round k | `STATUS: PASS|FAIL|SKIPPED …` |

Keep each agent's id. To send the Developer back to fix findings, **resume the same developer** with `SendMessage` (it keeps its context); start a new reviewer per round only if the previous one cannot be resumed. Read the files the agents write — do not rely on their chat summary. If an agent stops on an API error (rate limit, timeout), check the working tree and the dev log, then resume the same agent with a short note of where it stopped.

Subagents cannot launch other agents. A step the plan marks **Lead-run** (e.g. an independent second labeller or reviewer that must not share the developer's context) is done by you between developer phases: run the plan's leak check first, copy only the allowed inputs into an isolated scratch folder, run a fresh agent on a different model than the developer, copy its output back, and hand it to the developer.

**Design tickets on the claude.ai canvas** (profile `design`): no developer/reviewer subagents — subagents cannot write to claude.ai artifacts. You edit and publish the canvas yourself, publish early so the owner sees progress, and mirror the files to `docs/design/canvas/` in the same commit.

Track progress with a todo list: one item per step below.

## Steps

### 1. Preflight
- `git status --short` must be clean, except for untracked files under `.work/`. Otherwise stop and offer: commit first (`git-commit`), stash, or abort.
- Atlassian MCP responds (`mcp__atlassian__getJiraIssue` on any key).
- `node -v` ≥ 20 when the ticket may need E2E; if lower, warn that QA will fail and ask whether to continue with QA skipped.
- When the ticket may need containers (stack, database, model server): check the Docker **engine**, not just the client — `docker version --format '{{.Server.Version}}'`. If it fails, stop before planning and give the owner the fix steps (or pick another ticket and say why).

### 2. Select the ticket (only if no key was given)
JQL (cloudId in `.claude/skills/jira-ticket-management/references/jira-conventions.md`):
```
project = EA AND statusCategory = "To Do" AND status != Blocked AND issuetype != Epic
AND (labels IS EMPTY OR labels NOT IN (deferred, proposed))
ORDER BY priority DESC, rank ASC
```
(`Blocked` belongs to the To Do status category, so it must be excluded explicitly.) Take the first ticket whose "is blocked by" links are all Done.
- Same epic as the last ticket worked on → tell the owner which ticket and why in one line, then continue (no approval needed).
- **Different epic** → stop and ask the owner (AskUserQuestion): the first candidate (recommended) plus 2–3 unblocked alternatives, including the best one in the current epic.
- If the chain is held up by a ticket the team cannot unblock, apply the Blocked rule (step 11) to that ticket first.

### 3. Start
- Read the ticket. Stop if it is Done, labelled `deferred`, or has an unresolved blocker.
- Create `.work/EA-<n>/`. Make sure `.work/` is in `.gitignore`.
- Branch: follow `git-commit` mode `start` in **pipeline mode** — base `main` (or `dev` if it exists), branch name per that skill, no confirmation prompt.
- Jira: transition to *In Progress* (list transitions first) — via `jira-ticket-management`.

### 4. Plan
Dispatch `ticket-planner` with the branch name, so it lands in `plan.md` and the Jira plan comment. Then read `plan.md` and check: every AC is in the table, every task names files, profile is set, branch is filled.
- Check the planner posted the plan comment on the ticket (comment id in its return line and in `plan.md`); the owner reviews the plan there. If it is missing, resume the planner once to post it; if that fails too, post `plan-comment.md` yourself via `jira-ticket-management`.
- Check every **Lead-run** step in the plan has a leak check you can run before it (see Team).
- `BLOCKED` → ask the owner the blocking questions (AskUserQuestion, with the planner's options and recommendation), resume the planner with the answers (it updates the same comment), repeat.

### 5. Implement
Dispatch `developer`. `BLOCKED` → ask the owner, resume the developer with the answer.

### 6. Code review loop (max 3 rounds)
Round N = 1, 2, 3: dispatch `code-reviewer` (round N, base branch).
- `PASS` → step 7.
- `CHANGES_REQUESTED` → resume the developer with `review-<N>.md`, then next round.
- Still failing after round 3 → **escalate** (step 11).

### 7. QA loop (max 3 rounds)
Round k = 1, 2, 3: dispatch `qa-e2e`.
- `SKIPPED` (profile `docs` or `design`) or `PASS` → step 8. For these profiles you may skip dispatching `qa-e2e` and record QA as SKIPPED.
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
- Without `--push`, never push.

### 9b. Merge and push (only with `--merge` / `--push`)
- Before merging, run the ticket's checks on a fresh checkout of the ticket branch (temporary `git worktree`, removed afterwards) to catch line-ending or untracked-file surprises.
- `git fetch`, switch to the base, `git pull --ff-only`, then `git merge --no-ff <branch> -m "[EA-<n>] chore(<scope>): merge <short summary>" -m "Refs: EA-<n>"`. On a conflict, stop and ask the owner.
- Re-run the ticket's checks on the base. Commit the retro entry (step 10) on the base before pushing, so one push carries both.
- With `--push`: `git push origin <base>` (never force). Do not push the ticket branch unless asked.

### 10. Close
- Jira (via `jira-ticket-management`, finish hand-off with the evidence from `final.md`): add a markdown comment — summary, branch, commit hash(es), merge commit and push (if done), AC → evidence table, test counts, known limitations. Then transition:
  - not merged, every AC passed → *In Review*;
  - merged, every AC passed and the DoD needs nothing more from a person → *Done*;
  - merged, but an AC or the DoD still needs a person (owner review of content, human labellers, a manual sign-off) → *Human Review*, with an **"Owner action needed"** list in the comment (numbered, concrete steps, and when to move it to Done).
- **Improvements:**
  - product/code ideas (from minors, QA observations, plan risks) → propose new tickets (summary + one-line reason, label `proposed`). Create them only after the owner approves; in auto mode, list them in the Jira comment instead.
  - pipeline/process ideas (what slowed this ticket down, recurring review findings, missing rules) → append a dated entry to `docs/dev/team-retro.md`. If the same coding finding appears in 2+ tickets, propose a new rule for `docs/dev/coding-rules.md`.
- Report to the owner (Vietnamese, short): ticket, branch, commit, AC status, review/QA rounds used, improvements proposed, anything left open.

### 11. Escalate (any step)
Stop the pipeline, keep the working tree as is, and tell the owner: where it stopped, the last report file, the open findings, and 2–3 options (e.g. accept with known issues, give guidance and resume, split the ticket, abandon the branch). Resume from the step the owner chooses.

**Blocked rule:** when a ticket cannot move because of something the team cannot decide or fix (an environment problem, a missing account or key, an owner decision with no safe default), transition it to *Blocked* and add a comment with:
- **Reason** — what cannot proceed and which AC are affected;
- **Root cause** — verified now, with the command output or source;
- **Owner action needed** — numbered, concrete steps, and how to check they worked;
- **Impact** — which tickets wait on it;
- **Resume** — the command to run once it is fixed (e.g. `/ship-ticket EA-<n> --auto-commit`).

## Guardrails

- One ticket per run. Never start a second ticket in the same run.
- Push only with `--push` (the base branch, after merge). Never force, amend pushed commits, or skip hooks.
- Never mark a ticket Done without evidence for every AC, and never before its branch is merged.
- Do not edit agent outputs to make them pass; send work back instead.
