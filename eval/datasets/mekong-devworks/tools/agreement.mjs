// Inter-labeller agreement (AC5): strict label-file validation, percent agreement and Cohen's kappa.
import fs from "node:fs";
import { parseCsv } from "./csv.mjs";

export function percentAgreement(a, b) {
  if (a.length !== b.length || a.length === 0) throw new Error("label lists must have the same non-zero length");
  return a.filter((x, i) => x === b[i]).length / a.length;
}

export function cohenKappa(a, b) {
  const po = percentAgreement(a, b);
  const n = a.length;
  const count = (list) => list.reduce((m, x) => m.set(x, (m.get(x) ?? 0) + 1), new Map());
  const ca = count(a);
  const cb = count(b);
  let pe = 0;
  for (const [label, na] of ca) pe += (na / n) * ((cb.get(label) ?? 0) / n);
  if (pe === 1) return po === 1 ? 1 : 0;
  return (po - pe) / (1 - pe);
}

function stats(a, b) {
  return { agreement: percentAgreement(a, b), kappa: cohenKappa(a, b) };
}

// rows: [{key, type, correct_script, note}]; ctx: {keys, types, scripts}.
// Returns the labels by row key and a list of human-readable problems (empty when the file is usable).
export function validateLabelRows(rows, ctx) {
  const problems = [];
  const labels = new Map();
  const expected = new Set(ctx.keys);
  const validScripts = new Set([...ctx.scripts, "NONE"]);
  rows.forEach((r, i) => {
    const key = (r.key ?? "").trim();
    const where = `row ${i + 1} (${key || "no key"})`;
    if (!expected.has(key)) return problems.push(`${where}: unknown key ${key || "(blank)"}`);
    if (labels.has(key)) return problems.push(`${where}: duplicate key ${key}`);
    const type = (r.type ?? "").trim();
    const correct_script = (r.correct_script ?? "").trim();
    if (!ctx.types.includes(type)) problems.push(`${where}: type "${type}" is blank or not one of ${ctx.types.join("/")}`);
    if (!validScripts.has(correct_script)) problems.push(`${where}: correct_script "${correct_script}" is blank or not a script id or NONE`);
    labels.set(key, { type, correct_script });
  });
  const missing = ctx.keys.filter((k) => !labels.has(k));
  if (missing.length) problems.push(`missing row(s): ${missing.join(", ")}`);
  return { labels, problems };
}

export function readLabelFile(file, ctx) {
  const { header, rows } = parseCsv(fs.readFileSync(file, "utf8"));
  const lacking = ["key", "type", "correct_script"].filter((h) => !header.includes(h));
  if (lacking.length) throw new Error(`${file}: header lacks column(s) ${lacking.join(", ")}`);
  const { labels, problems } = validateLabelRows(rows, ctx);
  if (problems.length) throw new Error(`${file} is not usable:\n  ${problems.join("\n  ")}`);
  return labels;
}

// labelsA / labelsB: Map(key -> {type, correct_script}); keyToId: Map(key -> question id).
export function compareLabels(labelsA, labelsB, keyToId) {
  const keys = [...keyToId.keys()];
  const field = (labels, f) => keys.map((k) => labels.get(k)[f]);
  const both = (labels) => keys.map((k) => `${labels.get(k).type}|${labels.get(k).correct_script}`);
  const differs = (k) => labelsA.get(k).type !== labelsB.get(k).type || labelsA.get(k).correct_script !== labelsB.get(k).correct_script;
  return {
    n: keys.length,
    type: stats(field(labelsA, "type"), field(labelsB, "type")),
    correct_script: stats(field(labelsA, "correct_script"), field(labelsB, "correct_script")),
    both: stats(both(labelsA), both(labelsB)),
    disagreements: keys.filter(differs).map((k) => ({ key: k, id: keyToId.get(k), a: labelsA.get(k), b: labelsB.get(k) })),
  };
}

export function compareLabellers(fileA, fileB, keyToId, ctx) {
  return compareLabels(readLabelFile(fileA, ctx), readLabelFile(fileB, ctx), keyToId);
}

export function parseAgreementArgs(args) {
  const files = [];
  let out = null;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--out") {
      if (!args[i + 1] || args[i + 1].startsWith("--")) throw new Error("--out needs a file name");
      out = args[++i];
    } else files.push(args[i]);
  }
  if (files.length !== 2) throw new Error("usage: agreement <fileA> <fileB> [--out file]");
  return { fileA: files[0], fileB: files[1], out };
}
