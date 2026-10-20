# deliver-ticket — design

- **Date:** 2026-10-20
- **Status:** draft for owner approval
- **Owner:** Hao (Howie) C. NGUYEN
- **Relation to `/ship-ticket`:** independent. `/ship-ticket` and its agents stay unchanged; `/deliver-ticket` is tried on a few tickets first, then the owner decides.

## Goal

Deliver one Jira EA ticket — feature, bug fix or chore — on the superpowers workflow, with as few owner questions as possible: the Lead decides what superpowers would normally ask the human, and asks only BLOCKING questions. On top of superpowers: a black-box QA engineer (as in flow F), Jira, and 1–2 commits per ticket.

## Owner decisions (2026-10-20)

| # | Decision |
|---|---|
| O1 | Works with Jira: ticket selection, plan comment, final comment, transitions (same conventions as `/ship-ticket`). |
| O2 | Brainstorming is autonomous. The owner is asked only BLOCKING questions, in one message. |
| O3 | No mutation reviewer and no automatic security review. When the ticket is done, the Lead **suggests** running `security-review` if the change touches a sensitive area; the owner decides. |
| O4 | Independent of `/ship-ticket`; trial first. |
| O5 | Name `deliver-ticket` (covers features, fixes and chores). |

## Flow

```
/deliver-ticket [EA-<n>] [--auto-commit] [--merge] [--push]
 0. Lead: preflight, select ticket, branch, Jira In Progress (same rules as /ship-ticket steps 1–3)
 1. DESIGN — designer agent, autonomous brainstorming
      feature/chore: superpowers:brainstorming, questions answered from sources
      bug: superpowers:systematic-debugging first (reproduce, root cause, failing test)
      → spec.md with a Rulings table; builder-check agent challenges it once
      → BLOCKING questions? Lead asks the owner once, designer updates
 2. PLAN — same designer agent, superpowers:writing-plans
      small tasks with Interfaces, Review Focus, Global Constraints, test contract
      → Lead posts the plan summary to Jira
 3. BUILD ‖ QA DESIGN
      Lead runs superpowers:subagent-driven-development (per task: fresh implementer
      → task reviewer → fix loop ≤ 5, model per task, escalate in rounds 4–5)
      deliver-qa mode design in parallel: test cases + specs from contract.md only
 4. FINAL REVIEW ‖ QA RUN
      final whole-branch reviewer (most capable model) reads the diff
      deliver-qa mode run against the local stack
      → findings + QA bugs: ONE fix wave → scoped re-review + QA recheck
 5. VERIFY — superpowers:verification-before-completion (npm run check, npm run e2e)
 6. COMMIT — squash the task commits into 1–2 commits (git-commit skill)
      --merge / --push as in /ship-ticket; otherwise keep the branch
 7. CLOSE — Jira comment + transition; report with Rulings, QA result, token report,
      and the security-review suggestion when it applies
```

## Roles

Each role is a separate context; they share files only, passed by the Lead.

| Role | Agent | Model | Writes |
|---|---|---|---|
| Lead (controller) | main session, skill `deliver-ticket` | session model | ledger, Jira, final report, commits |
| Designer | new `.claude/agents/designer.md` (modes design, revise, plan, contract) | opus | `spec.md`, `plan.md`, `contract.md` |
| Builder check | general-purpose with superpowers `builder-check-prompt.md` | sonnet | questions list |
| Implementer (per task) | general-purpose with superpowers `implementer-prompt.md` | per task: sonnet by default, opus for design-heavy tasks, one tier up in fix rounds 4–5 | code, unit/integration tests, task commit |
| Task reviewer (per task) | general-purpose with superpowers `task-reviewer-prompt.md` | sonnet (mid-tier floor), opus for tasks in the Review Focus | review file |
| Final reviewer | general-purpose with superpowers `code-reviewer.md` | opus | review file |
| QA | new `.claude/agents/deliver-qa.md` (modes design / run / recheck) | sonnet | `test-cases.md`, `e2e/**`, `qa-report.md` |

## Autonomous brainstorming

- The designer runs superpowers brainstorming but answers its own questions. Every answer is a **Ruling**: decision, why, source (D-xx, file, ticket, code), cost if wrong. An answer without a source must be the safe default and is marked as an assumption.
- **BLOCKING** (asked to the owner, never decided): scope change, data model change, security boundary, an exemption from tenant isolation, an irreversible or destructive action, a choice between options with no safe default. The Lead batches them in one AskUserQuestion.
- The builder check is superpowers' fresh-reader pass: answered / minor (designer decides, marks it a Ruling) / BLOCKING (to the owner).
- The Lead reads the ticket from Jira and passes its text to the designer (the claude.ai Atlassian connector is not available inside subagents, retro EA-21); the Lead posts every Jira comment.
- Bug tickets: the spec contains the reproduction, the verified root cause and the failing test that proves it, before any fix is planned.

