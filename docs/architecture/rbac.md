# Roles and permissions (3-tier RBAC)

Status: built in EA-23 (FND-06). Decisions: D48 (roles), D46 (tenant isolation), D32 (identity from the token), D50 (audit), D6 (the Platform Admin never sees business data).

Code: `backend/src/ei_ai/rbac/` (`roles.py`, `permissions.py`, `access.py`, `declarations.py`). The matrices below are compared with the code by `backend/tests/rbac/test_matrix.py`, and the admin app matrix (`apps/admin/src/members/matrixData.ts`) by `RoleMatrix.test.tsx`; change code and documents together.

## Tiers

| Tier | Roles | Scope |
|---|---|---|
| Platform | `platform_admin`, `platform_support`, `billing` | The platform plane (CLI today). No role of this tier holds a permission inside an Organization. |
| Organization | `org_owner`, `org_admin` | One Organization (`memberships.org_role`). |
| Workspace | `workspace_admin`, `developer`, `builder`, `knowledge_editor`, `reviewer`, `viewer` (assignable), `member` | One Workspace (`workspace_memberships.role`). A user holds at most one role per Workspace. |

Rules:

- An **Org Owner or Org Admin acts as Workspace Admin in every Workspace of the Organization**, without a Workspace membership. Neither ever gets `conversations.read`: an Admin who needs to read conversations assigns themselves Reviewer, and that change is audited.
- The effective permissions of a user in a Workspace are the **union** of the grants of the user's Organization role and Workspace role. An unknown role code grants nothing (fail closed).
- Only an **Org Owner** changes Organization roles (`org.roles.manage`, API only). The last Org Owner cannot be demoted (409 `last_org_owner`). Nobody can raise themselves to Org Owner.
- `member` (the chat-only role) holds only `workspace.access` and is not assignable on the Members & roles screen (EA-89).
- A user who is not in a Workspace and holds no Organization role gets 404 `not_found` for it, exactly like an unknown Workspace id (no existence oracle). A member lacking the permission gets 403 `forbidden`.
- Permissions are read per request inside the tenant transaction (one indexed query); there is no per-session cache, so a role change applies from the next request (NFR: within 60 s).

## What each role can do (Members & roles matrix)

The eight rows shown on the Members & roles screen, in artboard order. Sensitive rows (publish, connectors, read conversations) are highlighted in the UI.

<!-- rbac-matrix:start -->
| Permission | Code | Admin | Developer | Builder | Knowledge Editor | Reviewer | Viewer |
|---|---|---|---|---|---|---|---|
| Documents, scripts, glossary | `knowledge.manage` | Yes | — | Yes | Yes | — | — |
| Assistants, skills, channels | `assistants.manage` | Yes | — | Yes | — | — | — |
| Playground (test drafts, see traces) | `playground.use` | Yes | — | Yes | — | — | — |
| Publish an assistant | `assistants.publish` | Yes | — | Yes | — | — | — |
| Connectors, secrets, signing keys | `connectors.manage` | Yes | Yes | — | — | — | — |
| Read conversations | `conversations.read` | — | — | — | — | Yes | — |
| Change who can read a collection | `collections.access.manage` | Yes | — | — | — | — | — |
| Dashboard | `dashboard.view` | Yes | Yes | Yes | Yes | Yes | Yes |
<!-- rbac-matrix:end -->

## Full grants

Every permission against every role code. Org Owner and Org Admin hold the Workspace Admin set in every Workspace plus their Organization permissions.

<!-- rbac-grants:start -->
| Permission | Scope | workspace_admin | developer | builder | knowledge_editor | reviewer | viewer | member | org_owner | org_admin |
|---|---|---|---|---|---|---|---|---|---|---|
| `workspace.access` | workspace | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `dashboard.view` | workspace | Yes | Yes | Yes | Yes | Yes | Yes | — | Yes | Yes |
| `knowledge.manage` | workspace | Yes | — | Yes | Yes | — | — | — | Yes | Yes |
| `assistants.manage` | workspace | Yes | — | Yes | — | — | — | — | Yes | Yes |
| `playground.use` | workspace | Yes | — | Yes | — | — | — | — | Yes | Yes |
| `assistants.publish` | workspace | Yes | — | Yes | — | — | — | — | Yes | Yes |
| `connectors.manage` | workspace | Yes | Yes | — | — | — | — | — | Yes | Yes |
| `conversations.read` | workspace | — | — | — | — | Yes | — | — | — | — |
| `collections.access.manage` | workspace | Yes | — | — | — | — | — | — | Yes | Yes |
| `members.view` | workspace | Yes | Yes | Yes | Yes | Yes | Yes | — | Yes | Yes |
| `members.manage` | workspace | Yes | — | — | — | — | — | — | Yes | Yes |
| `org.settings.manage` | org | — | — | — | — | — | — | — | Yes | Yes |
| `org.roles.manage` | org | — | — | — | — | — | — | — | Yes | — |
| `platform.organizations.list` | platform | — | — | — | — | — | — | — | — | — |
<!-- rbac-grants:end -->

