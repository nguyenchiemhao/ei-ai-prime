# Cross-labelling agreement report — Mekong Devworks test set

Date: 2026-10-14. All data in this folder is fictional (see `README.md`).

## 1. Method

- Sample: 100 of the 430 questions, drawn with a seeded shuffle (mulberry32, seed 16, Fisher–Yates, first 100 ids sorted). The ids are in `cross_labelling/sample.json`.
- Blind sheet: the 100 questions are shuffled again (seed 160) and every row gets an opaque key `r-001` ... `r-100`. The sheet `cross_labelling/blind_sheet.csv` shows key, language, history and question only: no id, no group, no label. The map from key to question id (`cross_labelling/key_map.json`) is kept apart and was not given to the labeller.
- Labeller 1 — dataset author, developer agent claude-sonnet-5-5. Its labels are the dataset labels after the fixes of reviews 1 and 2, frozen as `cross_labelling/labeller_1_author.csv` before run 3 started (identical to the snapshot of run 2: nothing was relabelled between the runs).
- Labeller 2 — independent agent claude-opus-5-5, a separate agent with a fresh context and a different model from labeller 1. It received only copies of `labeling_guide.md` (guide version 1.2), the script catalogue (id, title and example questions in both languages; no answers) and the blind sheet, in a folder outside the repository, and reported that it opened nothing else. It wrote `cross_labelling/labeller_2_llm.csv` with the columns `key,type,correct_script,note`; the file is never edited.
- Agreement is computed by `node eval/datasets/mekong-devworks/tools/cross-labelling.mjs agreement cross_labelling/labeller_1_author.csv cross_labelling/labeller_2_llm.csv`. The tool first checks both files (header, one row per key, no blank, unknown or duplicate rows, exact label values), then joins them through the key map. The result is in `cross_labelling/agreement.json`, computed on the raw files before any decision below.
- Run 1 is superseded. It used a blind sheet sorted by question id, and ids were contiguous per group, so a labeller could infer the group from the position of a row (review R1-1). It reported 100.00% agreement and kappa 1.00 for type, correct script and both, with 0 disagreements. Its files are archived unchanged in `cross_labelling/run-1/`; it is not evidence for the labels.
- Run 2 is superseded. It fixed the row order but used guide version 1.1, whose examples were near-copies of sampled questions and carried their labels (review R2-1). The affected rows were q-0006 (r-029), q-0293 (r-086), q-0402 (r-004), q-0416 (r-100) and q-0421 (r-034), that is 5 of the 100, on the task/information and data/NONE boundaries. It reported 100.00% agreement and kappa 1.00 for type, correct script and both, with 0 disagreements. Its files are archived unchanged in `cross_labelling/run-2/`; it is not evidence for the labels either. Guide version 1.2 rewrote every example and a check (`tools/guide-check.mjs`, run by the test suite) now guards against copies; translations of a question cannot be detected automatically and were checked by hand.

## 2. Results

Run 3 (opaque shuffled keys, guide version 1.2):

| Field | n | Percent agreement | Cohen's kappa |
|---|---|---|---|
| type | 100 | 100.00 | 1.00 |
| correct_script | 100 | 99.00 | 0.99 |
| both | 100 | 99.00 | 0.99 |

`both` counts a question as agreed only when type and correct script are both identical; its kappa is computed on the combined label.

Sample composition by group: A 27, B 17, C 15, D 12, E 6, F 4, G 11, H 8.

Sample composition by type: information 62, task 14, data 3, out_of_scope 6, greeting 2, handoff 2, follow_up 11.

## 3. Disagreements

One disagreement out of 100 questions (key r-053, in `cross_labelling/key_map.json`).

| Id | Labeller 1 | Labeller 2 | Resolution | Guide change |
|---|---|---|---|---|
| q-0081 | information, laptop-request | information, NONE | keep | none |

Question q-0081: "How often is my work laptop replaced?". Labeller 2 noted: "Replacement cycle policy; laptop-request is a possible alternative."

Decision: keep. Under guide section 5 the label is the script a reasonable colleague would send as the helpful reply, and the `laptop-request` answer states the rule ("Laptops are replaced after 3 years, or earlier if IT confirms a hardware fault"). The guide is not unclear here; the disagreement comes from the labeller's input. The catalogue shows titles and example questions but not the script answers, so labeller 2 could not see that the answer covers the replacement cycle and chose `NONE`. The same limitation explains the uncertainty it noted for r-005 (the 3-working-day security review is in the `software-install-request` answer; both labellers still chose that script). No guide change and no relabelling. For the human pass the labellers should get the script answers as well (section 6).

### 3.1 Labeller notes (no disagreement)

Labeller 2 added notes to three more rows, where it chose the same labels as labeller 1.

