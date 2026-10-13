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