## Plan

- superpowers writing-plans: task = the smallest unit with its own test cycle; each task lists exact files, an Interfaces block, and test → code → verify steps.
- Global Constraints = the non-negotiable rules of `CLAUDE.md` (tenant filter, identity from token, masked logs, no secrets, i18n, test per AC), copied verbatim.
- Review Focus = the five failure modes most likely to slip through, each with a test in its task; tenant, identity and secret handling are listed whenever the ticket touches them.
- The test contract lives in `contract.md`, the only file QA reads besides the ticket: the ACs verbatim (for a bug, the observable symptom), routes, test ids, roles/labels, API and CLI shapes, error and exit codes, seed data, one scenario per AC and an Attack list of the Review Focus items visible from outside — no implementation detail. Implementers, fixers and reviewers get it too, and each task's Interfaces block repeats the contract values it implements.
- Size budget: superpowers' proportion rule ("a plan longer than the code it describes has written the code instead"); `plan.md` stays under ~25 KB.
- Every AC of the ticket maps to at least one task test and one QA case.

## Commits

superpowers reviews each task on its own commit range, so implementers keep committing per task on the ticket branch. The base branch and its SHA are recorded in `.work/EA-<n>/base` at the start. The squash is the last step before committing (afterwards the ledger's task SHAs are unreachable and no review package can be built from them): `git reset --soft <base SHA>`, `git restore --staged .`, then commit by group — one commit for code and tests, an optional second for docs or the retro. A red CI after the push is fixed by one fixer and a new commit on top, without re-squashing. The SDD workspace is deleted only after the merge/push.

## Security review suggestion

At close, if the diff or the Review Focus touches authentication, tokens, tenant scoping, RBAC, Connectors/Tools/outbound HTTP, upload, logging of user data or prompt construction, the report ends with: "Suggested: run `/security-review` on this branch (reason: …)". The Lead does not run it.

## Overrides of superpowers

| superpowers default | deliver-ticket |
|---|---|
| Brainstorming asks the human one question at a time | Designer answers from sources; only BLOCKING questions go to the owner |
| Design approval and plan approval by the human | No approval gate; the plan summary is posted to Jira for the owner's information |
| Spec and plan committed under `docs/superpowers/` | Kept in `.work/EA-<n>/` (git-ignored); the summary goes to Jira |
| Worktree per plan | Ticket branch in the main working tree for the trial (the local Docker stack and ports stay simple) |
| Commit per task in the final history | Task commits squashed into 1–2 commits |
| No QA role | Black-box QA (design in parallel, run and recheck) |
| Final-review fix wave: review findings only | One fix wave for final-review findings and QA bugs together |
| Finish menu (merge / PR / keep) asked at the end | `finishing-a-development-branch` is not used; `--merge` / `--push` decide, without them the branch is kept |
| Implementer runs the full suite before each commit | Tier T1 per step; the full `npm run check` and `npm run e2e` run once in the verify step (a red result gets one verify-fix, then escalation) |

Everything else follows superpowers unchanged: TDD, per-task review with two verdicts, fix loop limits and breaker, ledger, Rulings in the final message, verification before completion.

## Files

- New: `.claude/skills/deliver-ticket/SKILL.md` (orchestrator; references the superpowers skills by name, lists the overrides above), `.claude/agents/designer.md`, `.claude/agents/deliver-qa.md` (black-box QA for this flow: designs from `contract.md` and `ticket.md` only).
- Reused with additive changes: `git-commit` skill (auto mode also for `/deliver-ticket --auto-commit`), `token-report.mjs` (labels `designer`, `deliver-qa`, and general-purpose agents by their dispatch description: `Builder check`, `Implement`/`Fix`, `Review`/`Final review`), Jira conventions.
- Untouched: `/ship-ticket` and its agents (`ticket-planner`, `developer`, `qa-e2e`, `code-reviewer`).

## Trial and success criteria

Run `/deliver-ticket` on two tickets: one feature and one bug. Compare with EA-21 (`/ship-ticket`, ~$32.8 API-equivalent, 2 verify rounds):
- owner questions asked (target: only BLOCKING ones);
- defects found after the final review (target: none reach commit);
- token cost per ticket from `token-report.mjs`;
- Rulings the owner would have decided differently.

## Risks

- A wrong autonomous decision costs rework: mitigated by sourced Rulings, the BLOCKING stop and the Rulings list in the report.
- No mutation reviewer: tests that do not bite can pass review; the owner can still run `security-review`, and the final reviewer checks the Review Focus tests.
- More agents per ticket (one implementer and one reviewer per task): cost is measured in the trial before any wider use.
