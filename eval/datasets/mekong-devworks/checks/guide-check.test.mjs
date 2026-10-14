// EA-16 R2-1: no example in the labelling guide may give away the label of a test question.
// Run: node --test "eval/datasets/mekong-devworks/checks/guide-check.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import { guideExamples, findLeakedExamples } from "../tools/guide-check.mjs";

// Question texts copied from the data set as it was when review 2 found the leaks.
const DATASET = [
  { id: "q-0416", question: "Lan Ho (lan.ho@example.com) submitted the wrong hours last Friday. Can the timesheet be reopened?" },
  { id: "q-0293", question: "Mình còn bao nhiêu ngày phép sẽ được bảo lưu sang năm sau?" },
  { id: "q-0402", question: "This is Lan Ho, emp-0100, +84 987 654 321. Please cancel my leave request for next Monday and email the confirmation to lan.ho@example.com" },
  { id: "q-0027", question: "How much was my net pay in last month's payslip?" },
  { id: "q-0006", question: "Cancel my annual leave on Friday please" },
];

test("guide_examples_come_from_quotes_and_from_json_lines_but_not_from_other_code", () => {
  const guide = [
    'Prose with "Hello again!" and "a real human" and "..." here.',
    "```json",
    '{"id":"q-0000","history":[{"user":"Where is it?","assistant":"Upstairs."}],"question":"Which floor is the pantry on?"}',
    "```",
    "```",
    '"not an example in plain code"',
    "```",
    "Back to prose: \"Mình còn bao nhiêu ngày phép?\".",
  ].join("\n");
  assert.deepEqual(guideExamples(guide), ["Hello again!", "a real human", "...", "Which floor is the pantry on?", "Where is it?", "Upstairs.", "Mình còn bao nhiêu ngày phép?"]);
});

test("flags_the_leaks_review_2_found_in_the_guide", () => {
  const old = [
    "I want to cancel my leave tomorrow", // translation of q-0421: not detectable by tokens, covered by manual review
    "Can this timesheet be reopened?",
    "Mình còn bao nhiêu ngày phép?",
    "Please cancel my leave request for Friday.",
    "How much was my net pay last month?",
    "cancel my leave on Friday",
  ];
  const flagged = findLeakedExamples(old, DATASET).map((f) => `${f.example}=>${f.id}`);
  assert.deepEqual(flagged, [
    "Can this timesheet be reopened?=>q-0416",
    "Mình còn bao nhiêu ngày phép?=>q-0293",
    "Please cancel my leave request for Friday.=>q-0402",
    "How much was my net pay last month?=>q-0027",
    "cancel my leave on Friday=>q-0006",
  ]);
});

test("ignores_short_examples_unrelated_examples_and_low_overlap", () => {
  assert.deepEqual(findLeakedExamples(["Hello again!", "Cancel my leave", "Where is the pantry on this floor?"], DATASET), []);
});

test("overlap_ignores_case_diacritics_and_punctuation_and_applies_to_either_language", () => {
  const found = findLeakedExamples(["MINH CON BAO NHIEU NGAY PHEP, nhi?"], DATASET);
  assert.equal(found.length, 1);
  assert.equal(found[0].id, "q-0293");
  assert.ok(found[0].overlap >= 0.8);
});

test("threshold_is_configurable_and_reports_the_best_match_once_per_example", () => {
  const lax = findLeakedExamples(["Cancel my vacation days on Friday please"], DATASET, { threshold: 0.6 });
  assert.equal(lax.length, 1);
  assert.equal(lax[0].id, "q-0006");
  assert.deepEqual(findLeakedExamples(["Cancel my vacation days on Friday please"], DATASET), []);
});
