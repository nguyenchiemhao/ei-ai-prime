# Jira operations — how to do each capability

Two channels:

- **MCP** — `mcp__claude_ai_Atlassian__*` tools (the claude.ai Atlassian connector) (load them with ToolSearch `select:<name>` if deferred). Preferred: no setup, markdown descriptions.
- **REST** — `scripts/jira-rest.sh` (curl + API token) for what MCP cannot do. Run it with the Bash tool from the repo root: `bash .claude/skills/jira-ticket-management/scripts/jira-rest.sh <cmd> ...`.

cloudId for MCP: `71bb307d-8749-442a-86d4-969021d4b921`. Site for REST: `https://nguyenchiemhao2205.atlassian.net`.

## Setup

One-time setup, needed only for the REST channel. The user creates an API token at https://id.atlassian.com/manage-profile/security/api-tokens and adds to `~/.bashrc` (never to the repo):

```bash
export JIRA_EMAIL="nguyenchiemhao2205@gmail.com"
export JIRA_API_TOKEN="<token>"
```

Then `bash .claude/skills/jira-ticket-management/scripts/jira-rest.sh check` must print `OK: <name>`. If the variables are missing, explain the setup and fall back to MCP-only behaviour; never ask the user to paste the token into the chat and never write it to a file.

## Capability map

| Area | Capability | Channel | How |
|---|---|---|---|
| Issues | Create Task / Bug / Story / Epic | MCP | `createJiraIssue` (`issueTypeName`, `summary`, `description`, `contentFormat: markdown`, `additional_fields: {priority, labels, parent}`) |
| | Create Subtask | MCP | `createJiraIssue` with `issueTypeName: "Subtask"`, `parent: "EA-41"` |
| | Update fields (priority, labels, parent, custom) | MCP | `editJiraIssue` `fields: {...}` — always read first; `labels` replaces the whole list, so merge with the current labels |
| | Assign / unassign | MCP | `lookupJiraAccountId` (name or email) → `editJiraIssue` `fields: {"assignee": {"accountId": "<id>"}}`; unassign with `null` |
| | Search with JQL | MCP | `searchJiraIssuesUsingJql` with narrow `fields`; patterns in [jql-patterns.md](jql-patterns.md) |
| | Get details | MCP | `getJiraIssue` (`fields`, `expand: "renderedFields,names"` when needed) |
| | Delete | REST | `DELETE /rest/api/3/issue/EA-99?deleteSubtasks=true` — see "Delete" below |
| | Batch create | MCP (parallel) / REST | See "Batch create" below |
| Workflow | List transitions | MCP | `getTransitionsForJiraIssue` |
| | Required fields on a transition | REST | `GET /rest/api/3/issue/EA-41/transitions?expand=transitions.fields` → fields with `required: true` |
| | Transition (with fields) | MCP | `transitionJiraIssue` `transition: {id}`, `fields: {"resolution": {"name": "Done"}}` if required; add the explanation as a separate comment |
| | Log work | MCP | `addWorklogToJiraIssue` |
| Agile | Find the board | REST | `GET /rest/agile/1.0/board?projectKeyOrId=EA` → `values[].id`, `type` |
| | List sprints | REST | `GET /rest/agile/1.0/board/<boardId>/sprint?state=active,future,closed` |
| | Create sprint | REST | `POST /rest/agile/1.0/sprint` |
| | Update / start / close sprint | REST | `POST /rest/agile/1.0/sprint/<id>` (partial update) |
| | Move issues to a sprint | REST | `POST /rest/agile/1.0/sprint/<id>/issue` `{"issues": [...]}` (≤ 50 per call) |
| | Move issues back to backlog | REST | `POST /rest/agile/1.0/backlog/issue` `{"issues": [...]}` |
| | Issues in a sprint | MCP | JQL `project = EA AND sprint = <id>` (or `sprint in openSprints()`) |
| | Link issue to epic | MCP | `editJiraIssue` `fields: {"parent": {"key": "EA-3"}}` |
| | Epic progress | MCP | JQL `parent = EA-3` with fields `status, labels` → aggregate (see below) |
| Collaboration | Comment (markdown) / edit comment | MCP | `addCommentToJiraIssue` (`contentFormat: markdown`; `commentId` to edit) |
| | Upload attachment | REST | `jira-rest.sh upload EA-41 <file>` |
| | Issue link (Blocks, Relates, Duplicate, Cloners) | MCP | `createIssueLink` (direction rules in jira-conventions.md); types via `getIssueLinkTypes` |
| | Remove issue link | REST | `DELETE /rest/api/3/issueLink/<linkId>` (id from `getJiraIssue` field `issuelinks`) |
| | Read remote links | MCP | `getJiraIssueRemoteIssueLinks` |
| | Create remote link (web / Confluence URL) | REST | `POST /rest/api/3/issue/EA-85/remotelink` |
| Fields | Issue types of EA | MCP | `getJiraProjectIssueTypesMetadata` |
| | Fields of an issue type (ids, schema, allowed values) | MCP | `getJiraIssueTypeMetaWithFields` with `requiredFieldsOnly: false` |
| | Search fields by keyword | REST | `GET /rest/api/3/field/search?query=story%20point&type=custom` |
| | All fields | REST | `GET /rest/api/3/field` |
| Batch | Changelogs for many issues | REST | `POST /rest/api/3/changelog/bulkfetch` |
| | Bulk edit (labels, priority, parent, sprint) | MCP (parallel) / REST | See "Bulk operations" below |

