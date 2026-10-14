// JSON Lines reader that reports parse errors with 1-based line numbers instead of throwing.
import fs from "node:fs";

export function parseJsonl(text) {
  const records = [];
  const errors = [];
  const lines = text.replace(/^﻿/, "").replace(/\r\n/g, "\n").split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  lines.forEach((raw, i) => {
    const line = i + 1;
    try {
      records.push({ line, value: JSON.parse(raw) });
    } catch (e) {
      errors.push({ line, message: `invalid JSON: ${e.message}` });
    }
  });
  return { records, errors };
}

export function readJsonl(file) {
  return parseJsonl(fs.readFileSync(file, "utf8"));
}
