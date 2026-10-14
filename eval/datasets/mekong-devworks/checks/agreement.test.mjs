// EA-16 AC5: cross-labelling sample, opaque blind sheet and agreement statistics.
// Run: node --test "eval/datasets/mekong-devworks/checks/agreement.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import { percentAgreement, cohenKappa, validateLabelRows, compareLabels, parseAgreementArgs } from "../tools/agreement.mjs";
import { sampleIds, buildKeyMap, buildBlindSheet, buildSnapshot, renderHistory } from "../tools/cross-labelling.mjs";
import { parseCsv } from "../tools/csv.mjs";

// Worked example (n = 10), computed by hand:
//   A: a a a a a b b b b b
//   B: a a a b b b b b b a
// They agree on positions 1-3 and 6-9, so p_o = 7/10 = 0.7.
// A has a = 5, b = 5; B has a = 4, b = 6, so p_e = 0.5*0.4 + 0.5*0.6 = 0.5.
// kappa = (0.7 - 0.5) / (1 - 0.5) = 0.4.
const A = ["a", "a", "a", "a", "a", "b", "b", "b", "b", "b"];
const B = ["a", "a", "a", "b", "b", "b", "b", "b", "b", "a"];

const KEYS = ["r-001", "r-002", "r-003"];
const CTX = { keys: KEYS, types: ["greeting", "information", "task"], scripts: ["leave-request", "leave-cancel"] };
const row = (key, type, correct_script, note = "") => ({ key, type, correct_script, note });
const GOOD = [row("r-001", "information", "leave-request"), row("r-002", "task", "leave-cancel"), row("r-003", "greeting", "NONE")];

test("percent_agreement_and_cohen_kappa_match_worked_example", () => {
  assert.equal(percentAgreement(A, B), 0.7);
  assert.ok(Math.abs(cohenKappa(A, B) - 0.4) < 1e-12);
});

test("kappa_is_1_when_labels_are_identical_and_constant", () => {
  assert.equal(cohenKappa(["x", "x", "x"], ["x", "x", "x"]), 1);
  assert.equal(cohenKappa(A, A), 1);
});

test("accepts_complete_label_rows_and_trims_whitespace", () => {
  const rows = [row("r-001", " information ", " leave-request "), GOOD[1], GOOD[2]];
  const { labels, problems } = validateLabelRows(rows, CTX);
  assert.deepEqual(problems, []);
  assert.deepEqual(labels.get("r-001"), { type: "information", correct_script: "leave-request" });
});

test("rejects_blank_unknown_wrongly_cased_duplicate_missing_and_unknown_rows", () => {
  const bad = (rows) => validateLabelRows(rows, CTX).problems.join("\n");
  assert.match(bad([row("r-001", "", "NONE"), GOOD[1], GOOD[2]]), /r-001.*type/);
  assert.match(bad([row("r-001", "information", ""), GOOD[1], GOOD[2]]), /r-001.*correct_script/);
  assert.match(bad([row("r-001", "Information", "NONE"), GOOD[1], GOOD[2]]), /r-001.*type/);
  assert.match(bad([row("r-001", "information", "none"), GOOD[1], GOOD[2]]), /r-001.*correct_script/);
  assert.match(bad([row("r-001", "information", "no-such"), GOOD[1], GOOD[2]]), /r-001.*correct_script/);
  assert.match(bad([GOOD[0], GOOD[0], GOOD[1], GOOD[2]]), /duplicate.*r-001/);
  assert.match(bad([GOOD[0], GOOD[1]]), /missing.*r-003/);
  assert.match(bad([...GOOD, row("r-999", "task", "NONE")]), /unknown.*r-999/);
  assert.match(bad(GOOD.map((r) => row(r.key, "", ""))), /r-003/);
});

test("compare_labels_reports_type_script_both_and_disagreements_by_question_id", () => {
  const labelsA = new Map([
    ["r-001", { type: "information", correct_script: "leave-request" }],
    ["r-002", { type: "task", correct_script: "leave-cancel" }],
    ["r-003", { type: "greeting", correct_script: "NONE" }],
  ]);
  const labelsB = new Map([
    ["r-003", { type: "greeting", correct_script: "NONE" }],
    ["r-001", { type: "information", correct_script: "leave-cancel" }],
    ["r-002", { type: "information", correct_script: "leave-cancel" }],
  ]);
  const keyToId = new Map([["r-001", "q-0101"], ["r-002", "q-0007"], ["r-003", "q-0300"]]);
  const r = compareLabels(labelsA, labelsB, keyToId);
  assert.equal(r.n, 3);
  assert.ok(Math.abs(r.type.agreement - 2 / 3) < 1e-12);
  assert.ok(Math.abs(r.correct_script.agreement - 2 / 3) < 1e-12);
  assert.ok(Math.abs(r.both.agreement - 1 / 3) < 1e-12);
  assert.deepEqual(r.disagreements.map((d) => [d.key, d.id]), [["r-001", "q-0101"], ["r-002", "q-0007"]]);
  assert.deepEqual(r.disagreements[0].b, { type: "information", correct_script: "leave-cancel" });
});

