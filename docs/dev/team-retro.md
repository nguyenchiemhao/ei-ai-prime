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
