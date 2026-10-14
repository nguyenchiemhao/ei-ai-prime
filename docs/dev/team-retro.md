# Dev agent team — retro log

The Lead (`/ship-ticket`) appends one entry per ticket about the **pipeline itself**: what slowed it down, recurring review/QA findings, missing rules or tools. Product ideas go to Jira as `proposed` tickets instead.

Format:

```markdown
## YYYY-MM-DD — EA-<n>
- Rounds: review <N>, QA <k>; escalations: <none | where>
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