test("parse_agreement_args_handles_no_out_out_first_out_last_and_missing_value", () => {
  assert.deepEqual(parseAgreementArgs(["a.csv", "b.csv"]), { fileA: "a.csv", fileB: "b.csv", out: null });
  assert.deepEqual(parseAgreementArgs(["--out", "o.json", "a.csv", "b.csv"]), { fileA: "a.csv", fileB: "b.csv", out: "o.json" });
  assert.deepEqual(parseAgreementArgs(["a.csv", "b.csv", "--out", "o.json"]), { fileA: "a.csv", fileB: "b.csv", out: "o.json" });
  assert.throws(() => parseAgreementArgs(["a.csv", "b.csv", "--out"]), /--out needs a file/);
  assert.throws(() => parseAgreementArgs(["a.csv"]), /usage/);
});

const ALL = Array.from({ length: 430 }, (_, i) => `q-${String(i + 1).padStart(4, "0")}`);

test("sample_is_deterministic_for_seed_and_has_100_unique_ids", () => {
  const first = sampleIds(ALL, 16, 100);
  assert.deepEqual(sampleIds(ALL, 16, 100), first);
  assert.equal(new Set(first).size, 100);
  assert.deepEqual(first, [...first].sort());
  assert.ok(first.every((id) => ALL.includes(id)));
  assert.notDeepEqual(sampleIds(ALL, 17, 100), first);
});

test("key_map_is_a_deterministic_shuffle_with_opaque_row_keys", () => {
  const ids = sampleIds(ALL, 16, 100);
  const map = buildKeyMap(ids, 160);
  assert.deepEqual(buildKeyMap(ids, 160), map);
  assert.deepEqual(map.map((m) => m.key), Array.from({ length: 100 }, (_, i) => `r-${String(i + 1).padStart(3, "0")}`));
  assert.deepEqual(map.map((m) => m.id).sort(), ids);
  const order = map.map((m) => m.id);
  assert.notDeepEqual(order, ids, "row order must not follow the id order");
  const ascendingSteps = order.filter((id, i) => i > 0 && id > order[i - 1]).length;
  assert.ok(ascendingSteps > 30 && ascendingSteps < 70, `row order looks sorted (${ascendingSteps} ascending steps)`);
});

const QUESTIONS = [
  { id: "q-0001", group: "A", language: "en", history: [], question: "Where, exactly?", type: "information", correct_script: "leave-request" },
  {
    id: "q-0002",
    group: "G",
    language: "vi",
    history: [{ user: "Hỏi", assistant: "Đáp" }, { user: "Hỏi 2", assistant: "Đáp 2" }],
    question: "thế còn cái kia?",
    type: "follow_up",
    correct_script: "NONE",
  },
  { id: "q-0003", group: "B", language: "vi", history: [], question: "khong chon", type: "information", correct_script: "NONE" },
];
const MAP = [{ key: "r-001", id: "q-0002" }, { key: "r-002", id: "q-0001" }];

test("blind_sheet_hides_ids_group_and_labels_and_follows_the_key_order", () => {
  const csv = buildBlindSheet(QUESTIONS, MAP);
  const parsed = parseCsv(csv);
  assert.deepEqual(parsed.header, ["key", "language", "history", "question", "type", "correct_script", "note"]);
  assert.deepEqual(parsed.rows.map((r) => r.key), ["r-001", "r-002"]);
  assert.equal(parsed.rows[0].history, "User: Hỏi / Assistant: Đáp / User: Hỏi 2 / Assistant: Đáp 2");
  assert.deepEqual(parsed.rows[1], { key: "r-002", language: "en", history: "", question: "Where, exactly?", type: "", correct_script: "", note: "" });
  assert.equal(renderHistory([]), "");
  assert.ok(!/q-\d{4}/.test(csv), "no question id in the sheet");
  assert.ok(!csv.includes("leave-request") && !/information|follow_up/.test(csv) && !csv.includes("group"));
});

test("snapshot_follows_the_key_order_and_carries_the_dataset_labels", () => {
  const parsed = parseCsv(buildSnapshot(QUESTIONS, MAP));
  assert.deepEqual(parsed.header, ["key", "type", "correct_script", "note"]);
  assert.deepEqual(parsed.rows, [row("r-001", "follow_up", "NONE"), row("r-002", "information", "leave-request")]);
});
