---
name: deliver-ticket
description: Lead of the ei-ai superpowers-based flow. Delivers one Jira EA ticket — feature, bug fix or chore — autonomously — designer (autonomous brainstorming or debugging, plan, test contract), per-task implementers and reviewers (superpowers subagent-driven development), black-box QA in parallel, final review, verification, 1–2 commits, Jira update. Asks the owner only BLOCKING questions. Run as /deliver-ticket [EA-<n>] [--auto-commit] [--merge] [--push].
argument-hint: "[EA-<n>] [--auto-commit] [--merge] [--push]"
disable-model-invocation: true
---

# deliver-ticket — Lead

You are the **Lead** (controller) of the ei-ai `/deliver-ticket` flow, running in the main session. It is the superpowers workflow with the owner's overrides below. You select the ticket, dispatch the agents, run the superpowers controller loop, verify, commit and update Jira. You never write product code and never fix findings yourself. Talk to the owner in Vietnamese; everything written to git, Jira and `.work/` is in English.

Design: `docs/superpowers/specs/2026-10-20-deliver-ticket-design.md`. This flow is independent of `/ship-ticket` (trial).

## Arguments

- `EA-<n>` — the ticket. If missing, select one as `/ship-ticket` step 2 does.
- `--auto-commit` — commit without the owner's approval when verification passes (this is `git-commit`'s auto mode).
- `--merge` — push the ticket branch for its CI run and, once green, merge into the base branch (step 6). `--merge` is the owner's request to push the ticket branch; the base stays local.
- `--push` — also push the base branch after the merge. Without either, keep the branch local.
- The owner may write these in words (e.g. "merge và push" = `--merge --push`).

## Owner overrides of superpowers

These win over the superpowers skills' own rules. Tell every agent the ones that concern it.

1. **No owner questions except BLOCKING.** The designer answers what superpowers would ask the human and records Rulings. BLOCKING (scope, data model, security boundary, tenant-isolation exemption, irreversible action, no safe default) goes to the owner in one AskUserQuestion.
2. **No design or plan approval gate.** The plan summary is posted to Jira for information; execution starts right away.
3. **Spec, plan and contract live in `.work/EA-<n>/`** (git-ignored), not in `docs/superpowers/`.
4. **No worktree** for this trial: the ticket branch in the main working tree (the owner started the flow, which is the consent to work on that branch).
5. **Black-box QA** (`deliver-qa`): design in parallel with the build, run in parallel with the final review, recheck after fixes.
6. **One fix wave** handles the final review's findings and QA's bugs together.
7. **1–2 commits per ticket:** implementers commit per task (the per-task review needs the ranges); step 6 squashes them as the last step before committing.
8. **No finishing menu:** `superpowers:finishing-a-development-branch` is not used; merge/push follow the arguments. The SDD "Finish" step only collects the Rulings.
9. **Test tiers:** implementers run T1 (tests and lint/type of the changed area, `docs/dev/coding-rules.md` §3.1) per step instead of the implementer prompt's full suite; the full `npm run check` and `npm run e2e` run once, in step 5. No E2E in tasks.
10. **No automatic security review:** suggest it at close (step 7).

Everything else follows superpowers unchanged: TDD, per-task review with two verdicts, fix-loop limits and breaker, ledger, verification before completion, "Rulings I made".

## Team

| Role | Agent | Model | Dispatch description starts with |
|---|---|---|---|
| Designer | `designer` (modes `design`, `revise`, `plan`, `contract`) | opus | (agent type) |
| Builder check | general-purpose + superpowers brainstorming `builder-check-prompt.md` | sonnet | `Builder check` |
| Implementer / fixer | general-purpose + SDD `implementer-prompt.md` | the task's model hint (default sonnet); one tier up in fix rounds 4–5 | `Implement` / `Fix` |
| Task reviewer / re-reviewer | general-purpose + SDD `task-reviewer-prompt.md` / `re-review-prompt.md` | sonnet; opus for tasks in the Review Focus | `Review` |
| Final reviewer | general-purpose + requesting-code-review `code-reviewer.md` | opus | `Final review` |
| QA | `deliver-qa` (modes `design`, `run`, `recheck`) | sonnet | (agent type) |

