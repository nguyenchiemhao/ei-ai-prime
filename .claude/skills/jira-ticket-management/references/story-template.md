# Ticket template (English, markdown)

Use this exact section order. Omit **Design reference** only for tickets with no UI (say "No UI" instead if a reader might expect one). Write "None" rather than deleting a section.

```markdown
**Epic:** <E# name> | **Story Points:** <n> (reason: <why this size>) | **Priority:** <Highest|High|Medium|Low> (reason: <why>)
**Labels:** <label, label>
**Dependencies:** Blocked by <CODE, CODE | —> | Blocks <CODE | —> | Relates to <CODE, DSN-01 | —>

### User Story
As a <role>, I want <capability>, so that <value>.

### Context
<Why this exists. Cite decisions (Dxx), risks (Rxx), open items (Oxx), screens. Mark [Proposed] items.>

### Design reference
Canvas: https://claude.ai/artifact/4YiSppZaEbjh9C5YSMgHUF — **<Artboard>**:
- <exact labels, fields, options, states and copy the implementer must match>
- <what is "Later" in the artboard and must stay disabled/hidden>

### Scope
- In scope: <…>
- Out of scope: <…>

### Acceptance Criteria
AC1 – <name>: Given <context>, When <action>, Then <measurable result>.
AC2 – <name>: …
ACn – Matches design: Then the screen matches the <Artboard> artboard.

### Expected Result
<What the user/system has when done.>

### Technical notes
<Suggestions only, no premature decisions.>

### Non-functional requirements
<Performance, security, privacy, accessibility, observability — or None.>

### Suggested tests
<Unit / integration / E2E / evaluation cases.>

### ⚠️ Open questions
1. <question> → *Proposal:* <recommended answer>. *(Owner: <who decides>)*

### Definition of Done
- Code review approved; tests pass
- All AC pass in the local integration environment (SET-03)
- <extra lines, e.g. "No known security issues" for security/privacy tickets>
```

## Writing rules

- **Summary:** `[CODE] <verb> <object> <qualifier>`, English, ≤ ~120 chars, describes the outcome (not "Implement X").
- **AC:** numbered, Given/When/Then, independently testable, with concrete numbers (latency, counts, limits) and real names from the seed data (Mekong Devworks, An Do, Employee Portal…). Cover happy path, permissions, errors/empty states, and the design match for UI tickets.
- **Points reason:** name the parts that drive the size; if outside 5–8, explain why it is not split/merged.
- **Priority reason:** milestone, critical path, risk or value.
- **Open questions:** every question has a *Proposal:* or *Assumption:*; when the owner answers, move the answer into Context/Scope and add label `approved`.
- **Spikes:** state the time-box, the question to answer, the output document and a decision criterion.
- **Deferred tickets:** add a "Deferred" note at the top of Context: reason, date, condition to resume.
- **DoD:** local integration environment while staging (SET-05) is deferred; tickets in E9 add "re-tested on staging once SET-05 is done".
