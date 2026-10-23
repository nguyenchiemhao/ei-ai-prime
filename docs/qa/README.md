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
| EA-20 | foundation | [foundation/EA-20-org-encryption-vectors.md](foundation/EA-20-org-encryption-vectors.md) | `e2e/foundation/EA-20-org-encryption-vectors.spec.ts`, `e2e/foundation/EA-20-crypto-perf.spec.ts` | `e2e/foundation/scripts/EA-20-org-encryption-vectors-explore.mjs`, `e2e/foundation/scripts/EA-20-org-encryption-vectors-check-state.mjs` |
| EA-32 | knowledge | [knowledge/EA-32-collections-folders.md](knowledge/EA-32-collections-folders.md) | `e2e/knowledge/EA-32-collections.spec.ts`, `e2e/knowledge/EA-32-collections-perf.spec.ts` | `e2e/knowledge/scripts/EA-32-collections-explore-data.mjs` |
| EA-33 | knowledge | [knowledge/EA-33-upload-process-documents.md](knowledge/EA-33-upload-process-documents.md) | `e2e/knowledge/EA-33-upload-process-documents.spec.ts`, `e2e/knowledge/EA-33-upload-process-documents-access.spec.ts`, `e2e/knowledge/EA-33-upload-process-documents-limits.spec.ts`, `e2e/knowledge/EA-33-upload-process-documents-perf.spec.ts` | `e2e/knowledge/scripts/EA-33-upload-process-documents-explore-data.mjs`, `e2e/knowledge/EA-33-upload-process-documents-explore-files.spec.ts` |
| EA-35 | knowledge | [knowledge/EA-35-vector-index-per-org.md](knowledge/EA-35-vector-index-per-org.md) | `e2e/knowledge/EA-35-vector-index.spec.ts`, `e2e/knowledge/EA-35-vector-index-slow.spec.ts`, `e2e/knowledge/EA-35-vector-index-perf.spec.ts` | `e2e/knowledge/scripts/EA-35-vector-index-access-lock.mjs` |
| EA-36 | knowledge | [knowledge/EA-36-permission-retrieval.md](knowledge/EA-36-permission-retrieval.md) | `e2e/knowledge/EA-36-permission-retrieval.spec.ts` | `e2e/knowledge/scripts/EA-36-permission-retrieval-hygiene.mjs` |
| EA-94 | foundation | [foundation/EA-94-demo-seed.md](foundation/EA-94-demo-seed.md) | `e2e/foundation/EA-94-demo-seed.spec.ts`, `e2e/foundation/EA-94-seed-perf.spec.ts` | `e2e/foundation/scripts/EA-94-demo-seed-explore.mjs`, `e2e/foundation/scripts/EA-94-demo-seed-check-state.mjs` |
