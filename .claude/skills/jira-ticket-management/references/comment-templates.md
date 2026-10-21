# Jira comment templates (pipelines)

Used by `/ship-ticket` and `/deliver-ticket`. The Lead posts every comment (subagents have no Jira access); planner and designer only write the plan comment file.

Rules for every comment:
- Short and scannable: **plan ≤ 1 500 characters, final ≤ 2 000 characters** (Blocked: as long as the facts need).
- Lists and comparisons go into **tables**, one short line per cell. Prose only for the 1–2 sentence summary.
- Plain language for the product owner: name areas, not files, functions, SQL or flags, unless the owner must act on one.
- Markdown (`contentFormat: "markdown"`); no markdown image syntax; links as plain URLs.
- Re-plan: update the same plan comment (`commentId`) and bump `rev`.

## Plan comment

```markdown
## Plan — EA-<n> (rev <r>)

**Goal:** <1–2 sentences: what changes for whom>

| Area | Change |
|---|---|
| <area> | <one line> |

**Decisions to check** (reply on the ticket to change one)

| # | Decision | Why |
|---|---|---|
| 1 | <one line> | <one line> |

| AC | How it is shown to work |
|---|---|
| AC1 | <one line> |

**Testing:** <automatic / browser checks> · **Risk:** <high/normal — reason> · **Needs you:** <none / one line>
```

## Final comment

```markdown
## <Done | In Review | Human Review> — EA-<n>

<1–2 sentences: what was delivered>

| | |
|---|---|
| Branch | `<branch>` |
| Commits | `<sha>` feature · `<sha>` docs/retro · merge `<sha>` (or "not merged") |
| CI | branch `<run>` green · main `<run>` green (or "not pushed") |
| Tests | backend <n> · frontend <n> · e2e <n> · QA cases <n> |
| QA cases | `docs/qa/<area>/EA-<n>-<slug>.md` |

| AC | Result | Proof |
|---|---|---|
| AC1 | ✅ | <one line> |

| Bug fixed | Severity | Found by |
|---|---|---|
| <one line> | blocker / major / minor (count for minors) | review / QA |

| Follow-up (not created) | Why |
|---|---|
| <one line> | <one line> |
```

*Human Review* adds an **Owner action needed** table (`# | Action | Then`).

## Blocked comment

```markdown
## Blocked — EA-<n>

| | |
|---|---|
| Reason | <what cannot proceed, which ACs> |
| Root cause | <verified, with the command output or source> |
| Impact | <tickets waiting> |
| Resume | `<command>` |

| # | Owner action needed | How to check |
|---|---|---|
| 1 | <step> | <check> |
```
