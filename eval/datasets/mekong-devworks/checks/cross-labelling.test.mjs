// EA-16 AC5: cross-labelling files and the agreement report.
// Run: node --test "eval/datasets/mekong-devworks/checks/cross-labelling.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { DIR, read, scripts, questions } from "./context.mjs";
import { DEFAULT_CONFIG } from "../tools/schema.mjs";
import { parseCsv } from "../tools/csv.mjs";
import { compareLabellers, readLabelFile } from "../tools/agreement.mjs";

// ---- AC5 cross-labelling (run 2: opaque shuffled keys, strict label files) ----

const CROSS = "cross_labelling";
const sample = JSON.parse(read(`${CROSS}/sample.json`));
const keyMap = JSON.parse(read(`${CROSS}/key_map.json`));
const keyToId = new Map(keyMap.rows.map((r) => [r.key, r.id]));
const labelCtx = { keys: keyMap.rows.map((r) => r.key), types: DEFAULT_CONFIG.types, scripts: scripts.map((s) => s.id) };
const L1 = path.join(DIR, CROSS, "labeller_1_author.csv");
const L2 = path.join(DIR, CROSS, "labeller_2_llm.csv");


test("AC5: sample has 100 existing ids drawn with seed 16", () => {
  const all = new Set(questions.map((q) => q.id));
  assert.equal(sample.seed, 16);
  assert.equal(sample.size, 100);
  assert.equal(sample.ids.length, 100);
  assert.equal(new Set(sample.ids).size, 100);
  for (const id of sample.ids) assert.ok(all.has(id), `${id} is not a question id`);
});

test("AC5: key map covers exactly the sample and its row order does not follow the id order", () => {
  assert.deepEqual(keyMap.rows.map((r) => r.id).sort(), [...sample.ids].sort());
  assert.deepEqual(keyMap.rows.map((r) => r.key), Array.from({ length: 100 }, (_, i) => `r-${String(i + 1).padStart(3, "0")}`));
  const order = keyMap.rows.map((r) => r.id);
  const ascending = order.filter((id, i) => i > 0 && id > order[i - 1]).length;
  assert.ok(ascending > 30 && ascending < 70, `row order looks sorted (${ascending} ascending steps of 99)`);
  const groupOf = new Map(questions.map((q) => [q.id, q.group]));
  const sameGroupNeighbours = order.filter((id, i) => i > 0 && groupOf.get(id) === groupOf.get(order[i - 1])).length;
  assert.ok(sameGroupNeighbours < 40, `rows look grouped (${sameGroupNeighbours} same-group neighbours)`);
});

test("AC5: blind sheet follows the key map and hides ids, groups and labels", () => {
  const raw = read(`${CROSS}/blind_sheet.csv`);
  assert.ok(!/q-\d{4}/.test(raw), "the sheet must not contain question ids");
  const sheet = parseCsv(raw);
  assert.deepEqual(sheet.header, ["key", "language", "history", "question", "type", "correct_script", "note"]);
  assert.deepEqual(sheet.rows.map((r) => r.key), labelCtx.keys);
  for (const r of sheet.rows) {
    assert.equal(r.type, "", r.key);
    assert.equal(r.correct_script, "", r.key);
    const q = questions.find((x) => x.id === keyToId.get(r.key));
    assert.equal(r.question, q.question);
    assert.equal(r.language, q.language);
  }
});

test("AC5: first labeller file is a valid snapshot in key order", () => {
  const rows = parseCsv(read(`${CROSS}/labeller_1_author.csv`));
  assert.deepEqual(rows.header, ["key", "type", "correct_script", "note"]);
  assert.deepEqual(rows.rows.map((r) => r.key), labelCtx.keys);
  assert.doesNotThrow(() => readLabelFile(L1, labelCtx));
});

test("AC5: runs 1 and 2 are archived and marked as superseded", () => {
  const runs = [
    ["run-1", /superseded: row order leaked the group \(review R1-1\)/i],
    ["run-2", /superseded: guide examples gave away labels of 5 sampled rows \(review R2-1\)/i],
  ];
  for (const [run, reason] of runs) {
    for (const f of ["README.md", "labeller_1_author.csv", "labeller_2_llm.csv", "blind_sheet.csv", "agreement.json", "agreement_report.md"]) {
      assert.ok(fs.existsSync(path.join(DIR, CROSS, run, f)), `${run}/${f} is missing`);
    }
    assert.match(read(`${CROSS}/${run}/README.md`), reason);
  }
  assert.equal(read(`${CROSS}/run-2/key_map.json`), read(`${CROSS}/key_map.json`));
});

// ---- AC5 agreement report (T9; needs the run-2 labeller file) ----

const RESOLUTIONS = ["definition change", "label fix", "keep"];

function section(text, heading) {
  const start = text.indexOf(`## ${heading}`);
  assert.ok(start >= 0, `report misses section ${heading}`);
  const next = text.indexOf("\n## ", start + 3);
  return text.slice(start, next === -1 ? undefined : next);
}

