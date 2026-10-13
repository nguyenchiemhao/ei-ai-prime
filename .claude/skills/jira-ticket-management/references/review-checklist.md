# Ticket review checklist

Severity: **High** = blocks implementation or misleads the implementer; **Medium** = should be fixed before the ticket enters a sprint; **Low** = polish.

## Per ticket

| # | Area | Check | Severity |
|---|---|---|---|
| L1 | Language | Summary and description are in English (product copy quoted from the Vietnamese widget is fine) | High |
| L2 | Summary | `[CODE]` prefix + clear action phrase describing the outcome | Medium |
| T1 | Template | All sections present in order (see `story-template.md`) | High |
| T2 | Header | Epic, points with reason, priority with reason, labels, dependencies | Medium |
| A1 | AC | Numbered, Given/When/Then, testable, concrete numbers/names | High |
| A2 | AC coverage | Happy path + permissions + errors/empty states (+ design match for UI) | Medium |
| E1 | Estimate | `sp-N` label present and equals the header | Medium |
| E2 | Size | 5–8, or a reason; ≥ 13 must be split | Medium |
| I1 | INVEST | Independent enough, valuable (enablers say so), small, testable | Medium |
| D1 | Dependencies | Description line matches Jira links; no transitive Blocks; no cycles | Medium |
| D2 | Parent | Belongs to the right epic for its code prefix | Medium |
| G1 | Design | UI ticket has a Design reference section and a Relates link to EA-85; artboard names exist | Medium |
| G2 | Design drift | Ticket does not contradict a DSN-01 X-item proposal or design-decisions.md | Medium |
| Q1 | Open questions | Each has a Proposal/Assumption and an owner; answered questions are folded in and labelled `approved` | Low |
| R1 | Traceability | Context cites Dxx/Rxx/Oxx/screens; [Proposed] items are labelled `proposed` | Low |
| F1 | DoD | Uses the local integration environment (SET-03); security/privacy tickets add "No known security issues" | Medium |
| F2 | Status labels | `deferred` tickets have priority Low, a resume condition, and are not in a sprint | Medium |
| M1 | Markdown | No markdown image syntax, no broken tables, no leftover placeholders | Low |

## Backlog level

| # | Check |
|---|---|
| B1 | Every story/task has a parent epic |
| B2 | Points per epic and totals in `docs/backlog/backlog.md` match the `sp-N` labels |
| B3 | Critical path in `backlog.md` matches the Blocks links |
| B4 | No duplicate tickets (same scope under different codes) |
| B5 | Sprint plan respects dependencies and velocity |
| B6 | All UI tickets are linked from EA-85 |

## Report format

| Key | Code | Check | Finding | Severity | Proposed fix |
|---|---|---|---|---|---|

End with: tickets reviewed, findings by severity, and the top 3 fixes.