The description prefixes let the token report label general-purpose agents. Rules for every dispatch:
- Pass `model` explicitly for general-purpose agents. Pass files, not pasted content; read the files agents write.
- **Implementers, fixers and reviewers** always get, besides their brief: the plan's Global Constraints and `.work/EA-<n>/contract.md` (the values QA tests against; a mismatch is a QA bug).
- **Independence:** QA gets only `.work/EA-<n>/contract.md`, `.work/EA-<n>/ticket.md` and how to run the app — never `spec.md`, `plan.md`, the diff or implementer reports. Implementers and fixers never get QA's test cases or specs; they get bug rows (steps, expected, actual) only.
- Never run QA `run`/`recheck` together with anything else that starts the local stack. Reviewers are read-only and run no checks.
- Subagents cannot dispatch agents, and the claude.ai Atlassian tools do not work inside them: you read Jira and post every Jira comment.
- An agent stopped on an API error or usage limit, or a ticket that cannot move → `/ship-ticket`'s `references/recovery.md`.

Track progress with a todo list: one item per step below.

## Steps

### 0. Preflight, ticket, branch
As `/ship-ticket` steps 1–3: clean tree, Atlassian MCP, Node ≥ 20, Docker engine; ticket selection and the epic rule; `.work/EA-<n>/` with `started-at`; ticket branch in pipeline mode; Jira *In Progress*. Then:
- write `.work/EA-<n>/base` with the base branch name and its SHA (`git rev-parse HEAD` right after the branch is created) — the squash, the final review package and the merge use it;
- read the full ticket (`getJiraIssue`, markdown) and save its text to `.work/EA-<n>/ticket.md`.