const disagreementTable = (report) => section(report, "3. Disagreements").split("\n### ")[0];

test("AC5: second labeller file is strictly valid, covers all keys and has no BOM", () => {
  const raw = fs.readFileSync(L2);
  assert.ok(!(raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf), "labeller_2_llm.csv has a BOM");
  assert.deepEqual(parseCsv(raw.toString("utf8")).header, ["key", "type", "correct_script", "note"]);
  assert.doesNotThrow(() => readLabelFile(L2, labelCtx));
});

test("AC5: agreement.json equals a fresh computation on the two labeller files", () => {
  const stored = JSON.parse(read(`${CROSS}/agreement.json`))["labeller_1_author.csv vs labeller_2_llm.csv"];
  assert.deepEqual(stored, compareLabellers(L1, L2, keyToId, labelCtx));
});

test("AC5: report numbers match recomputed agreement", () => {
  const report = read("agreement_report.md");
  const fresh = compareLabellers(L1, L2, keyToId, labelCtx);
  const results = section(report, "2. Results");
  for (const key of ["type", "correct_script", "both"]) {
    const row = results.split("\n").find((l) => l.startsWith(`| ${key} |`));
    assert.ok(row, `results row ${key} missing`);
    const cells = row.split("|").map((c) => c.trim()).filter(Boolean);
    assert.deepEqual(cells, [key, String(fresh.n), (fresh[key].agreement * 100).toFixed(2), fresh[key].kappa.toFixed(2)]);
  }
});

test("AC5: every disagreement is listed with a resolution", () => {
  const report = read("agreement_report.md");
  const fresh = compareLabellers(L1, L2, keyToId, labelCtx);
  const text = disagreementTable(report);
  const rows = text.split("\n").filter((l) => /^\| q-\d{4} \|/.test(l)).map((l) => l.split("|").map((c) => c.trim()).filter(Boolean));
  assert.deepEqual(rows.map((r) => r[0]).sort(), fresh.disagreements.map((d) => d.id).sort());
  for (const r of rows) assert.ok(RESOLUTIONS.includes(r[3]), `${r[0]} resolution "${r[3]}"`);
  if (fresh.disagreements.length === 0) assert.match(text, /no disagreements/i);
});

test("AC5: guide change log lists every definition change named in the report", () => {
  const report = read("agreement_report.md");
  const log = read("labeling_guide.md");
  const changes = section(report, "4. Label-definition changes");
  const logText = log.slice(log.indexOf("## Change log"));
  const named = [...disagreementTable(report).matchAll(/^\| (q-\d{4}) \|.*\| definition change \|/gm)].map((m) => m[1]);
  for (const id of named) assert.ok(logText.includes(id), `${id} is not in the guide change log`);
  for (const id of ["q-0182", "q-0217", "q-0223", "q-0427", "q-0159", "q-0161", "q-0162", "q-0027", "q-0268", "q-0292"]) {
    assert.ok(logText.includes(id), `${id} (review R1-2 / R1-3) is not in the guide change log`);
    assert.ok(changes.includes(id), `${id} is not named in report section 4`);
  }
  assert.match(changes, /R1-2/);
  assert.match(changes, /R1-3/);
});

test("AC5: report states labeller identities, composition, run 1 supersession and limitations", () => {
  const report = read("agreement_report.md");
  for (const h of ["1. Method", "2. Results", "3. Disagreements", "4. Label-definition changes", "5. Limitations", "6. Human cross-labelling"]) {
    assert.match(report, new RegExp(`^## ${h}`, "m"));
  }
  const method = section(report, "1. Method");
  assert.match(method, /Labeller 1 — dataset author, developer agent claude-sonnet-5-5/);
  assert.match(method, /Labeller 2 — independent agent claude-opus-5-5/);
  assert.match(method, /seed 16/);
  assert.match(method, /opaque/i);
  assert.match(method, /run 1[^\n]*superseded/i);
  assert.match(method, /run 2[^\n]*superseded/i);
  assert.match(method, /guide version 1\.2/i);
  const byId = new Map(questions.map((q) => [q.id, q]));
  const count = (f) => sample.ids.reduce((m, id) => m.set(f(byId.get(id)), (m.get(f(byId.get(id))) ?? 0) + 1), new Map());
  const groups = [...count((q) => q.group)].sort().map(([g, n]) => `${g} ${n}`).join(", ");
  assert.ok(report.includes(`Sample composition by group: ${groups}`), `report misses "Sample composition by group: ${groups}"`);
  for (const [type, n] of count((q) => q.type)) assert.ok(report.includes(`${type} ${n}`), `report misses type count "${type} ${n}"`);
  const limits = section(report, "5. Limitations");
  for (const word of ["same vendor", "overstated", "owner review", "outsiders"]) assert.match(limits, new RegExp(word, "i"));
  assert.match(section(report, "6. Human cross-labelling"), /pending/i);
});