| Id | Key | Question | Labels (both labellers) | Labeller 2 note | Decision |
|---|---|---|---|---|---|
| q-0088 | r-005 | How long does the security review of new software take? | information, software-install-request | Approval timing may not be covered by the script; could be NONE. | keep: the answer of the script states the 3-working-day review |
| q-0298 | r-011 | Gửi lời mời họp retro chiều thứ Sáu cho cả nhóm | task, NONE | Generic calendar action rather than out_of_scope; no script. | keep: a team meeting invite is a work action, and guide section 4 rule 3 reserves `out_of_scope` for requests that are off-topic for every company; labeller 2 reached the same labels |
| q-0046 | r-049 | Sau chuyến công tác bao lâu thì phải quyết toán khoản tạm ứng? | information, business-trip-advance | Settling an advance could also fall under business-trip-expense-claim. | keep: the 10-working-day settlement rule is in the advance script; the same note was made in runs 1 and 2 |

## 4. Label-definition changes

No label-definition change came from the cross-labelling itself. Two came from code review 1 and are recorded here, with a row each in the change log of `labeling_guide.md`:

| Review finding | Change in the guide | Questions relabelled or replaced |
|---|---|---|
| R1-2 | Sections 3 and 4 (rule 5): a statement of what the user wants or needs done, or a bare request, without a how/where/when/who question is `task`. "Can this be done?" questions and "I want to know ..." stay `information`. | q-0159, q-0161, q-0162, q-0182, q-0217, q-0223, q-0427 changed from `information` to `task` (q-0161 was also reworded to remove a near-copy of an example). |
| R1-3 | Section 5: a question about the user's own value gets the script that tells where to look it up (payslip, application status); if no script does, `NONE`. | q-0027 kept as `payday-payslip`; the inconsistent group D items q-0268 and q-0292 were replaced by own-value questions that have no lookup script (`NONE`). |

Review 2 (R2-1) added one more change-log row: every example in the guide was reworded so that none copies a test question (version 1.2); the rules and all labels are unchanged.

Both inconsistencies of R1-2 and R1-3 were found by review in questions that both labellers had labelled alike in run 1, which is why cross-labelling alone could not catch them: two labellers who apply the same reading agree even when the reading is inconsistent across the data set.

## 5. Limitations

- Both labellers are LLMs from the same vendor (Anthropic) and read the same guide, so the agreement is likely overstated compared with two people. 100.00% / kappa 1.00 on type and 99.00% / kappa 0.99 on the script, between two such models, is weak evidence: it shows that guide version 1.2 is clear enough for models to apply on this sample, not that the labels are right or that people would agree.
- The composition (section 2) limits what the sample can show. Only 3 of 100 items are `data`, so the `data` / `NONE` boundary and the own-value rule were barely sampled. The `task` / `information` boundary was sampled with 14 `task` items, and the group F, E and G items (21 of 100) are largely fixed by the guide mechanically (greeting, handoff, out of scope, follow-up with history). The agreement is therefore mostly evidence for script choice on paraphrases, not for the hard boundaries.
- Runs 1 and 2 were invalidated (section 1); run 3 is the only run reported as a result. Language, history and the presence of personal data in a question still hint at its group, as they would for any labeller.
- The labeller catalogue contains no script answers, so questions that depend on answer content (q-0081, q-0088) cannot be judged fully by the labeller; this produced the one disagreement.
- Labeller 1's items are LLM-drafted (every question has `source: "llm-draft"`). Owner review of every item is still pending, so the data set is not reviewed yet.
- Groups A and B were not written by outsiders as the spike asks (jev-spike section 11), so the test set may be easier than real traffic; recommend a follow-up ticket for outsider-written A and B questions or anonymised real questions after the MVP.
- The notes in section 3.1 show borderline cases (advance versus claim, a script that may or may not cover a policy detail, a generic calendar action). They are few in the sample but a human pass could rate them differently.

## 6. Human cross-labelling — pending

AC5 asks for two people. This report covers the ticket's fallback (two LLM labellers). To add the human pass:

1. Copy `cross_labelling/blind_sheet.csv` to `cross_labelling/labeller_owner.csv` (owner) and `cross_labelling/labeller_outsider.csv` (a person outside the team), keeping the columns `key,type,correct_script,note`. Fill `type` (one of greeting, handoff, out_of_scope, follow_up, information, task, data, exactly as written) and `correct_script` (a script id from `scripts.jsonl` or `NONE`) using only `labeling_guide.md` and the scripts in `scripts.jsonl` (titles, example questions and, unlike the LLM run, the answers). Do not open `test_questions.jsonl` or `key_map.json`. The tool rejects blank, misspelled, duplicate or missing rows.
2. Run `node eval/datasets/mekong-devworks/tools/cross-labelling.mjs agreement cross_labelling/labeller_owner.csv cross_labelling/labeller_outsider.csv` from the repository root (and pairs against `labeller_1_author.csv`). Each pair is added to `cross_labelling/agreement.json`.
3. Add a row per pair to the table in section 2 and decide every disagreement as in section 3 (definition change, label fix or keep). Definition changes go into the change log of `labeling_guide.md`. Consider drawing a second sample that contains more `data` and `task` items, since the first one barely covers them.

Status: pending, needs the owner and one outsider.
