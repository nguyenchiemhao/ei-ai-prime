// EA-12 (SET-02) AC1-AC4: structural and consistency checks of docs/architecture/oss-license-review.md
// and of its links with docs/architecture/adr-001-tech-stack.md.
// These tests make sure no required part is missing; the correctness of each licence claim is checked
// by the reviewer against the Source URL of the row (and formally in MVP-10, EA-84).
//
// Run:  node --test docs/architecture/checks/oss-license-review.test.mjs
// (Node 22: pass the file path; `node --test <directory>` does not work.) No network, no dependencies.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const REVIEW = path.join(ROOT, "docs/architecture/oss-license-review.md");
const ADR = path.join(ROOT, "docs/architecture/adr-001-tech-stack.md");
const POC_DIR = path.join(ROOT, "poc/stack-spike");
const POC_REQ = path.join(POC_DIR, "requirements.txt");
const POC_COMPOSE = path.join(POC_DIR, "compose.yaml");
const POC_DOCKERFILE = path.join(POC_DIR, "Dockerfile");

const HEADINGS = [
  "1. Scope, assumptions and method",
  "2. Library and model table",
  "3. Model weights",
  "4. Red flags",
  "5. Ideas from existing platforms",
  "6. Obligations when shipping",
  "7. Approved list for M0–M5",
  "8. Open items and hand-offs",
  "9. Sources",
];
const LIBRARY_HEADER = ["Component", "Version reviewed", "Licence (SPDX)", "Serves", "Shipped", "Risk", "Verdict", "Alternative", "Conditions", "Source"];
const MODEL_HEADER = ["Model", "Role", "Revision", "Licence (SPDX)", "Commercial use", "Self-hosted use", "Conditions", "Verdict", "Source"];
const VERDICTS = ["approved", "approved with conditions", "dev only", "ideas only", "not approved", "do not use"];
const APPROVED = VERDICTS.slice(0, 2);
const USABLE = [...APPROVED, "dev only"];
const SHIPPED = ["yes", "dev only", "no"];
const RISK_CATEGORIES = ["Low", "Weak copyleft", "Aggregated OS packages", "Strong copyleft", "Network copyleft", "Source-available", "Restricted model terms", "Custom terms", "Commercial terms"];
const RED_FLAG_CATEGORIES = RISK_CATEGORIES.slice(3);
// Also catches non-commercial and field-of-use model licences (CC-BY-NC, OpenRAIL, research-only).
const RISKY_LICENCE = /AGPL|SSPL|RSAL|BUSL|Elastic-2\.0|Commons-Clause|LicenseRef-|(?<!L)GPL|-NC(?:-|\b)|NonCommercial|RAIL|research/i;
const MODEL_ROLES = ["LLM ~4B", "LLM larger", "Embedding", "Reranker"];
const REQUIRED = [
  ["pypdf"], ["pdfplumber"], ["PyMuPDF"], ["python-docx"], ["openpyxl"],
  ["langchain-text-splitters", "semchunk", "tokenizers"], ["bge-m3"],
  ["bge-reranker-v2-m3", "Qwen3-Reranker"], ["Qwen3-4B-Instruct-2507"], ["pgvector"], ["PostgreSQL"],
  ["ParadeDB"], ["llama.cpp"], ["vLLM"], ["PyJWT"], ["underthesea"], ["pyvi"], ["Unidecode"],
  ["anyascii"], ["psycopg"], ["Valkey"], ["Redis"], ["MinIO"], ["Vault"], ["IBM Plex"], ["Dify"],
  ["MaxKB"], ["AnythingLLM"],
];
const KNOWN_RED_FLAGS = ["PyMuPDF", "MinIO", "ParadeDB", "Redis server", "Vault", "Unidecode", "Dify", "MaxKB"];
const ADR_SHARED = ["PyMuPDF", "MinIO", "ParadeDB", "Valkey", "Unidecode", "underthesea", "psycopg", "pgvector", "llama.cpp", "vLLM", "bge-m3", "DOMPurify"];

