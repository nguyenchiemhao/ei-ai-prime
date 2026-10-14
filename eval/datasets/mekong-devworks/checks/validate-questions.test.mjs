// EA-16 AC2, AC3, AC4, AC6 (test questions): every question rule has a failing-input test on a tiny in-memory data set.
// Run: node --test "eval/datasets/mekong-devworks/checks/validate-questions.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { CONFIG, REGISTRY, question, run, rules, assertRejects } from "./fixtures.mjs";
import { validateDataset, loadDataset } from "../tools/validate.mjs";
import { parseJsonl } from "../tools/jsonl.mjs";

// ---- AC2 / AC3 questions ----

test("rejects_question_missing_a_required_field", () => {
  const r = run((d) => delete d.questions[3].type);
  const hit = assertRejects(r, "question-field", "test_questions.jsonl");
  assert.equal(hit.line, 4);
});

test("rejects_unknown_group_language_or_type", () => {
  assertRejects(run((d) => (d.questions[0].group = "Z")), "question-enum");
  assertRejects(run((d) => (d.questions[0].language = "fr")), "question-enum");
  assertRejects(run((d) => (d.questions[0].type = "chitchat")), "question-enum");
  assertRejects(run((d) => (d.questions[0].source = "robot")), "question-source");
});

test("rejects_correct_script_that_does_not_exist", () => {
  assertRejects(run((d) => (d.questions[0].correct_script = "no-such-script")), "question-script");
});

test("rejects_label_inconsistent_with_group", () => {
  assertRejects(run((d) => (d.questions[5].correct_script = "leave-request")), "question-group-rule");
  assertRejects(run((d) => (d.questions[6].type = "information")), "question-group-rule");
  assertRejects(run((d) => (d.questions[0].type = "greeting")), "question-group-rule");
  assertRejects(run((d) => (d.questions[0].correct_script = "NONE")), "question-group-rule");
});

test("rejects_group_c_question_whose_script_has_no_pair", () => {
  const r = run((d) => {
    delete d.scripts[2].near_duplicate_of;
    delete d.scripts[3].near_duplicate_of;
  });
  assertRejects(r, "question-group-rule");
});

test("rejects_invalid_history_shape", () => {
  assertRejects(run((d) => (d.questions[8].history = "none")), "question-history");
  assertRejects(run((d) => (d.questions[8].history = [{ user: "x" }])), "question-history");
  assertRejects(
    run((d) => (d.questions[8].history = Array.from({ length: 3 }, () => ({ user: "u", assistant: "a" })))),
    "question-history",
  );
  assertRejects(run((d) => (d.questions[8].history = [])), "question-group-rule");
  assertRejects(run((d) => (d.questions[0].history = [{ user: "u", assistant: "a" }])), "question-group-rule");
});

test("rejects_bad_question_id_and_duplicate_id", () => {
  assertRejects(run((d) => (d.questions[0].id = "q1")), "question-id");
  assertRejects(run((d) => (d.questions[1].id = d.questions[0].id)), "question-id");
});

test("rejects_invalid_json_line_with_line_number", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mekong-"));
  fs.writeFileSync(path.join(dir, "scripts.jsonl"), '{"id":"a"}\n{not json}\n');
  fs.writeFileSync(path.join(dir, "test_questions.jsonl"), "");
  fs.writeFileSync(path.join(dir, "scripts.csv"), "");
  fs.writeFileSync(path.join(dir, "fake_personal_data.json"), JSON.stringify(REGISTRY));
  const result = validateDataset(loadDataset(dir), CONFIG);
  const hit = assertRejects(result, "json", "scripts.jsonl");
  assert.equal(hit.line, 2);
});

test("rejects_group_count_outside_5_percent", () => {
  const withA = (n) => (d) => {
    for (let i = 0; i < n; i++) {
      d.questions.push(question(100 + i, "A", "en", "information", "leave-request", `extra paraphrase number ${i}`));
    }
  };
  const config = { ...CONFIG, groups: { ...CONFIG.groups, A: 40 } };
  const inside = run(withA(36), config); // 2 + 36 = 38 = 95% of 40
  const outside = run(withA(35), config); // 2 + 35 = 37 < 38
  assert.ok(!rules(inside).includes("group-count"), "38 of 40 is inside 5 percent");
  assertRejects(outside, "group-count");
});

test("rejects_language_share_outside_45_55", () => {
  const r = run((d) => d.questions.forEach((q) => { if (q.group !== "B") q.language = "en"; }));
  assertRejects(r, "language-share");
});

test("rejects_english_or_accented_group_b_question", () => {
  assertRejects(run((d) => (d.questions[2].language = "en")), "group-b-language");
  assertRejects(run((d) => (d.questions[2].question = "cách xin nghỉ phép")), "group-b-accent");
});

test("rejects_vietnamese_question_outside_group_b_without_diacritics", () => {
  assertRejects(run((d) => (d.questions[1].question = "minh muon rut don nghi")), "language-accent");
});

// ---- AC4 separation ----

