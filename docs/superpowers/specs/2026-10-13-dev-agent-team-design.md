# Dev agent team — design

- **Date:** 2026-10-13
- **Status:** approved in chat (architecture A, 5 roles), implemented in the same session
- **Owner:** Hao (Howie) C. NGUYEN — the only human reviewer

## Goal

Take one Jira EA ticket through its whole lifecycle with as little human effort as possible:
pick → analyse and clarify → research → detailed plan → branch + code → code review → web E2E test
(Playwright + Chrome DevTools) → final review against Acceptance Criteria → commit → Jira update →
improvement proposals.

## Decisions

| # | Decision |
|---|---|
| T1 | One ticket at a time, sequential. Parallel tickets are out of scope for now. |
| T2 | Architecture A: the main session is the **Lead** and runs the `/ship-ticket` skill; four subagents in `.claude/agents/` do the work. Agent teams stay enabled but are not used by the pipeline. |
| T3 | Human gate only **before commit**. `/ship-ticket <key> --auto-commit` skips that gate. Never push. |
| T4 | Code Reviewer is separate from Developer (no self-review). |
| T5 | Review tooling: built-in `code-review` skill (effort `high`) + `security-review` for auth / tenant / token / identity / connector work. Developer handles feedback with `superpowers:receiving-code-review`. `pr-review-toolkit` is a phase-2 option. |
| T6 | E2E tooling is scoped to the QA agent through inline `mcpServers`: Playwright MCP (`@playwright/mcp`) and Chrome DevTools MCP (`chrome-devtools-mcp`). Playwright test files are committed under `e2e/`. |
| T7 | Agents hand off through files in `.work/EA-<n>/` (git-ignored). The Lead posts the final summary as a Jira comment. |
| T8 | Coding rules in two layers: project `CLAUDE.md` (stack-agnostic, applies now) and `docs/dev/coding-rules.md` (stack-specific part filled once SET-01 / EA-11 picks the stack). |
| T9 | Loop limits: 3 review rounds, 3 QA rounds; then stop and ask the owner. Blocking open questions also stop the pipeline. |
| T10 | Improvements: product/code ideas → proposed tickets (label `proposed`), created only with owner approval (auto mode: listed in the Jira comment only). Process ideas → `docs/dev/team-retro.md`. |

## Roles

| Agent | File | Model | Writes | Output |
|---|---|---|---|---|
| Lead | `.claude/skills/ship-ticket/SKILL.md` (main session) | session model | `.work/EA-<n>/final.md`, git commit, Jira | final report |
| Planner | `.claude/agents/ticket-planner.md` | opus | `.work/EA-<n>/plan.md` | `STATUS: READY` or `BLOCKED` |
| Developer | `.claude/agents/developer.md` | sonnet | source code, unit tests, `dev-log.md` | `STATUS: DONE` or `BLOCKED` |
| Code Reviewer | `.claude/agents/code-reviewer.md` | opus | `review-<N>.md` | `STATUS: PASS` or `CHANGES_REQUESTED` |
| QA E2E | `.claude/agents/qa-e2e.md` | sonnet | `e2e/**`, `qa-report.md`, `screenshots/` | `STATUS: PASS`, `FAIL` or `SKIPPED` |

## Flow

```
Lead: preflight → pick ticket → Jira In Progress → branch (git-commit start, auto-confirmed)
  → Planner ─BLOCKED→ ask owner → resume Planner
  → Developer
  → Code Reviewer ─CHANGES_REQUESTED→ Developer (resume) … max 3
  → QA E2E ─FAIL→ Developer → Code Reviewer → QA … max 3   (SKIPPED for docs/spike tickets)
  → Lead final review (every AC has evidence, full test run, clean diff)
  → commit (gate, or auto) → Jira comment + Done → improvements → report
```

## Ticket profiles

The Planner sets one profile in `plan.md`; it decides what QA does.

| Profile | Example | QA |
|---|---|---|
| `ui` | widget, admin screens | Playwright specs per AC + exploratory run + DevTools console/network/perf check |
| `api` | endpoints, pipeline | API-level Playwright `request` tests or the project test runner |
| `docs` | spike/ADR, docs-only | skipped; Reviewer checks the document against the AC |

## Prerequisites

- Node.js ≥ 20.19 (Chrome DevTools MCP) — the dev machine has v14, upgrade to Node 22 LTS.
- Google Chrome installed (Chrome DevTools MCP).
- Atlassian MCP connected (already configured at user level).
- Trust the project folder so inline MCP servers in `.claude/agents/` load.

## Out of scope

Parallel tickets, worktrees, pull requests, CI, deploys (staging is deferred — see backlog EA-15).