const cache = new Map();
const read = (file) => (cache.has(file) ? cache.get(file) : cache.set(file, fs.readFileSync(file, "utf8")).get(file));
const isPlaceholder = (cell) => ["", "-", "—", "?", "tbd", "todo", "n/a"].includes(cell.trim().toLowerCase());
const lower = (s) => s.toLowerCase();

function sections(md) {
  const parts = md.split(/^## /m).slice(1);
  return parts.map((part) => {
    const [title, ...body] = part.split("\n");
    return { title: title.trim(), body: body.join("\n") };
  });
}

function tables(body) {
  const lines = body.replace(/^```[\s\S]*?^```/gm, "").split("\n").concat("");
  const result = [];
  let current = [];
  for (const line of lines) {
    if (line.trimStart().startsWith("|")) {
      const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (!cells.every((c) => /^:?-+:?$/.test(c))) current.push(cells);
    } else if (current.length) {
      result.push(current);
      current = [];
    }
  }
  return result;
}

const rowsAsObjects = ([header, ...rows]) => rows.map((row) => Object.fromEntries(header.map((name, i) => [name, row[i] ?? ""])));

function spdxIds(cell) {
  return cell.split(/ OR | AND |[,;/()]/).map((id) => id.trim()).filter(Boolean);
}
const normaliseSpdx = (id) => id.replace(/-only$|-or-later$|\+$/i, "");
const hasWord = (text, word) => new RegExp(`\\b${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(text);

function sectionOf(file, number) {
  const section = sections(read(file)).find((s) => s.title.startsWith(`${number}. `));
  assert.ok(section, `${path.basename(file)} section ${number} is missing`);
  return section;
}
const reviewSection = (number) => sectionOf(REVIEW, number);
const adrSection = (number) => sectionOf(ADR, number);

const libraryTable = () => tables(reviewSection(2).body)[0];
const modelTable = () => tables(reviewSection(3).body)[0];
const libraryRows = () => rowsAsObjects(libraryTable());
const modelRows = () => rowsAsObjects(modelTable());
const riskCategory = (row) => RISK_CATEGORIES.find((c) => row.Risk === c || row.Risk.startsWith(`${c}:`));
const isRedFlag = (row) => RED_FLAG_CATEGORIES.includes(riskCategory(row));
const findRow = (rows, key, name) => rows.find((r) => lower(r[key]).includes(lower(name)));

// ---- AC1: library table -------------------------------------------------------------------

test("review_file_exists_at_the_agreed_path", () => {
  assert.ok(fs.existsSync(REVIEW), `missing ${REVIEW}`);
});

test("review_has_required_headings_and_status", () => {
  const md = read(REVIEW);
  assert.deepEqual(sections(md).map((s) => s.title), HEADINGS);
  assert.match(md, /^- Status: \S+/m);
  assert.match(md, /^- Date: \d{4}-\d{2}-\d{2}/m);
  assert.ok(md.includes("EA-12"));
});

test("library_table_has_the_required_columns", () => {
  assert.deepEqual(libraryTable()[0], LIBRARY_HEADER);
});

test("library_table_lists_at_least_15_components", () => {
  const names = libraryRows().map((r) => r.Component);
  assert.ok(names.length >= 15, `only ${names.length} rows`);
  assert.equal(new Set(names.map(lower)).size, names.length, "duplicate Component values");
});

test("every_row_has_version_licence_serves_risk_verdict_and_source", () => {
  for (const row of libraryRows()) {
    for (const column of ["Component", "Version reviewed", "Licence (SPDX)", "Serves", "Shipped", "Risk", "Verdict", "Source"]) {
      assert.ok(!isPlaceholder(row[column]), `${row.Component}: empty ${column}`);
    }
    assert.ok(SHIPPED.includes(row.Shipped), `${row.Component}: Shipped "${row.Shipped}"`);
    assert.ok(row.Source.includes("https://"), `${row.Component}: Source has no https URL`);
  }
});

test("risk_uses_a_known_category", () => {
  for (const row of libraryRows()) {
    const category = riskCategory(row);
    assert.ok(category, `${row.Component}: unknown Risk "${row.Risk}"`);
    if (RISKY_LICENCE.test(row["Licence (SPDX)"])) {
      assert.ok(isRedFlag(row) || category === "Aggregated OS packages", `${row.Component}: licence "${row["Licence (SPDX)"]}" labelled "${category}"`);
    }
    if (["Weak copyleft", "Aggregated OS packages"].includes(category) && APPROVED.includes(row.Verdict)) {
      assert.ok(!isPlaceholder(row.Conditions), `${row.Component}: ${category} needs Conditions`);
    }
  }
});

test("covers_every_component_in_the_ticket_scope", () => {
  const names = libraryRows().map((r) => lower(r.Component));
  const missing = REQUIRED.filter((alts) => !alts.some((alt) => names.some((n) => n.includes(lower(alt)))));
  assert.deepEqual(missing, [], `missing components: ${missing.map((m) => m.join("|")).join(", ")}`);
});

test("reviews_every_poc_pin", (t) => {
  if (!fs.existsSync(POC_DIR)) return t.skip("PoC removed by SET-03");
  const rows = libraryRows();
  const md = read(REVIEW);
  const pins = [...read(POC_REQ).matchAll(/^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==(\S+)/gm)];
  assert.ok(pins.length > 0, "no pins found in requirements.txt");
  for (const [, name, version] of pins) {
    const row = rows.find((r) => lower(r.Component).includes(lower(name)) && r["Version reviewed"].includes(version));
    assert.ok(row, `no row for pin ${name}==${version}`);
  }
  const compose = read(POC_COMPOSE);
  const images = [...compose.matchAll(/^\s*image:\s*(\S+)/gm)].map((m) => m[1]);
  images.push(read(POC_DOCKERFILE).match(/^FROM\s+(\S+)/m)[1]);
  assert.ok(images.length >= 4, "expected compose images and the Dockerfile base image");
  for (const image of images) assert.ok(md.includes(image), `image ${image} is not reviewed`);
  const revision = compose.match(/\/resolve\/([0-9a-f]{40})\//)[1];
  assert.ok(reviewSection(3).body.includes(revision), `model revision ${revision} missing in section 3`);
});

// ---- AC2: red flags -----------------------------------------------------------------------

test("verdicts_use_the_controlled_vocabulary", () => {
  for (const row of [...libraryRows(), ...modelRows()]) {
    assert.ok(VERDICTS.includes(row.Verdict), `${row.Component ?? row.Model}: Verdict "${row.Verdict}"`);
  }
});

function hasApprovedAlternative(row, rows) {
  const alternative = lower(row.Alternative);
  if (isPlaceholder(alternative)) return false;
  if (alternative.startsWith("own ")) return true;
  return rows.some((other) => other !== row && USABLE.includes(other.Verdict) && alternative.startsWith(lower(other.Component)));
}

test("every_red_flag_row_is_do_not_use_or_has_an_approved_alternative", () => {
  const rows = libraryRows();
  for (const row of rows.filter(isRedFlag)) {
    assert.ok(!APPROVED.includes(row.Verdict), `${row.Component}: red flag cannot be "${row.Verdict}"`);
    assert.ok(row.Verdict === "do not use" || hasApprovedAlternative(row, rows), `${row.Component}: "${row.Verdict}" without an approved alternative ("${row.Alternative}")`);
  }
});

test("known_red_flags_are_listed", () => {
  const rows = libraryRows();
  for (const name of KNOWN_RED_FLAGS) {
    const row = findRow(rows, "Component", name);
    assert.ok(row, `no row for ${name}`);
    assert.ok(isRedFlag(row), `${name}: Risk "${row.Risk}" is not a red-flag category`);
    assert.ok(["do not use", "not approved"].includes(row.Verdict), `${name}: Verdict "${row.Verdict}"`);
  }
});

// ---- AC3: model weights -------------------------------------------------------------------

test("model_table_has_the_required_columns", () => {
  assert.deepEqual(modelTable()[0], MODEL_HEADER);
});

test("every_proposed_model_allows_commercial_and_self_hosted_use", () => {
  for (const row of modelRows()) {
    assert.ok(MODEL_ROLES.includes(row.Role), `${row.Model}: Role "${row.Role}"`);
    if (APPROVED.includes(row.Verdict)) {
      assert.ok(!RISKY_LICENCE.test(row["Licence (SPDX)"]), `${row.Model}: approved with restricted licence "${row["Licence (SPDX)"]}"`);
      assert.equal(row["Commercial use"], "yes", `${row.Model}: commercial use`);
      assert.equal(row["Self-hosted use"], "yes", `${row.Model}: self-hosted use`);
    }
  }
});

test("proposes_an_llm_4b_a_larger_llm_an_embedding_and_a_reranker", () => {
  const rows = modelRows().filter((r) => APPROVED.includes(r.Verdict));
  const missing = MODEL_ROLES.filter((role) => !rows.some((r) => r.Role === role));
  assert.deepEqual(missing, [], `no approved model for: ${missing.join(", ")}`);
});

test("every_proposed_model_is_pinned_to_a_revision", () => {
  for (const row of modelRows().filter((r) => APPROVED.includes(r.Verdict))) {
    assert.match(row.Revision, /[0-9a-f]{40}/, `${row.Model}: revision`);
  }
});

test("every_model_is_also_in_the_library_table", () => {
  const rows = libraryRows();
  for (const row of modelRows()) {
    const other = rows.find((r) => lower(r.Component) === lower(row.Model));
    assert.ok(other, `${row.Model} is not in section 2`);
    assert.equal(other.Verdict, row.Verdict, `${row.Model}: verdict differs between section 2 and 3`);
    assert.equal(other["Licence (SPDX)"], row["Licence (SPDX)"], `${row.Model}: licence differs between section 2 and 3`);
  }
});

// ---- AC4: link with the ADR ---------------------------------------------------------------

test("adr_links_to_the_review", () => {
  assert.ok(adrSection(1).body.includes("](oss-license-review.md)"), "ADR section 1 has no link");
  assert.ok(adrSection(10).body.includes("](oss-license-review.md)"), "ADR section 10 has no link");
  assert.ok(adrSection(12).body.includes("oss-license-review.md"), "ADR section 12 has no reference");
});

test("adr_has_no_unverified_set02_markers", () => {
  const marker = /to verify in SET-02|after SET-02|legal review in SET-02|SET-02 confirms|produced by SET-02.*pending/i;
  const hits = read(ADR).split("\n").map((line, i) => [i + 1, line]).filter(([, line]) => marker.test(line));
  assert.deepEqual(hits.map(([n]) => n), [], "ADR lines with SET-02 markers");
});

test("adr_and_review_agree_on_shared_licences", () => {
  const adrRows = tables(adrSection(10).body)[0].slice(1);
  const rows = libraryRows();
  const mismatches = [];
  for (const name of ADR_SHARED) {
    const adrRow = adrRows.find((r) => lower(r[0]).includes(lower(name)));
    const row = findRow(rows, "Component", name);
    if (!adrRow || !row) {
      mismatches.push(`${name}: missing in ${adrRow ? "review" : "ADR section 10"}`);
      continue;
    }
    for (const id of spdxIds(row["Licence (SPDX)"]).filter((i) => !i.startsWith("LicenseRef-"))) {
      if (!hasWord(adrRow[1], normaliseSpdx(id))) mismatches.push(`${name}: review "${id}" not in ADR "${adrRow[1]}"`);
    }
  }
  assert.deepEqual(mismatches, []);
});