test("rejects_test_question_equal_to_example_after_normalisation", () => {
  assertRejects(run((d) => (d.questions[0].question = "LEAVE-REQUEST   English, one?")), "separation");
  assertRejects(run((d) => (d.questions[2].question = "Leave-cancel tieng viet mot")), "separation");
});

test("rejects_test_question_equal_to_script_title", () => {
  assertRejects(run((d) => (d.questions[0].question = "How to request leave?")), "separation");
});

test("rejects_duplicate_test_questions_with_same_history", () => {
  assertRejects(run((d) => (d.questions[1].question = "where do I file a  day off")), "duplicate");
});

test("accepts_same_question_text_with_different_history", () => {
  const config = { ...CONFIG, groups: { ...CONFIG.groups, G: 2 }, languageShare: [0.4, 0.6] };
  const r = run((d) => {
    const copy = structuredClone(d.questions[8]);
    copy.id = "q-0011";
    copy.history = [{ user: "Another topic", assistant: "Another answer" }];
    d.questions.push(copy);
  }, config);
  assert.ok(!rules(r).includes("duplicate"));
});

// ---- coverage ----

test("rejects_scripts_without_enough_group_a_questions", () => {
  assertRejects(run(() => {}, { ...CONFIG, minGroupAPerScript: 1 }), "coverage");
});

test("skips_handoff_scripts_in_group_a_coverage", () => {
  const r = run(
    (d) => {
      for (const s of d.scripts.slice(2)) Object.assign(s, { mode: "action", action_type: "handoff", action_value: "hr@mekongdevworks.example" });
    },
    { ...CONFIG, minGroupAPerScript: 1 },
  );
  const messages = r.errors.filter((e) => e.rule === "coverage").map((e) => e.message).join("\n");
  assert.doesNotMatch(messages, /ot-weekday|ot-public-holiday/);
});

test("rejects_too_few_pair_members_group_b_scripts_task_or_data_questions", () => {
  assertRejects(run(() => {}, { ...CONFIG, minGroupCPerPairMember: 1 }), "coverage");
  assertRejects(run(() => {}, { ...CONFIG, minGroupBScripts: 2 }), "coverage");
  assertRejects(run(() => {}, { ...CONFIG, minTaskQuestions: 2 }), "coverage");
  assertRejects(run(() => {}, { ...CONFIG, minDataQuestions: 1 }), "coverage");
});

// ---- AC6 personal data ----

test("rejects_unregistered_phone_or_id_number", () => {
  assertRejects(run((d) => (d.questions[9].question += " hoặc 0987 654 321")), "personal-data");
  assertRejects(run((d) => (d.registry.phones = [])), "personal-data");
});

test("rejects_real_email_domain", () => {
  assertRejects(run((d) => (d.questions[9].question += " an.do@gmail.com")), "personal-data");
});

test("rejects_non_example_url", () => {
  assertRejects(run((d) => (d.questions[0].question = "Is https://www.google.com the portal?")), "personal-data");
});

test("rejects_group_h_question_without_personal_data", () => {
  assertRejects(run((d) => (d.questions[9].question = "Mình muốn hủy đơn nghỉ ngày mai")), "group-h-data");
});

test("accepts_group_h_question_with_a_registered_name_only", () => {
  assert.deepEqual(run((d) => (d.questions[9].question = "Mình là An Do, muốn hủy đơn nghỉ")).errors, []);
});

test("rejects_group_h_set_that_misses_a_kind_of_personal_data", () => {
  const r = run(() => {}, { ...CONFIG, minHKinds: { phone: 1, email: 1, national_id: 0 } });
  const hit = assertRejects(r, "group-h-kinds");
  assert.match(hit.message, /email/);
  assert.doesNotMatch(hit.message, /phone/);
});

// ---- robustness against hand-edited data (review R1-7, R1-11) ----

test("rejects_question_fields_with_the_wrong_json_type", () => {
  assertRejects(run((d) => (d.questions[0].question = 123)), "question-type");
  assertRejects(run((d) => (d.questions[0].group = ["A"])), "question-type");
  assertRejects(run((d) => (d.questions[0].correct_script = null)), "question-field");
});

test("reports_null_history_turns_without_crashing", () => {
  assertRejects(run((d) => (d.questions[8].history = [null])), "question-history");
});


test("rejects_formula_prefix_in_questions_and_history", () => {
  assertRejects(run((d) => (d.questions[0].question = "+84 912 345 678 is my number")), "question-injection");
  assertRejects(run((d) => (d.questions[0].question = "=1+1")), "question-injection");
  assertRejects(run((d) => (d.questions[8].history[0].user = "@home today")), "question-injection");
});

test("parse_jsonl_strips_a_utf8_bom_and_reports_line_numbers", () => {
  const { records, errors } = parseJsonl('﻿{"a":1}\n{"a":2}\nnot json\n');
  assert.deepEqual(records.map((r) => r.value.a), [1, 2]);
  assert.equal(errors[0].line, 3);
});
