// Validator and CLI for the Mekong Devworks test set (EA-16).
// Run: node eval/datasets/mekong-devworks/tools/validate.mjs [dir]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { DEFAULT_CONFIG } from "./schema.mjs";
import { parseJsonl } from "./jsonl.mjs";
import { validateScripts, validateCsv } from "./validate-scripts.mjs";
import { validateQuestions } from "./validate-questions.mjs";

const EMPTY_REGISTRY = { phones: [], emails: [], national_ids: [], names: [] };

export function loadDataset(dir) {
  const parseErrors = [];
  const read = (file) => {
    try {
      return fs.readFileSync(path.join(dir, file), "utf8");
    } catch (e) {
      parseErrors.push({ file, line: 0, message: `cannot read ${file}: ${e.code ?? e.message}` });
      return "";
    }
  };
  const jsonl = (file) => {
    const { records, errors } = parseJsonl(read(file));
    for (const e of errors) parseErrors.push({ file, ...e });
    return records;
  };
  let registry = EMPTY_REGISTRY;
  try {
    registry = JSON.parse(read("fake_personal_data.json"));
  } catch (e) {
    parseErrors.push({ file: "fake_personal_data.json", line: 0, message: `invalid JSON: ${e.message}` });
  }
  return { scripts: jsonl("scripts.jsonl"), questions: jsonl("test_questions.jsonl"), csvText: read("scripts.csv"), registry, parseErrors };
}

export function validateDataset({ scripts, questions, csvText, registry, parseErrors = [] }, config = DEFAULT_CONFIG) {
  const errors = parseErrors.map((e) => ({ file: e.file, line: e.line, rule: "json", message: e.message }));
  const scriptResult = validateScripts(scripts, registry, config);
  const questionResult = validateQuestions(questions, scripts.map((s) => s.value), registry, config);
  errors.push(...scriptResult.errors, ...validateCsv(csvText, scripts, config), ...questionResult.errors);
  return { errors, stats: { scripts: scripts.length, pairs: scriptResult.pairs, ...questionResult.stats } };
}

export function summarise(stats) {
  const groups = Object.entries(stats.byGroup).map(([g, n]) => `${g} ${n}`).join(", ");
  return `OK: ${stats.scripts} scripts, ${stats.questions} questions (${groups}; en ${stats.byLanguage.en ?? 0} / vi ${stats.byLanguage.vi ?? 0})`;
}

function main() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const dir = path.resolve(process.argv[2] ?? path.join(here, ".."));
  const { errors, stats } = validateDataset(loadDataset(dir));
  if (errors.length === 0) {
    console.log(summarise(stats));
    return 0;
  }
  for (const e of errors) console.log(`${e.file}${e.line ? `:${e.line}` : ""} ${e.rule} ${e.message}`);
  console.log(`FAILED: ${errors.length} error(s)`);
  return 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = main();
