# JQL patterns for project EA

Always add `project = EA`. Request only the fields you need (`summary,status,priority,labels,parent,issuelinks`).

## Backlog structure

| Need | JQL |
|---|---|
| All epics | `project = EA AND issuetype = Epic ORDER BY key` |
| Children of an epic | `project = EA AND parent = EA-3 ORDER BY key` |
| Stories without an epic | `project = EA AND issuetype in (Story, Task, Bug) AND parent is EMPTY` |
| Ticket by code | `project = EA AND summary ~ "\"[KB-02]\""` |
| Prototype vs MVP | `project = EA AND labels = prototype` / `labels = mvp` |

## Status and flow

| Need | JQL |
|---|---|
| Open work | `project = EA AND statusCategory != Done ORDER BY priority DESC, key` |
| In progress | `project = EA AND statusCategory = "In Progress"` |
| Done this week | `project = EA AND statusCategory = Done AND resolved >= startOfWeek()` |
| Changed recently | `project = EA AND updated >= -7d ORDER BY updated DESC` |
| Stale in progress | `project = EA AND statusCategory = "In Progress" AND updated <= -5d` |
| Status changed by date | `project = EA AND status CHANGED TO "Done" DURING (startOfWeek(), now())` |

## Dependencies

| Need | JQL |
|---|---|
| Blocked tickets still open | `project = EA AND issueLinkType = "is blocked by" AND statusCategory != Done` |
| Tickets blocking others | `project = EA AND issueLinkType = blocks AND statusCategory != Done` |
| Linked to the design hub | `project = EA AND issue in linkedIssues(EA-85)` |

`linkedIssues()` and `issueLinkType` work on Jira Cloud without apps. To list blockers of one ticket, read its `issuelinks` field.

## Estimation and hygiene

| Need | JQL |
|---|---|
| By points | `project = EA AND labels = sp-8` |
| Missing points | `project = EA AND issuetype in (Story, Task) AND labels not in (sp-1, sp-2, sp-3, sp-5, sp-8, sp-13) AND labels != admin-task` |
| Spikes | `project = EA AND labels = spike` |
| Deferred / approved | `project = EA AND labels = deferred` / `labels = approved` |
| Proposed (not in docs) | `project = EA AND labels = proposed` |
| Unassigned in sprint | `project = EA AND sprint in openSprints() AND assignee is EMPTY` |
| Text search | `project = EA AND text ~ "MailHog"` (diacritics may not match — fall back to parsing descriptions) |

## Sprints

| Need | JQL |
|---|---|
| Active sprint | `project = EA AND sprint in openSprints()` |
| Future sprints | `project = EA AND sprint in futureSprints()` |
| Specific sprint | `project = EA AND sprint = <sprintId>` (or `sprint = "EA Sprint 1"`) |
| Not in any sprint | `project = EA AND sprint is EMPTY AND statusCategory != Done` |
| Label fallback | `project = EA AND labels = sprint-1` |
