// EA-16 integration checks (AC1-AC4, AC6) on the real data files of the Mekong Devworks test set.
// Run: node --test "eval/datasets/mekong-devworks/checks/*.test.mjs" (from the repository root)
// No network, no dependencies. CRLF is normalised on read.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { DIR, read, dataset, scripts, questions, result, assertNoErrors } from "./context.mjs";
import { DEFAULT_CONFIG } from "../tools/schema.mjs";
import { parseCsv } from "../tools/csv.mjs";
import { buildScriptsCsv } from "../tools/build-scripts-csv.mjs";
import { normalise, hasVietnameseDiacritics } from "../tools/text.mjs";
import { isVietnamesePhone, isCccd, isCmnd, digitsOf, extractPersonalData, checkPersonalData } from "../tools/personal-data.mjs";
import { guideExamples, findLeakedExamples } from "../tools/guide-check.mjs";

test("expected files exist", () => {
  for (const f of ["scripts.jsonl", "scripts.csv", "test_questions.jsonl", "labeling_guide.md", "fake_personal_data.json"]) {
    assert.ok(fs.existsSync(path.join(DIR, f)), `${f} is missing`);
  }
});

// ---- AC1 ----

test("AC1: has 40 scripts with EN and VI answers and 3-5 examples per language", () => {
  assert.equal(scripts.length, 40);
  for (const s of scripts) {
    assert.ok(s.answer_en.trim() && s.answer_vi.trim(), `${s.id} lacks an answer`);
    for (const f of ["questions_en", "questions_vi"]) {
      assert.ok(s[f].length >= 3 && s[f].length <= 5, `${s.id}.${f} has ${s[f].length} examples`);
    }
  }
  assertNoErrors("script-field", "script-count", "script-answer", "script-examples", "script-example-duplicate", "script-variable");
});

test("AC1: has at least 8 near-duplicate pairs including the 4 design pairs", () => {
  const byId = new Map(scripts.map((s) => [s.id, s]));
  const pairs = new Set();
  for (const s of scripts) {
    if (s.near_duplicate_of) {
      assert.equal(byId.get(s.near_duplicate_of)?.near_duplicate_of, s.id, `${s.id} pair is not symmetric`);
      pairs.add([s.id, s.near_duplicate_of].sort().join("/"));
    }
  }
  assert.ok(pairs.size >= 8, `only ${pairs.size} pairs`);
  for (const [a, b] of DEFAULT_CONFIG.requiredPairs) assert.ok(pairs.has([a, b].sort().join("/")), `${a}/${b} missing`);
  assertNoErrors("script-pair", "script-pairs-min", "script-required-pair");
});

test("AC1: reuses the design script titles", () => {
  const titles = new Set(scripts.map((s) => s.title));
  for (const t of DEFAULT_CONFIG.requiredTitles) assert.ok(titles.has(t), `design title missing: ${t}`);
  const design = scripts.find((s) => s.id === "leave-cancel");
  assert.ok(design.questions_vi.includes("huy phep da duyet"), "the ScriptEditor example is kept");
  assertNoErrors("script-required-title", "script-title", "script-id", "script-set");
});

test("AC1: scripts follow the action, status, date, link and CSV-injection rules", () => {
  assertNoErrors("script-mode", "script-action", "script-status", "script-date", "script-injection", "script-placeholder", "script-url", "script-personal-data");
  const tet = scripts.find((s) => s.id === "tet-holiday-2027");
  assert.deepEqual([tet.start_date, tet.end_date], ["2027-01-15", "2027-02-20"]);
  assert.equal(scripts.find((s) => s.id === "ot-public-holiday").status, "draft");
});

// ---- AC3 CSV ----

test("AC3: scripts.csv has the PIPE-04 columns and matches scripts.jsonl", () => {
  const csv = read("scripts.csv");
  const parsed = parseCsv(csv);
  assert.deepEqual(parsed.header, DEFAULT_CONFIG.csvColumns);
  assert.equal(parsed.rows.length, 40);
  assert.equal(csv, buildScriptsCsv(scripts));
  assert.ok(!csv.startsWith("﻿"));
  assertNoErrors("csv-header", "csv-rows", "csv-content");
});

// ---- Labelling guide (T4) ----

