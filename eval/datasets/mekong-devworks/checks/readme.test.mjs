// EA-16 NFR: README and the list of expected files.
// Run: node --test "eval/datasets/mekong-devworks/checks/readme.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { DIR, read, questions } from "./context.mjs";

const CROSS = "cross_labelling";

// ---- NFR / README (T10) ----

test("NFR: README states that all data is fictional", () => {
  const readme = read("README.md");
  assert.match(readme, /Mekong Devworks is a fictional company\. Every name, phone number, email, ID number, URL and figure in this folder is invented for testing\./);
  assert.ok(readme.indexOf("fictional") < readme.indexOf("\n## "), "the statement comes before the first section");
});

test("README documents commands, counts, usage notes, limitations and status", () => {
  const readme = read("README.md");
  assert.match(readme, /node --test "eval\/datasets\/mekong-devworks\/checks\/\*\.test\.mjs"/);
  assert.match(readme, /node eval\/datasets\/mekong-devworks\/tools\/validate\.mjs/);
  assert.match(readme, /from the repository root/i);
  assert.match(readme, /fail when .* 0 tests/i);
  assert.match(readme, /CI wiring pending SET-03 \(EA-13\)/);
  assert.match(readme, /every script is a candidate regardless of status/i);
  assert.match(readme, /NONE-precision/);
  assert.match(readme, /430/);
  assert.match(readme, /Version: 1\.0 — 2026-10-13/);
  assert.match(readme, /Review status: Pending owner review/);
  for (const file of fs.readdirSync(DIR).filter((f) => !f.startsWith(".") && !["README.md", "checks", "tools", "cross_labelling"].includes(f))) {
    assert.ok(readme.includes(`\`${file}\``), `README does not mention ${file}`);
  }
  const counts = {};
  const languages = {};
  for (const q of questions) {
    counts[q.group] = (counts[q.group] ?? 0) + 1;
    languages[`${q.group}-${q.language}`] = (languages[`${q.group}-${q.language}`] ?? 0) + 1;
  }
  for (const [g, n] of Object.entries(counts)) {
    const row = readme.split("\n").find((l) => l.startsWith(`| ${g} |`));
    assert.ok(row, `README has no table row for group ${g}`);
    const cells = row.split("|").map((c) => c.trim()).filter(Boolean);
    assert.deepEqual(cells.slice(2), [String(n), String(languages[`${g}-en`] ?? 0), String(languages[`${g}-vi`] ?? 0)], `README counts for group ${g}`);
  }
  for (const fact of ["14 days", "150%", "200%", "300%", "ext. 1234", "VND 250,000", "VND 600,000", "the 28th", "learning budget"]) {
    assert.ok(readme.includes(fact), `company facts table misses ${fact}`);
  }
});

test("expected files exist (final)", () => {
  for (const f of ["README.md", "scripts.jsonl", "scripts.csv", "test_questions.jsonl", "labeling_guide.md", "fake_personal_data.json", `${CROSS}/sample.json`, `${CROSS}/key_map.json`, `${CROSS}/blind_sheet.csv`, `${CROSS}/labeller_1_author.csv`]) {
    assert.ok(fs.existsSync(path.join(DIR, f)), `${f} is missing`);
  }
});

test("expected run-3 files exist (final)", () => {
  for (const f of ["agreement_report.md", `${CROSS}/labeller_2_llm.csv`, `${CROSS}/agreement.json`]) {
    assert.ok(fs.existsSync(path.join(DIR, f)), `${f} is missing`);
  }
});
