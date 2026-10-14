# Cross-labelling agreement report — Mekong Devworks test set

Date: 2026-10-13. All data in this folder is fictional (see `README.md`).

## 1. Method

- Sample: 100 of the 430 questions, drawn with a seeded shuffle (mulberry32, seed 16, Fisher–Yates, first 100 ids sorted). The ids are in `cross_labelling/sample.json`.
- Labeller 1 — dataset author, developer agent claude-sonnet-5-5. The labels are the ones written while drafting the data set, frozen as `cross_labelling/labeller_1_author.csv` before any fix.
- Labeller 2 — independent agent claude-opus-5-5, a separate agent with a fresh context and a different model from labeller 1.
- Blind procedure: labeller 2 received only a copy of `labeling_guide.md`, the script catalogue (id, title, set, example questions in both languages) and `cross_labelling/blind_sheet.csv` (id, language, history, question; no group, no type, no script). It reported that it read nothing else, and it never saw `test_questions.jsonl` or labeller 1's file. It wrote `cross_labelling/labeller_2_llm.csv` (the file is never edited).
- Agreement is computed by `node eval/datasets/mekong-devworks/tools/cross-labelling.mjs agreement cross_labelling/labeller_1_author.csv cross_labelling/labeller_2_llm.csv`, on the raw files, before any decision on disagreements. The result is stored in `cross_labelling/agreement.json`.

## 2. Results

| Field | n | Percent agreement | Cohen's kappa |
|---|---|---|---|
| type | 100 | 100.00 | 1.00 |
| correct_script | 100 | 100.00 | 1.00 |
| both | 100 | 100.00 | 1.00 |

`both` counts a question as agreed only when type and correct script are both identical; its kappa is computed on the combined label.

## 3. Disagreements

There are no disagreements: the two labellers gave the same type and the same correct script for all 100 questions. The table is therefore empty, and no label was changed.

| Id | Labeller 1 | Labeller 2 | Resolution | Guide change |
|---|---|---|---|---|

### 3.1 Labeller notes (no disagreement)

Labeller 2 added a note to four rows. In all four it still chose the same labels as labeller 1, so they are not disagreements. They show where the guide leaves room for doubt. Decision for each: keep the label; no guide change, because the guide already says to choose the script a reasonable colleague would send (section 5) and the choices match.

| Id | Question | Labels (both labellers) | Labeller 2 note | Decision |
|---|---|---|---|---|
| q-0015 | Who gives me my laptop and badge when I start? | information, onboarding-checklist | First-day equipment handover read as onboarding rather than laptop-request. | keep: the onboarding answer names IT as the giver on day 1 |
| q-0046 | Sau chuyến công tác bao lâu thì phải quyết toán khoản tạm ứng? | information, business-trip-advance | Settling an advance could also be covered by business-trip-expense-claim. | keep: the 10-working-day settlement rule is in the advance script |
| q-0081 | How often is my work laptop replaced? | information, laptop-request | Laptop refresh cycle may be a KB policy question (NONE). | keep: the laptop script states the 3-year replacement rule |
| q-0416 | Lan Ho (lan.ho@example.com) submitted the wrong hours last Friday. Can the timesheet be reopened? | information, timesheet-correct | Asks whether reopening is possible so read as information not task. | keep: it asks if something is possible, not to perform it |

## 4. Label-definition changes

There was no label-definition change: no disagreement showed a gap in the guide, so `labeling_guide.md` keeps version 1.0 and its change log lists only the initial version.

## 5. Limitations

- Both labellers are LLMs from the same vendor (Anthropic) and read the same guide, so the agreement is likely overstated compared with two people. A kappa of 1.00 on 100 questions says that the guide is clear enough for models to apply it consistently on this sample, not that the labels are right or that people would agree. The sample also contains many easy items (paraphrases, greetings, out-of-scope requests).
- Labeller 1's items are LLM-drafted (every question has `source: "llm-draft"`). Owner review of every item is still pending, so the ticket cannot be called reviewed yet.
- Groups A and B were not written by outsiders as the spike asks (jev-spike section 11), so the test set may be easier than real traffic; recommend a follow-up ticket for outsider-written A and B questions or anonymised real questions after the MVP.
- The 4 notes in section 3.1 show borderline cases (a laptop question that could be a KB policy question, advance versus claim). They are rare in the sample but a human pass could rate them differently.

## 6. Human cross-labelling — pending

AC5 asks for two people. This report covers the ticket's fallback (two LLM labellers). To add the human pass:

1. Copy `cross_labelling/blind_sheet.csv` to `cross_labelling/labeller_owner.csv` (owner) and `cross_labelling/labeller_outsider.csv` (a person outside the team). Fill `type` and `correct_script` using only `labeling_guide.md` and the script list in `scripts.jsonl` (titles and example questions); do not open `test_questions.jsonl`. Remove the `note` text or keep it short.
2. Run `node eval/datasets/mekong-devworks/tools/cross-labelling.mjs agreement cross_labelling/labeller_owner.csv cross_labelling/labeller_outsider.csv` (and pairs against `labeller_1_author.csv`). Each pair is added to `cross_labelling/agreement.json`.
3. Add a row per pair to the table in section 2 and decide every disagreement as in section 3 (definition change, label fix or keep). Definition changes go into the change log of `labeling_guide.md`.

Status: pending, needs the owner and one outsider.
