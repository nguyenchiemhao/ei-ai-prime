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
