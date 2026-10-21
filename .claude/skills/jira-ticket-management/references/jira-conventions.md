# Jira conventions — project EA

## Connection

| Item | Value |
|---|---|
| Site | https://nguyenchiemhao2205.atlassian.net |
| cloudId | `71bb307d-8749-442a-86d4-969021d4b921` |
| Project | `EA` (team-managed, name "ei-ai") |
| Board / issues | https://nguyenchiemhao2205.atlassian.net/jira/software/projects/EA/issues |

## Issue types

| Type | Use |
|---|---|
| Epic | Business capability / milestone (E0–E9) |
| Story | User-facing or enabler work with AC |
| Task | Spikes (label `spike`), admin/legal work, design work |
| Bug | Defects |
| Subtask | Only if the user asks for a breakdown |

There is no Spike issue type → **Task + label `spike`**.

## Fields

| Field | Rule |
|---|---|
| Summary | `[CODE] <action phrase>` in English, e.g. `[KB-02] Upload and process PDF/DOCX/MD/TXT into normalised chunks` |
| Description | Markdown via `contentFormat: "markdown"`; template in `story-template.md`; **no markdown image syntax** |
| Comments | Markdown; short, tables for lists and comparisons; pipeline comments (plan, final, Blocked) use `comment-templates.md`. Subagents have no Jira access: the Lead posts them |
| Priority | Highest, High, Medium, Low (field works) |
| Story points | The Story Points field is **not on the screen** → label `sp-N` (`sp-1`, `sp-3`, `sp-5`, `sp-8`, `sp-13`) and the header line of the description. Backfill the field from labels if it gets enabled |
| Parent | Epic key (`parent: "EA-3"`) |
| Labels | lowercase, hyphenated |

## Labels

| Label | Meaning |
|---|---|
| `sp-N` | Story points |
| `prototype` / `mvp` | Phase |
| `spike` | Time-boxed investigation |
| `proposed` | Not in the source docs; suggested by the team |
| `approved` | Owner approved a proposal on this ticket |
| `deferred` | Postponed; description says why and when to resume |
| `local-env` | Runs only in the local integration environment (demo site, mocks) |
| `sprint-N` | Planned sprint |
| `M0`…`M5`, `M3b` | Milestone (on epics) |
| `enabler` | Technical enabler with indirect user value |
| Module labels | `foundation`, `security`, `kb`, `rag`, `widget`, `pipeline`, `jev`, `skill`, `connector`, `admin-ui`, `eval`, `design`, `ui`, `privacy`, `rbac`, `observability`… |

## Links

| Type | Direction in `createIssueLink` |
|---|---|
| Blocks | `inwardIssue` = the issue that **blocks**, `outwardIssue` = the issue that **is blocked** ("A is blocked by B" → inward B, outward A) |
| Relates | either direction; for design links use inward `EA-85`, outward the UI ticket |
| Duplicate | when merging tickets |

Link direct dependencies only (no transitive Blocks). Keep the Dependencies line in the description in sync with the links.

## Codes → epics

| Prefix | Epic | Key |
|---|---|---|
| SET, DSN | E0 Tech foundation, tech stack & UI design | EA-1 |
| FND | E1 Multi-tenant, security & observability foundations (M0) | EA-2 |
| KB | E2 Knowledge Base & permission-aware RAG (M1) | EA-3 |
| WGT | E3 Widget & Channel (M2) | EA-4 |
| PIPE | E4 5-step pipeline & Answer Scripts (M3) | EA-5 |
| JEV | E5 Jev Decision Provider (M3b) | EA-6 |
| SKL | E6 Thin slice of Skills & Connectors (M4) | EA-7 |
| ADM | E7 Assistant configuration & operations (M5) | EA-8 |
| EVL | E8 Quality evaluation & test data | EA-9 |
| MVP | E9 MVP hardening (after the prototype; also holds deferred SET-05) | EA-10 |

The full code → key map is in `docs/backlog/backlog.md`. New codes continue the sequence of their prefix (next WGT is WGT-12, etc.).

## Workflow

Statuses (all transitions are global): To Do, In Progress, In Review, Human Review, Blocked, Done, Close. Always list transitions with `getTransitionsForJiraIssue` before transitioning.

| Status | Use |
|---|---|
| In Review | Committed on the ticket branch, not merged yet |
| Human Review | Merged, but an AC or the DoD still needs a person (owner review, human labellers); the comment lists the owner actions |
| Blocked | Cannot move because of something the team cannot fix or decide; the comment gives reason, root cause, owner action, impact, resume command. Its status category is To Do, so selection JQL must exclude `status = Blocked` |
| Done | Every AC has evidence, the DoD is met and the branch is merged |

## Sprints

- Name: `EA Sprint <n>`; goal in English, one sentence; 2-week cadence unless the owner changes it.
- Real sprints need REST credentials and the Sprints feature enabled on the team-managed project; otherwise use the `sprint-N` label fallback.
- Keep `sprint-N` labels and the sprint table in `docs/backlog/backlog.md` in sync with Jira sprints.

## Tool tips

- Large JQL results get saved to a file; parse them with `node` (Python is not available on this machine; Node is v14, so no global `fetch`).
- Ask for only the fields you need; descriptions are long (~3–6 KB each).
- `editJiraIssue` replaces the whole description and the whole `labels` list — always start from the current values.
- REST calls go through `scripts/jira-rest.sh`; quote paths containing `?` or `&`.
