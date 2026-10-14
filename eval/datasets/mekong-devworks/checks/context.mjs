// Shared context of the integration checks: the real files of the data set, loaded and validated once.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadDataset, validateDataset } from "../tools/validate.mjs";

export const DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const read = (f) => fs.readFileSync(path.join(DIR, f), "utf8").replace(/\r\n/g, "\n");

export const dataset = loadDataset(DIR);
export const scripts = dataset.scripts.map((r) => r.value);
export const questions = dataset.questions.map((r) => r.value);
export const result = validateDataset(dataset);

export function assertNoErrors(...rules) {
  const found = result.errors.filter((e) => rules.includes(e.rule));
  assert.deepEqual(found.map((e) => `${e.file}:${e.line} ${e.rule} ${e.message}`), []);
}
