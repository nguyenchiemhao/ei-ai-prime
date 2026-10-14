// Cross-labelling helper (AC5).
// Run: node eval/datasets/mekong-devworks/tools/cross-labelling.mjs <command> ...   (from the repository root)
//   sample                         draw 100 question ids (seed 16) into cross_labelling/sample.json
//   key-map                        shuffle the sample (seed 160) and give each row an opaque key r-001...: cross_labelling/key_map.json
//                                  (the key map is NOT given to a labeller)
//   blind-sheet                    write cross_labelling/blind_sheet.csv (opaque keys, no id, no group, no labels)
//   snapshot                       freeze the current dataset labels as cross_labelling/labeller_1_author.csv
//   agreement <fileA> <fileB> [--out file]   compare two labeller files (paths relative to the dataset folder)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { formatCsv } from "./csv.mjs";
import { readJsonl } from "./jsonl.mjs";
import { DEFAULT_CONFIG } from "./schema.mjs";
import { compareLabellers, parseAgreementArgs } from "./agreement.mjs";

export const SEED = 16;
export const KEY_SEED = 160;
export const SAMPLE_SIZE = 100;
const DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CROSS = path.join(DIR, "cross_labelling");

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffled(list, seed) {
  const out = [...list];
  const random = mulberry32(seed);
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function sampleIds(allIds, seed, size) {
  return shuffled(allIds, seed).slice(0, size).sort();
}

export function buildKeyMap(ids, seed) {
  return shuffled(ids, seed).map((id, i) => ({ key: `r-${String(i + 1).padStart(3, "0")}`, id }));
}

export function renderHistory(history) {
  return history.map((t) => `User: ${t.user} / Assistant: ${t.assistant}`).join(" / ");
}

function inKeyOrder(questions, keyMap) {
  const byId = new Map(questions.map((q) => [q.id, q]));
  return keyMap.map(({ key, id }) => {
    if (!byId.has(id)) throw new Error(`key map points to unknown question ${id}`);
    return { key, q: byId.get(id) };
  });
}

export function buildBlindSheet(questions, keyMap) {
  const rows = inKeyOrder(questions, keyMap).map(({ key, q }) => ({
    key,
    language: q.language,
    history: renderHistory(q.history),
    question: q.question,
    type: "",
    correct_script: "",
    note: "",
  }));
  return formatCsv(rows, ["key", "language", "history", "question", "type", "correct_script", "note"]);
}

export function buildSnapshot(questions, keyMap) {
  const rows = inKeyOrder(questions, keyMap).map(({ key, q }) => ({ key, type: q.type, correct_script: q.correct_script, note: "" }));
  return formatCsv(rows, ["key", "type", "correct_script", "note"]);
}

function loadQuestions() {
  const { records, errors } = readJsonl(path.join(DIR, "test_questions.jsonl"));
  if (errors.length) throw new Error(`test_questions.jsonl has ${errors.length} invalid line(s)`);
  return records.map((r) => r.value);
}

const loadJson = (file) => JSON.parse(fs.readFileSync(path.join(CROSS, file), "utf8"));
const writeJson = (file, value) => fs.writeFileSync(path.join(CROSS, file), JSON.stringify(value, null, 2) + "\n");

function runAgreement(args) {
  const { fileA, fileB, out } = parseAgreementArgs(args);
  const target = out ? path.resolve(DIR, out) : path.join(CROSS, "agreement.json");
  const rows = loadJson("key_map.json").rows;
  const ctx = {
    keys: rows.map((r) => r.key),
    types: DEFAULT_CONFIG.types,
    scripts: readJsonl(path.join(DIR, "scripts.jsonl")).records.map((r) => r.value.id),
  };
  const result = compareLabellers(path.resolve(DIR, fileA), path.resolve(DIR, fileB), new Map(rows.map((r) => [r.key, r.id])), ctx);
  const existing = fs.existsSync(target) ? JSON.parse(fs.readFileSync(target, "utf8")) : {};
  existing[`${path.basename(fileA)} vs ${path.basename(fileB)}`] = result;
  fs.writeFileSync(target, JSON.stringify(existing, null, 2) + "\n");
  console.log(
    `wrote ${path.relative(process.cwd(), target)}: type kappa ${result.type.kappa.toFixed(2)}, script kappa ${result.correct_script.kappa.toFixed(2)}, ${result.disagreements.length} disagreement(s)`,
  );
}

function main([command, ...args]) {
  if (command === "sample") {
    const ids = sampleIds(loadQuestions().map((q) => q.id), SEED, SAMPLE_SIZE);
    writeJson("sample.json", { seed: SEED, size: SAMPLE_SIZE, ids });
    console.log(`wrote sample.json (${ids.length} ids, seed ${SEED})`);
  } else if (command === "key-map") {
    const rows = buildKeyMap(loadJson("sample.json").ids, KEY_SEED);
    writeJson("key_map.json", { seed: KEY_SEED, rows });
    console.log(`wrote key_map.json (${rows.length} rows, seed ${KEY_SEED}); do not give it to a labeller`);
  } else if (command === "blind-sheet") {
    fs.writeFileSync(path.join(CROSS, "blind_sheet.csv"), buildBlindSheet(loadQuestions(), loadJson("key_map.json").rows));
    console.log("wrote blind_sheet.csv");
  } else if (command === "snapshot") {
    const target = path.join(CROSS, "labeller_1_author.csv");
    if (fs.existsSync(target)) throw new Error("labeller_1_author.csv already exists: it is a frozen snapshot and is never regenerated");
    fs.writeFileSync(target, buildSnapshot(loadQuestions(), loadJson("key_map.json").rows));
    console.log("wrote labeller_1_author.csv");
  } else if (command === "agreement") {
    runAgreement(args);
  } else {
    throw new Error("usage: cross-labelling.mjs <sample|key-map|blind-sheet|snapshot|agreement>");
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main(process.argv.slice(2));
  } catch (e) {
    console.error(e.message);
    process.exitCode = 1;
  }
}
