# ei-ai — project instructions

Embeddable enterprise AI assistant. Product decisions D1–D66: `docs/workshop/`. UI decisions: `docs/design/design-decisions.md`. Backlog: Jira project **EA**, summary in `docs/backlog/backlog.md`.

## Language

- Talk to the owner in Vietnamese.
- Code, comments, commit messages, branch names, Jira tickets and dev docs in English.

## Workflow

- One ticket at a time through `/ship-ticket` (agent team: `.claude/agents/`, design in `docs/superpowers/specs/2026-10-13-dev-agent-team-design.md`).
- Git through the `git-commit` skill, Jira through the `jira-ticket-management` skill.
- Commit messages: no `Co-Authored-By` or other AI attribution lines (overrides default attribution guidance).
- Never push, force-push, or skip hooks unless the owner asks.
- Scratch files for a ticket go in `.work/EA-<n>/` (git-ignored).
- Prefer ripgrep for search speed: the Grep tool (built on ripgrep; file list first, then content with `head_limit`), or `rg` in Bash instead of `grep -r`/`find | grep`. Use `grep` only to filter another command's output. Scripts, CI and hooks keep `grep`/Node, since `rg` may not be installed there.

## Coding rules (all code, any stack)

Full rules and stack-specific sections: `docs/dev/coding-rules.md`. Non-negotiable:

1. **Tenant isolation (D46):** every data access is scoped by organization; no query, cache key, file path or vector search without the org filter. Cross-tenant access is a blocker-level bug.
2. **Identity from the token only (D32):** user id, org id, groups and other identity parameters come from the verified token, never from request bodies, query strings or model output.
3. **Masked logs and traces (D52):** never log raw prompts, answers, tokens, secrets or personal data; use the masking helper.
4. **No secrets in the repo:** config through environment variables; `.env*` stays untracked.
5. **Every Acceptance Criterion has a test** (unit/integration, plus E2E for UI behaviour).
6. **Small, focused units:** one responsibility per file/module; follow existing patterns before adding new ones.
7. **Vietnamese and English** are both first-class: user-facing strings go through i18n, never hard-coded.
