# QA test cases

Reusable black-box test cases, one file per ticket, written by the QA agents (`qa-e2e`, `deliver-qa`) at the end of a ticket's QA run. Use them to re-check a feature later, by hand or with the saved scripts.

Each file `docs/qa/<area>/EA-<n>-<slug>.md` holds:
- purpose, preconditions and test data;
- how to run: the Playwright spec (`e2e/<area>/EA-<n>-<slug>.spec.ts`) and the scripts (`e2e/<area>/scripts/EA-<n>-<slug>-<purpose>.mjs`);
- a cases table: `TC | AC | automated / exploratory | steps | expected | spec or script`;
- every exploratory flow as numbered steps a person can follow.

Test data rule: every case creates its own data with a unique marker (`qa-EA<n>-<run>`) and removes it afterwards; the demo Organization and seed rows are never changed. No secrets, tokens, one-time links or real personal data in these files.

## Index

| Ticket | Area | File | Spec | Scripts |
|---|---|---|---|---|
| EA-32 | knowledge | [knowledge/EA-32-collections-folders.md](knowledge/EA-32-collections-folders.md) | `e2e/knowledge/EA-32-collections.spec.ts`, `e2e/knowledge/EA-32-collections-perf.spec.ts` | `e2e/knowledge/scripts/EA-32-collections-explore-data.mjs` |
| EA-94 | foundation | [foundation/EA-94-demo-seed.md](foundation/EA-94-demo-seed.md) | `e2e/foundation/EA-94-demo-seed.spec.ts`, `e2e/foundation/EA-94-seed-perf.spec.ts` | `e2e/foundation/scripts/EA-94-demo-seed-explore.mjs`, `e2e/foundation/scripts/EA-94-demo-seed-check-state.mjs` |