## Recipes

### Delete

1. Only on an explicit request naming the issue(s).
2. Show for each issue: summary, status, subtasks, links, and what depends on it (`issueBlocks`). Get a final "yes".
3. `jira-rest.sh DELETE "/rest/api/3/issue/EA-99?deleteSubtasks=true"` (quote the path because of `?`).
4. Fix the Dependencies lines of linked tickets and `docs/backlog/backlog.md`.
5. Prefer closing (transition to Done + label `wont-do`) when the user only wants it gone from the board.

### Batch create

- Default: parallel `createJiraIssue` calls, ≤ 10 per message, **epics first**, then children with `additional_fields.parent`, then links. Keep a code → key table and report failures.
- REST alternative for many simple issues (no long description): `POST /rest/api/3/issue/bulk` with `{"issueUpdates": [{"fields": {"project": {"key": "EA"}, "issuetype": {"name": "Task"}, "summary": "...", "labels": ["sp-3"]}}]}` (≤ 50). In REST v3 the description must be ADF — set descriptions afterwards with `editJiraIssue` (markdown).

### Sprints

Team-managed projects need **Project settings → Features → Sprints** turned on; if the sprint endpoints return an error saying the board does not support sprints, ask the user to enable it.

```bash
J=".claude/skills/jira-ticket-management/scripts/jira-rest.sh"
bash $J GET "/rest/agile/1.0/board?projectKeyOrId=EA"
bash $J POST /rest/agile/1.0/sprint '{"name":"EA Sprint 1","originBoardId":<boardId>,"goal":"Stack decided; dataset; X1-X15 settled","startDate":"2026-10-19T09:00:00.000+07:00","endDate":"2026-10-30T18:00:00.000+07:00"}'
bash $J POST /rest/agile/1.0/sprint/<id>/issue '{"issues":["EA-11","EA-12","EA-13"]}'
bash $J POST /rest/agile/1.0/sprint/<id> '{"state":"active"}'     # start (dates must be set)
bash $J POST /rest/agile/1.0/sprint/<id> '{"state":"closed"}'     # close
```

Sprint names: `EA Sprint <n>`. Keep the `sprint-N` label in sync (it is the fallback when sprints are unavailable) and update the sprint table in `docs/backlog/backlog.md`.

### Epic progress

JQL `project = EA AND parent = EA-3` with fields `status,labels` → sum `sp-N` per status category (To Do / In Progress / Done) → report `done SP / total SP`, % and the open blockers. For large results saved to a file, aggregate with `node -e`.

### Remote links

```bash
bash $J POST /rest/api/3/issue/EA-85/remotelink '{"globalId":"canvas-ei-ai-prototype-ui","object":{"url":"https://claude.ai/artifact/4YiSppZaEbjh9C5YSMgHUF","title":"ei-ai Prototype UI (design canvas)"}}'
```

`globalId` makes the call idempotent (posting again updates the same link). Use the page URL for Confluence pages.

### Changelogs

```bash
bash $J POST /rest/api/3/changelog/bulkfetch '{"issueIdsOrKeys":["EA-11","EA-12"],"maxResults":1000}'
```

Fallback per issue: `GET /rest/api/3/issue/EA-11/changelog?maxResults=100`. Use it for "what changed since…" reports and to audit bulk edits.

### Bulk operations

1. Select the set with JQL; show the list (key, summary, current value → new value).
2. Get approval (always for > 5 issues).
3. Apply with parallel `editJiraIssue` calls (≤ 10 per message); for labels read-merge-write each issue.
4. Verify with the same JQL and report successes and failures.

### Custom fields and value formats

Discover the field id with `getJiraIssueTypeMetaWithFields` (`requiredFieldsOnly: false`) or `field/search`, then format the value by its `schema`:

| schema.type | Value format |
|---|---|
| string | `"text"` |
| number | `5` |
| option | `{"value": "Option A"}` |
| array of option | `[{"value": "A"}, {"value": "B"}]` |
| array of string (labels) | `["a", "b"]` |
| user | `{"accountId": "<id>"}` |
| date / datetime | `"2026-10-19"` / `"2026-10-19T09:00:00.000+0700"` |
| priority | `{"name": "High"}` |
| issuelink / parent | `{"key": "EA-3"}` |

Check `allowedValues` before writing an option. If Jira answers "Field cannot be set… not on the appropriate screen", the field is not on the issue type's screen — tell the user where to add it (team-managed: Project settings → Issue types → <type> → add field). Story points: once "Story point estimate" is on the screen, set it with its custom field id and keep the `sp-N` label in sync.
