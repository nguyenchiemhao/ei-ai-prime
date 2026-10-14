# Architecture documents

| Document | Status | Ticket |
|---|---|---|
| [adr-001-tech-stack.md](adr-001-tech-stack.md) — tech stack and overall architecture | Accepted (2026-10-14) | EA-11 (SET-01) |
| [oss-license-review.md](oss-license-review.md) — binding approved-libraries list | Proposed | EA-12 (SET-02) |

Check for the licence review (structure and agreement with the ADR; no network, no dependencies): `node --test docs/architecture/checks/oss-license-review.test.mjs`.

The runnable proof for ADR-001 (tenant isolation and one-command infrastructure start) is in `poc/stack-spike/`.