test("labeling guide defines all 7 types and has a change log", () => {
  const guide = read("labeling_guide.md");
  for (const type of DEFAULT_CONFIG.types) assert.match(guide, new RegExp("`" + type + "`"), `guide misses type ${type}`);
  for (const vi of ["chao_hoi", "chuyen_nguoi", "ngoai_pham_vi", "tiep_noi", "thong_tin", "tac_vu", "du_lieu"]) {
    assert.ok(guide.includes(vi), `guide misses D27 name ${vi}`);
  }
  assert.match(guide, /^## Change log$/m);
  assert.match(guide, /\| Date \| Section \| Change \| Triggered by \(question ids\) \|/);
  for (const g of "ABCDEFGH") assert.match(guide, new RegExp(`\\| ${g} \\|`), `guide misses group ${g}`);
});

// ---- AC2 / AC3 / AC4 / AC6 on test_questions.jsonl ----

test("AC3: every JSONL line has the required fields and the validator reports no errors on the data set", () => {
  assert.equal(dataset.parseErrors.length, 0);
  for (const q of questions) {
    for (const f of DEFAULT_CONFIG.requiredQuestionFields) assert.ok(f in q, `${q.id} lacks ${f}`);
  }
  assert.deepEqual(result.errors.map((e) => `${e.file}:${e.line} ${e.rule} ${e.message}`), []);
});

test("AC3: validate CLI exits 0", () => {
  const run = spawnSync(process.execPath, [path.join(DIR, "tools/validate.mjs")], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stdout + run.stderr);
  assert.match(run.stdout, /^OK: 40 scripts, 430 questions/);
});

test("AC2: group counts within 5 percent of targets and languages balanced", () => {
  const byGroup = {};
  const byLanguage = { en: 0, vi: 0 };
  for (const q of questions) {
    byGroup[q.group] = (byGroup[q.group] ?? 0) + 1;
    byLanguage[q.language]++;
  }
  for (const [g, target] of Object.entries(DEFAULT_CONFIG.groups)) {
    assert.ok(Math.abs(byGroup[g] - target) <= 0.05 * target, `group ${g}: ${byGroup[g]} vs ${target}`);
  }
  for (const lang of ["en", "vi"]) {
    const share = byLanguage[lang] / questions.length;
    assert.ok(share >= 0.45 && share <= 0.55, `${lang} share ${share}`);
  }
  assertNoErrors("group-count", "language-share");
});

test("AC2: group B is unaccented Vietnamese only", () => {
  const b = questions.filter((q) => q.group === "B");
  assert.ok(b.length >= 57);
  for (const q of b) {
    assert.equal(q.language, "vi", q.id);
    assert.equal(hasVietnameseDiacritics(q.question), false, `${q.id}: ${q.question}`);
  }
  assertNoErrors("group-b-language", "group-b-accent", "language-accent");
});

test("AC4: no test question equals a script example or title after normalisation", () => {
  const references = new Set();
  for (const s of scripts) {
    references.add(normalise(s.title));
    for (const e of [...s.questions_en, ...s.questions_vi]) references.add(normalise(e));
  }
  for (const q of questions) assert.ok(!references.has(normalise(q.question)), `${q.id} copies an example: ${q.question}`);
  assertNoErrors("separation", "duplicate");
});

test("AC6: all personal data is registered fake data in Vietnamese formats", () => {
  const registry = dataset.registry;
  assert.match(registry._note, /invented/);
  for (const p of registry.phones) assert.ok(isVietnamesePhone(p), `phone ${p}`);
  for (const id of registry.national_ids) assert.ok(isCccd(digitsOf(id)) || isCmnd(digitsOf(id)), `id ${id}`);
  for (const q of questions) {
    for (const text of [q.question, ...q.history.flatMap((t) => [t.user, t.assistant])]) {
      assert.deepEqual(checkPersonalData(text, registry), [], q.id);
    }
  }
  assertNoErrors("personal-data");
});

test("AC6: every group H question contains personal data and H covers phone, email and ID", () => {
  const h = questions.filter((q) => q.group === "H");
  assert.ok(h.length >= 29);
  let phones = 0, emails = 0, ids = 0;
  for (const q of h) {
    const found = extractPersonalData(q.question);
    const named = (dataset.registry.names || []).some((n) => q.question.includes(n));
    assert.ok(found.emails.length + found.numbers.length + found.employeeCodes.length > 0 || named, `${q.id} has no personal data`);
    if (found.numbers.some(isVietnamesePhone)) phones++;
    if (found.emails.length) emails++;
    if (found.numbers.some((n) => isCccd(digitsOf(n)) || isCmnd(digitsOf(n)))) ids++;
  }
  assert.ok(phones >= 5 && emails >= 5 && ids >= 5, `phones ${phones}, emails ${emails}, ids ${ids}`);
  assertNoErrors("group-h-data", "group-h-kinds");
});

test("labels: task and data questions reach their minimum and coverage rules hold", () => {
  assert.ok(questions.filter((q) => q.type === "task").length >= 15);
  assert.ok(questions.filter((q) => q.type === "data").length >= 15);
  assertNoErrors("coverage", "question-group-rule", "question-script", "question-enum", "question-history", "question-id", "question-field", "question-source", "question-type", "question-injection");
});


test("guide: no example copies or nearly copies a test question", () => {
  const leaks = findLeakedExamples(guideExamples(read("labeling_guide.md")), [
    ...questions,
    ...questions.flatMap((q) => q.history.map((t) => ({ id: q.id, question: t.user }))),
  ]);
  assert.deepEqual(leaks.map((l) => `"${l.example}" is ${Math.round(l.overlap * 100)}% inside ${l.id}`), []);
  assert.ok(guideExamples(read("labeling_guide.md")).length > 30, "the extractor finds the guide examples");
});
