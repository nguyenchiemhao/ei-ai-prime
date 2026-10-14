// Builds scripts.csv (PIPE-04 import format) from scripts.jsonl. Never hand-edit scripts.csv.
// Run: node eval/datasets/mekong-devworks/tools/build-scripts-csv.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { formatCsv } from "./csv.mjs";
import { readJsonl } from "./jsonl.mjs";
import { DEFAULT_CONFIG } from "./schema.mjs";

export function buildScriptsCsv(scripts) {
  const rows = scripts.map((s) => ({
    external_id: s.id,
    title: s.title,
    questions_en: s.questions_en.join("|"),
    questions_vi: s.questions_vi.join("|"),
    answer_en: s.answer_en,
    answer_vi: s.answer_vi,
    mode: s.mode,
    action_type: s.action_type,
    action_value: s.action_value,
    status: s.status,
    start_date: s.start_date,
    end_date: s.end_date,
  }));
  return formatCsv(rows, DEFAULT_CONFIG.csvColumns);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const dir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const { records, errors } = readJsonl(path.join(dir, "scripts.jsonl"));
  if (errors.length) {
    console.error(errors.map((e) => `scripts.jsonl:${e.line} ${e.message}`).join("\n"));
    process.exitCode = 1;
  } else {
    fs.writeFileSync(path.join(dir, "scripts.csv"), buildScriptsCsv(records.map((r) => r.value)));
    console.log(`wrote scripts.csv (${records.length} rows)`);
  }
}