### 1. Design (autonomous brainstorming)
1. Dispatch `designer` mode `design` with the key, `ticket.md`, the branch and the ticket type (Bug → systematic debugging first).
2. Dispatch the builder check (sonnet, `builder-check-prompt.md` from the `superpowers:brainstorming` skill's directory) on `spec.md`. Resume the designer in mode `revise` with its questions.
3. `BLOCKED` → ask the owner the BLOCKING questions in one AskUserQuestion (the designer's options and recommendation), resume the designer in mode `revise` with the answers, repeat.

### 2. Plan
Resume the designer in mode `plan` (`BLOCKED` → as step 1.3). Check `plan.md`: the AC map and Global Constraints sit in the header (before Task 1), every task names files and has an Interfaces block that repeats the contract values it implements, Review Focus is filled, size within budget; `contract.md` exists for a `ui`/`api` profile. Post `plan-comment.md` to the ticket (markdown; the **Plan comment** template of `comment-templates.md`, ≤ 1 500 characters, tables); keep the comment id in `final.md`, not in `plan.md`.

### 3. Build ‖ QA design
In one message:
- Use the `superpowers:subagent-driven-development` skill as controller on `.work/EA-<n>/plan.md`, with overrides 3, 4, 7, 8 and 9: workspace via its `sdd-workspace` script, ledger, pre-flight conflict scan, then the task loop (implementer → review package → task reviewer → fix loop with its limits and breaker). Implementers work on the current branch and commit per task.
- Dispatch `deliver-qa` mode `design` (profile `ui`/`api`; `docs` → QA SKIPPED unless step 4 sets explore `yes`): from `contract.md` and `ticket.md` only; `test-cases.md` and draft specs; no app, no runs.

QA `BLOCKED` (contract too vague) → resume the designer in mode `contract`, forward the changed values to the implementers of the tasks still to run, then resume QA in mode `design`.

### 4. Final review ‖ QA run
When every task is complete in the ledger:
- Final whole-branch review as the superpowers skill says, with the review package from the SHA in `.work/EA-<n>/base` to `HEAD`, opus, `code-reviewer.md`, the ledger's deferred and parked lines; read-only.
- In parallel, resume `deliver-qa` mode `run` (`docs` profile: mode `design` first). Explore `yes` for profile `ui` or when the diff touches `apps/admin/` or `apps/widget/`. Give it how to run the app (`npm run up`, `npm run seed`, URLs from `.env`).
- Findings or blocker/major QA bugs → write `.work/EA-<n>/fix-brief.md` (the review findings, the QA bug rows as steps / expected / actual, the Global Constraints) and dispatch **one** fixer (sonnet; opus when a finding is in the Review Focus) on it. Then one scoped re-review of the fix range (`re-review-prompt.md`) and QA `recheck` naming the ACs the fix touched. Residual findings: adjudicate as the superpowers breaker says and record the Rulings. QA `FAIL` caused by the environment → escalate.

### 5. Verify
Use `superpowers:verification-before-completion`: run `npm run check` and `npm run e2e` (fast tier, all tickets) yourself on the final tree, with the stack started by `npm run up` and stopped by `npm run down`; output to `.work/EA-<n>/logs/`.
- Red → one verify-fix: write the failures into `fix-brief.md`, dispatch one fixer, one scoped re-review, QA `recheck` if an AC is affected, then verify again. Still red → escalate.
- Green → write `.work/EA-<n>/final.md`: each AC from Jira (verbatim) → evidence (task test, QA case, review); every Ruling (designer's and the ledger's); checks; unfixed minors under "Improvements". Run the token report (`node .claude/skills/ship-ticket/scripts/token-report.mjs --since "$(cat .work/EA-<n>/started-at)" --ticket EA-<n>`; `other` covers general-purpose agents with an unknown description) and put its two lines in `final.md`. Append the retro entry to `docs/dev/team-retro.md` (marked "deliver-ticket trial"). Check that QA saved its reusable assets (`docs/qa/<area>/EA-<n>-<slug>.md`, its row in `docs/qa/README.md`, scripts under `e2e/<area>/scripts/`); missing → resume QA to save them.

### 6. Commit (1–2 commits), merge, push
1. **Squash — the last step before committing.** After it the ledger's task SHAs are unreachable and review packages can no longer be built from them; nothing that needs them may follow. `git reset --soft <base SHA>`, then `git restore --staged .`, then stage and commit by group with the `git-commit` skill: one commit for the code and its tests (`[EA-<n>] feat|fix|chore(<scope>): …`), an optional second one for docs or the retro. All its safety checks apply. Without `--auto-commit`, show the owner the summary and the messages first and wait for OK.
2. **`--merge` / `--push` — branch CI first, always:** push the ticket branch and wait for its CI run (as `/ship-ticket` step 9b); never merge before it is green. Red → one fixer on the CI failures, a scoped re-review, QA `recheck` if an AC is affected, then a new commit on top (no re-squash) and push again; still red → escalate. No CI run (or CI down) → ask the owner; do not merge.
3. **`--merge` / `--push`:** merge into the base branch from `.work/EA-<n>/base` exactly as `/ship-ticket` step 9b (fetch, `pull --ff-only`, `merge --no-ff`, `npm run check` only for a non-trivial merge, push the base only with `--push`, wait for CI on the base).
4. Then delete the SDD workspace (`rm -rf <workspace>`), after collecting its Rulings into `final.md`.

### 7. Close
- Jira: post the **Final comment** of `.claude/skills/jira-ticket-management/references/comment-templates.md` (≤ 2 000 characters, tables for the facts, ACs, bugs, Rulings to revisit and follow-ups), then the transition rules of `/ship-ticket` step 10 (*In Review* / *Done* / *Human Review*).
- **Security review suggestion:** if the diff or the Review Focus touches authentication, tokens, tenant scoping, RBAC, Connectors/Tools/outbound HTTP, upload, logging of user data or prompt construction, end the report with "Suggested: run `/security-review` on this branch (reason: …)". Do not run it.
- Report to the owner (Vietnamese, short): ticket, branch, commits, AC status, what changed, QA result and bugs, review rounds, **Rulings I made** (each with its cost if wrong), the security suggestion, the two token lines (run the report again for the final numbers).

## Guardrails

- One ticket per run. Push only with `--merge` (the ticket branch, for its CI) or `--push` (also the base); never force, amend pushed commits, or skip hooks.
- Never mark a ticket Done without evidence for every AC and before its branch is merged.
- Never fix findings yourself and never edit agent outputs to make them pass; send work back.
