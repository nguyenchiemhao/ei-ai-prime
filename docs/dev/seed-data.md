# Seed data

The demo seed fills a local or test database with two fictional Organizations so every screen has realistic data and the tenant isolation can be tried by hand. The manifests in `backend/src/ei_ai/seed/data/*.json` (one per Organization) are the source of truth; this file lists them, and the check `scripts/checks/seed-data.test.mjs` (part of `npm test` and CI) fails when the two disagree.

## Seed and reset

```
npm run seed
```

- It runs `ei-ai seed demo` inside the API container. It refuses to run unless the environment is `local` or `test` (exit code 2, before any setting is read or the database is touched).
- It is idempotent: it creates only what is missing and never changes or deletes an existing row, so a second run writes nothing (`already present`, `Audit events written: 0`) and a password a user has changed is kept.
- For a clean demo, `npm run reset` deletes the local database; then run `npm run up` and `npm run seed` again.

## Shared test password

Every seeded account that has a password signs in with the same value: `Pass@123`. It comes from the variable `EI_AI_SEED_PASSWORD` (the default is in `.env.example`; set it in `.env` to use another value). The value is applied only to accounts that have no password yet; after changing it, or after setting a password through a link on a seeded account, run `npm run reset && npm run up && npm run seed`. The seed stores it hashed like any other credential and never prints it; its output says only `Shared test password applied to <n> of <m> accounts`.

The value is a local and test convenience, not a secret. A user who sets or changes a password through the product still needs at least 12 characters; the shared value is shorter than that, so the product would reject it as a new password.

## Sign-in and Organizations

- Sign in at http://localhost:3000 (the port is `ADMIN_PORT` in `.env`; 3000 by default) with an email from the tables below and the shared password. You land on the Dashboard of the account's default Workspace.
- There is no Organization switcher. Each Organization is demoed with its own account: `sysadmin@mekongdevworks.example` always opens Mekong Devworks, and Sông Hàn Retail is demoed with Ngân Trịnh (`ngan.trinh@songhanretail.example`).
- The sysadmin is a member of both Organizations, but its Sông Hàn Retail membership has no password, so the shared password can never sign in to Sông Hàn Retail through that email.
- The seed prints no set-password links. When you need one (for example to try the set-password screen), run `docker compose exec -T api ei-ai user link --org <organization-id> --email <email>`.
- `platform_admin` is planned, not stored (by decision for this ticket): the sysadmin gets Org Owner and Workspace Admin memberships everywhere instead.

## Mekong Devworks

Organization id: `0192a000-0000-7000-8000-00000000ea21`

### Workspaces

| Workspace | Members | Collections |
|---|---|---|
| People Ops | 7 | 6 |
| Engineering | 4 | 2 |

### Accounts

| Name | Email | Organization role | Role in People Ops | Role in Engineering | Shared password | What it can do |
|---|---|---|---|---|---|---|
| Linh Tran | linh.tran@mekongdevworks.example | `org_admin` | `workspace_admin` | — | yes | manages the Organization and sees every Workspace in it; administers the Workspace |
| Minh Pham | minh.pham@mekongdevworks.example | — | `builder` | — | yes | builds assistants and agents in the Workspace |
| Thao Nguyen | thao.nguyen@mekongdevworks.example | — | `knowledge_editor` | — | yes | edits collections and documents in the Workspace |
| Quang Le | quang.le@mekongdevworks.example | — | `developer` | `workspace_admin` | yes | builds integrations and API keys in the Workspace; administers the Workspace |
| Hà Vũ | ha.vu@mekongdevworks.example | — | `reviewer` | — | yes | reviews answers and content in the Workspace |
| Son Hoang | son.hoang@mekongdevworks.example | — | `viewer` | — | yes | reads what the Workspace shares |
| Duy Lâm | duy.lam@mekongdevworks.example | `org_owner` | — | — | yes | owns the Organization (everything an Org Admin can do, plus ownership) |
| Vy Huỳnh | vy.huynh@mekongdevworks.example | — | — | `developer` | yes | builds integrations and API keys in the Workspace |
| Phúc Lương | phuc.luong@mekongdevworks.example | — | — | `knowledge_editor` | yes | edits collections and documents in the Workspace |
| Trung Võ | sysadmin@mekongdevworks.example | `org_owner` | `workspace_admin` | `workspace_admin` | yes | Platform sysadmin: Org Owner and Workspace Admin everywhere; `platform_admin`: planned, not stored |

### Collections

