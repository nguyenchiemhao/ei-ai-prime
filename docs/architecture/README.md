# Architecture documents

| Document | Status | Ticket |
|---|---|---|
| [adr-001-tech-stack.md](adr-001-tech-stack.md) — tech stack and overall architecture | Accepted (2026-10-14) | EA-11 (SET-01) |
| [oss-license-review.md](oss-license-review.md) — binding approved-libraries list | Proposed | EA-12 (SET-02) |
| [data-model.md](data-model.md) — multi-tenant data model, RLS and roles | Accepted with FND-01 review | EA-18 (FND-01) |
| [model-gateway.md](model-gateway.md) — Model Gateway, pinned model catalog, egress seam, adding a model | Built | EA-24 (FND-07) |
| [rbac.md](rbac.md) — 3-tier roles, the permission matrix, how a route declares its permission | Built | EA-23 (FND-06) |

Check for the licence review (structure and agreement with the ADR; no network, no dependencies): `node --test docs/architecture/checks/oss-license-review.test.mjs`.

The runnable proof for ADR-001 (tenant isolation and one-command infrastructure start) was the EA-11 stack spike. SET-03 (EA-13) removed it from the working tree and replaced it with the real skeleton (`compose.yaml`, `backend/`, `apps/`). It stays reachable in git history at commit `2ce9f3e`: `git show 2ce9f3e:poc/stack-spike/<path>` (schema `db/init/001_schema.sql`, `src/stack_spike/tenant.py`, `src/stack_spike/search.py`, `tests/isolation/`, `README.md`).

The structure check for ADR-001 is `docs/architecture/checks/adr-001.test.mjs` (Node port of the PoC check). All Node checks run with `node scripts/run-node-checks.mjs` (and in CI).
