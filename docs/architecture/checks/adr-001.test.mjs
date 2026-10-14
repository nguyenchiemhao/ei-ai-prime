// EA-11 (SET-01) AC1, AC2, AC5, AC6: structural checks of docs/architecture/adr-001-tech-stack.md.
// Node port (EA-13) of the Python check that lived in the stack-spike PoC.
//
// The content (is the choice sensible, is each licence claim correct) is checked by the reviewer;
// these tests make sure no required part is missing or left as a placeholder.
//
// Run:  node --test docs/architecture/checks/adr-001.test.mjs
// Override the file under test (used for mutation checks): ADR_FILE=<path>
// No network, no dependencies.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ADR_FILE = path.resolve(ROOT, process.env.ADR_FILE || "docs/architecture/adr-001-tech-stack.md");

const COMPONENT_TITLES = {
  "3.1": "Backend language and framework",
  "3.2": "Database and tenant isolation",
  "3.3": "Vector store",
  "3.4": "Keyword search",
  "3.5": "File storage and per-Organization encryption",
  "3.6": "Local model serving",
  "3.7": "Models: LLM, embedding, reranker",
  "3.8": "Admin frontend",
  "3.9": "Widget",
  "3.10": "Background jobs",
  "3.11": "Rate-limit store and cache",
  "3.12": "Packaging and local environment",
  "3.13": "Authentication and identity tokens",
  "3.14": "Egress proxy",
  "3.15": "Logging, tracing and masking",
};

const SECTION_TITLES = {
  1: "Context",
  2: "Selection criteria",
  3: "Decisions per component",
  4: "Architecture overview",
  5: "Foundations F1–F15 mapping",
  6: "Self-hosted single-Organization install",
  7: "Frontend fit with DSN-01",
  8: "Dev machine fit and RAM budget",
  9: "Isolation PoC results",
  10: "Licence notes and red flags",
  11: "Consequences, risks and revisit triggers",
  12: "References",
};

const PLACEHOLDER_CELLS = new Set(["", "-", "?", "tbd", "todo", "n/a"]);
const FENCE = /^```.*?^```/gms;

assert.ok(fs.existsSync(ADR_FILE), `ADR not found at ${ADR_FILE}`);
const adr = fs.readFileSync(ADR_FILE, "utf8");

/** Split on headings of one level into [number, title, body]; a body ends at the next heading of the same or a higher level. */
function split(text, level) {
  const marker = "#".repeat(level);
  const heading = new RegExp(`^${marker} (\\d+(?:\\.\\d+)?)\\.? (.*)$`, "gm");
  const higher = new RegExp(`^#{1,${level}} `, "gm");
  const parts = [];
  for (const match of text.matchAll(heading)) {
    const bodyStart = match.index + match[0].length;
    higher.lastIndex = bodyStart;
    const following = higher.exec(text);
    parts.push([match[1], match[2].trim(), text.slice(bodyStart, following ? following.index : text.length)]);
  }
  return parts;
}

const titles = (level) => Object.fromEntries(split(adr, level).map(([number, title]) => [number, title]));

/** Body of `## <number>.` (level 2) or `### <number>` (level 3). */
function section(number) {
  const level = number.includes(".") ? 3 : 2;
  const found = split(adr, level).find(([n]) => n === number);
  assert.ok(found, `section ${number} not found`);
  return found[2];
}

const isSeparator = (row) => row.every((cell) => /^:?-+:?$/.test(cell));

/** Markdown tables of a section body as rows of cells (separator row removed, header kept). */
function tables(body) {
  const lines = [...body.replace(FENCE, "").split("\n"), ""];
  const result = [];
  let current = [];
  for (const line of lines) {
    if (line.trimStart().startsWith("|")) {
      current.push(line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
    } else if (current.length) {
      result.push(current.filter((row) => !isSeparator(row)));
      current = [];
    }
  }
  return result;
}

const hasMermaid = (body) => /^```mermaid\b/m.test(body);

test("adr_file_exists_with_status_and_ticket", () => {
  assert.match(adr, /^- Status: (Proposed|Accepted)\b/m);
  assert.ok(adr.includes("EA-11"));
});

test("has_required_headings", () => {
  assert.deepEqual(titles(2), SECTION_TITLES);
  assert.deepEqual(titles(3), COMPONENT_TITLES);
});

test("lists_selection_criteria_table", () => {
  const rows = tables(section("2")).flat();
  const criteria = rows.filter((row) => /^C\d+$/.test(row[0]));
  assert.ok(criteria.length >= 5, `only ${criteria.length} criteria`);
});

for (const number of Object.keys(COMPONENT_TITLES)) {
  test(`every_main_component_has_at_least_two_options_${number}`, () => {
    const found = tables(section(number));
    assert.ok(found.length > 0, `section ${number} has no options table`);
    const [header, ...options] = found[0];
    assert.ok(header[0].toLowerCase().startsWith("option"), `section ${number}: first column is "${header[0]}"`);
    assert.ok(options.length >= 2, `section ${number}: only ${options.length} options`);
  });
}

for (const number of Object.keys(COMPONENT_TITLES)) {
  test(`every_main_component_has_choice_and_reasons_${number}`, () => {
    const body = section(number);
    assert.match(body, /^\*\*Choice:\*\*\s*\S+/m, `section ${number}: no Choice`);
    assert.match(body, /^\*\*Reasons:\*\*/m, `section ${number}: no Reasons`);
  });
}

function foundationRows() {
  const found = tables(section("5"));
  assert.ok(found.length > 0, "section 5 has no table");
  return found[0].slice(1);
}

test("maps_every_foundation_f1_to_f15", () => {
  assert.deepEqual(foundationRows().map((row) => row[0]), Array.from({ length: 15 }, (_, i) => `F${i + 1}`));
});

test("no_foundation_row_has_empty_or_placeholder_cell", () => {
  for (const row of foundationRows()) {
    assert.equal(row.length, 5, `${row[0]} must have 5 cells`);
    for (const cell of row) assert.ok(!PLACEHOLDER_CELLS.has(cell.trim().toLowerCase()), `${row[0]} has a placeholder cell`);
  }
});

test("has_no_tbd_or_todo_markers", () => {
  assert.doesNotMatch(adr, /\b(TBD|TODO)\b/);
});

test("has_self_host_section_with_topology_and_config_differences", () => {
  const body = section("6");
  assert.ok(hasMermaid(body), "no mermaid topology");
  assert.ok(tables(body).some((table) => table[0].join(" ").includes("Self-hosted")), "no Self-hosted comparison table");
  assert.ok(body.includes("D6"));
});

test("frontend_fit_section_covers_dsn01_requirements", () => {
  const body = section("7").toLowerCase();
  const required = [["ibm plex"], ["vietnamese"], ["token"], ["iframe"], ["settokenprovider"], ["stream"], ["abort", "stop"], ["i18n"], ["aria", "accessib"], ["bundle"]];
  for (const alternatives of required) {
    assert.ok(alternatives.some((word) => body.includes(word)), `section 7 misses ${alternatives}`);
  }
});

test("ram_budget_mentions_16_gb_and_one_command", () => {
  const body = section("8");
  assert.ok(body.includes("16 GB"));
  assert.ok(body.includes("--profile model up"));
});

test("architecture_overview_has_mermaid_diagram", () => {
  assert.ok(hasMermaid(section("4")));
});