`platform.organizations.list` belongs to `platform_admin` (metadata only: name and creation date, never business data, D6). No platform HTTP API exists yet (the platform plane is the CLI), so no endpoint declares it. Platform Support and Billing hold nothing yet.

## Sidebar mapping

The admin Sidebar shows an area when the caller holds any permission listed for it, and hides empty groups. The API checks the same permissions; hiding is a convenience, never the control.

| Area | Shown with any of |
|---|---|
| Dashboard | `dashboard.view` |
| Assistants | `assistants.manage` |
| Knowledge, Answer Scripts, Glossary | `knowledge.manage` |
| Skills & Connectors, Channels | `assistants.manage`, `connectors.manage` |
| Conversations, Unanswered | `conversations.read` |
| Members & roles | `members.view` |
| Organization | `org.settings.manage` |

## Declaring the permission of a route

Every route declares exactly one permission through a dependency from `ei_ai.rbac.declarations`:

- `requires(Permission.X)` for a Workspace route (path parameter `workspace_id`): 404 `not_found` when the caller cannot see the Workspace, 403 `forbidden` when the caller lacks `X`; returns the caller's `WorkspaceAccess`.
- `requires_org(Permission.X)` for an Organization route: 403 `forbidden` when the caller lacks `X`.
- `signed_in()` for a route that needs a session and nothing more (the caller's own data).
- `public("<reason>")` for a route without identity (probes, sign-in).

The service layer checks the permission again (`ensure`) before it changes data. A new route also needs an entry in `backend/tests/rbac/route_permissions.py` (the reviewed route table) and in the isolation cases; CI fails on an undeclared route and on a declaration that differs from the reviewed table. The generated role x endpoint test (`tests/integration/rbac/test_role_endpoint_matrix.py`) then runs the new route as every role.

## How the sensitive rules are proven today (R1)

Most endpoints behind the sensitive permissions do not exist yet (conversations, connector secrets, signing keys, publish). The collection access route exists (`PUT /workspaces/{workspace_id}/collections/{collection_id}/access`, `collections.access.manage`, EA-32): it is in the reviewed route table and runs in the generated role x endpoint test. Until the others land, the matrix tests pin who holds the four permissions, test-only probe routes carry those permissions through the generated role x endpoint test, and the reviewed route table forces each future route to declare its permission, so it is tested the day it is added.

## Decisions

- Q1: one Workspace role per Workspace (the schema allows one row per user and Workspace); effective permissions are the union with the Organization role. The footnote still works: an Org Admin who sets their own role to Reviewer keeps the Org Admin rights and gains `conversations.read`.
- A1: `members.manage` is held by Workspace Admin (own Workspace) and Org Owner/Admin (all Workspaces).
- A2: only an Org Owner changes Organization roles.
- A3: Org Owner/Admin see every Workspace of the Organization; the role shown is null without a membership. The default Workspace is the earliest membership, else the first Workspace by `(created_at, id)`.
- A4: no per-session permission cache; the UI re-checks on every area or Workspace change.
- A5: an invitation creates the user, the memberships and an unused set-password token; nothing is returned or printed. The person gets the link through "Forgot password" or `ei-ai user link`.
- A6: revoking a Workspace membership is a `DELETE` route only (tested); the screen has no remove control.
- A7: the Organization role is shown as a third line in the Member cell, not as a column.
- A8: a caller without an Organization role cannot take their own management right away (the API answers 403 `forbidden` to a self-change that drops `members.manage`, or to removing themselves); the screen shows their own row as text. With an Organization role the row is editable, which enables the self-assign Reviewer step.
- A9: the unanswered-questions area requires `conversations.read` until its own ticket decides otherwise.
- A10: `member` is not assignable here (422); it is shown as text.
