// EA-16 AC1, AC3 (scripts and scripts.csv): every script rule has a failing-input test on a tiny in-memory data set.
// Run: node --test "eval/datasets/mekong-devworks/checks/validate-scripts.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import { baseScripts, run, assertRejects } from "./fixtures.mjs";
import { buildScriptsCsv } from "../tools/build-scripts-csv.mjs";

test("accepts_minimal_valid_dataset", () => {
  const result = run();
  assert.deepEqual(result.errors, []);
  assert.equal(result.stats.scripts, 4);
  assert.equal(result.stats.questions, 10);
  assert.deepEqual(result.stats.byLanguage, { en: 5, vi: 5 });
  assert.equal(result.stats.byGroup.C, 2);
});

// ---- AC1 scripts ----

test("rejects_script_without_vi_answer", () => {
  const r = run((d) => (d.scripts[1].answer_vi = ""));
  assert.equal(assertRejects(r, "script-answer", "scripts.jsonl").line, 2);
});

test("rejects_script_with_2_or_6_examples_in_a_language", () => {
  assertRejects(run((d) => d.scripts[0].questions_en.pop()), "script-examples");
  assertRejects(run((d) => d.scripts[0].questions_vi.push("một", "hai", "ba")), "script-examples");
});

test("rejects_asymmetric_near_duplicate_pair", () => {
  assertRejects(run((d) => delete d.scripts[1].near_duplicate_of), "script-pair");
  assertRejects(run((d) => (d.scripts[0].near_duplicate_of = "nope")), "script-pair");
});

test("rejects_missing_required_design_pair", () => {
  const r = run((d) => {
    delete d.scripts[2].near_duplicate_of;
    delete d.scripts[3].near_duplicate_of;
  });
  assertRejects(r, "script-required-pair");
  assertRejects(r, "script-pairs-min");
});

test("rejects_missing_required_design_title", () => {
  assertRejects(run((d) => (d.scripts[0].title = "Something else")), "script-required-title");
});

test("rejects_duplicate_example_across_scripts", () => {
  const r = run((d) => (d.scripts[1].questions_en[0] = "Leave-Request English ONE!"));
  assertRejects(r, "script-example-duplicate");
});

test("rejects_unknown_answer_variable", () => {
  assertRejects(run((d) => (d.scripts[0].answer_en = "Hello {employee}")), "script-variable");
});

test("rejects_wrong_script_count", () => {
  assertRejects(run((d) => d.scripts.pop()), "script-count");
});

test("rejects_script_with_bad_id_duplicate_title_or_set", () => {
  assertRejects(run((d) => (d.scripts[0].id = "Leave_Request")), "script-id");
  assertRejects(run((d) => (d.scripts[1].title = d.scripts[0].title)), "script-title");
  assertRejects(run((d) => (d.scripts[0].set = "Finance")), "script-set");
});

test("rejects_invalid_mode_action_status_or_dates", () => {
  assertRejects(run((d) => (d.scripts[0].mode = "free")), "script-mode");
  assertRejects(run((d) => (d.scripts[0].action_type = "link")), "script-action");
  assertRejects(
    run((d) => Object.assign(d.scripts[0], { mode: "action", action_type: "link", action_value: "https://evil.com/x" })),
    "script-action",
  );
  assertRejects(
    run((d) => Object.assign(d.scripts[0], { mode: "action", action_type: "handoff", action_value: "hr@gmail.com" })),
    "script-action",
  );
  assertRejects(run((d) => (d.scripts[0].status = "scheduled")), "script-status");
  assertRejects(run((d) => (d.scripts[0].start_date = "2027-02-30")), "script-date");
  assertRejects(run((d) => Object.assign(d.scripts[0], { start_date: "2027-02-20", end_date: "2027-01-15" })), "script-date");
});

test("accepts_valid_action_scripts", () => {
  const r = run((d) => {
    Object.assign(d.scripts[0], { mode: "action", action_type: "link", action_value: "https://careers.mekongdevworks.example/jobs" });
    Object.assign(d.scripts[2], { mode: "action", action_type: "handoff", action_value: "hr@mekongdevworks.example" });
  });
  assert.deepEqual(r.errors, []);
});

test("rejects_csv_injection_prefix_placeholders_and_foreign_urls_in_scripts", () => {
  assertRejects(run((d) => (d.scripts[0].answer_en = "=SUM(A1)")), "script-injection");
  assertRejects(run((d) => (d.scripts[0].questions_vi[0] = "-1 ngày phép")), "script-injection");
  assertRejects(run((d) => (d.scripts[0].answer_en = "TODO write this")), "script-placeholder");
  assertRejects(run((d) => (d.scripts[0].answer_en = "See https://www.google.com/x")), "script-url");
  assertRejects(run((d) => (d.scripts[0].answer_en = "Call 0987 654 321")), "script-personal-data");
});

test("rejects_example_containing_a_pipe", () => {
  assertRejects(run((d) => (d.scripts[0].questions_en[0] = "a | b")), "script-examples");
});

// ---- scripts.csv ----

test("rejects_csv_that_differs_from_scripts", () => {
  const good = buildScriptsCsv(baseScripts());
  assertRejects(run((d) => (d.csvText = good.replace("Answer for leave-cancel", "Edited by hand"))), "csv-content", "scripts.csv");
  assertRejects(run((d) => (d.csvText = good.replace("external_id", "id"))), "csv-header");
  assertRejects(run((d) => (d.csvText = good.split("\n").slice(0, 3).join("\n") + "\n")), "csv-rows");
});

test("accepts_csv_with_crlf_line_endings", () => {
  const good = buildScriptsCsv(baseScripts());
  assert.deepEqual(run((d) => (d.csvText = good.replace(/\n/g, "\r\n"))).errors, []);
});


test("reports_a_script_without_examples_without_crashing", () => {
  const r = run((d) => delete d.scripts[0].questions_vi);
  assertRejects(r, "script-field", "scripts.jsonl");
});