| Workspace | Collection | Subtitle | Who can read | Groups | Data handling |
|---|---|---|---|---|---|
| People Ops | Company & Careers | — | `public` | — | Any model |
| People Ops | Employee Handbook | — | `authenticated` | — | Any model |
| People Ops | Engineering Standards | — | `authenticated` | — | Any model |
| People Ops | IT & Security | — | `authenticated` | — | Any model |
| People Ops | Manager Handbook | — | `restricted` | `managers` | Local model only |
| People Ops | Project Falcon | Client: Japan · under NDA | `restricted` | `project-falcon` | Local model only |
| Engineering | Architecture Decisions | — | `authenticated` | — | Any model |
| Engineering | Runbooks | — | `restricted` | `on-call` | Local model only |

### Folders

| Workspace | Collection | Folder |
|---|---|---|
| People Ops | Company & Careers | About Mekong Devworks |
| People Ops | Company & Careers | Hiring process |
| People Ops | Company & Careers | Candidate FAQ |
| People Ops | Employee Handbook | Policies |
| People Ops | Employee Handbook | Policies / Leave & time off |
| People Ops | Employee Handbook | Policies / Working hours & overtime |
| People Ops | Employee Handbook | Policies / Remote work & business travel |
| People Ops | Employee Handbook | Benefits |
| People Ops | Employee Handbook | Benefits / Allowances |
| People Ops | Employee Handbook | Benefits / Insurance & health care |
| People Ops | Employee Handbook | Onboarding & offboarding |
| People Ops | Employee Handbook | Onboarding & offboarding / First week |
| People Ops | Employee Handbook | Onboarding & offboarding / Leaving the company |
| People Ops | Employee Handbook | Templates |
| People Ops | Employee Handbook | Templates / HR forms |
| People Ops | Employee Handbook | Templates / Contracts |
| People Ops | Employee Handbook | Templates / Contracts / Labor contracts |
| People Ops | Engineering Standards | Coding conventions |
| People Ops | Engineering Standards | Code review |
| People Ops | Engineering Standards | Definition of Done |
| People Ops | IT & Security | Accounts & access |
| People Ops | IT & Security | Devices & equipment |
| People Ops | IT & Security | Security policies |
| People Ops | Manager Handbook | Performance reviews |
| People Ops | Manager Handbook | Hiring & approvals |
| People Ops | Project Falcon | Requirements |
| People Ops | Project Falcon | Meeting notes |
| People Ops | Project Falcon | Delivery |
| Engineering | Architecture Decisions | Accepted |
| Engineering | Architecture Decisions | Superseded |
| Engineering | Runbooks | Incidents |
| Engineering | Runbooks | Incidents / Postmortems |
| Engineering | Runbooks | Deployments |

## Sông Hàn Retail

Organization id: `0192a000-0000-7000-8000-00000000ea94`

### Workspaces

| Workspace | Members | Collections |
|---|---|---|
| Customer Care | 2 | 1 |

### Accounts

| Name | Email | Organization role | Role in Customer Care | Shared password | What it can do |
|---|---|---|---|---|---|
| Ngân Trịnh | ngan.trinh@songhanretail.example | `org_admin` | `workspace_admin` | yes | manages the Organization and sees every Workspace in it; administers the Workspace |
| Trung Võ | sysadmin@mekongdevworks.example | `org_owner` | `workspace_admin` | no | Platform sysadmin: Org Owner and Workspace Admin everywhere; `platform_admin`: planned, not stored. Membership only, no password here |

### Collections

| Workspace | Collection | Subtitle | Who can read | Groups | Data handling |
|---|---|---|---|---|---|
| Customer Care | Store Policies | — | `authenticated` | — | Any model |

### Folders

| Workspace | Collection | Folder |
|---|---|---|
| Customer Care | Store Policies | Returns & exchanges |
| Customer Care | Store Policies | Delivery & installation |
| Customer Care | Store Policies | Warranty |

## Not seeded yet

Documents and their contents, Answer Scripts, Assistants, Channels, Skills, API keys, connectors, evaluation runs, conversations, the `platform_admin` role and a second sysadmin credential are not seeded. The collections are empty apart from their folders.

## Extending the seed

A ticket that adds a seedable feature extends the manifests in `backend/src/ei_ai/seed/data/` (keep ids, names and emails of existing rows unchanged; only add) and this file in the same change. `scripts/checks/seed-data.test.mjs` compares the tables here with the manifests; run it with `node --test scripts/checks/seed-data.test.mjs`.
