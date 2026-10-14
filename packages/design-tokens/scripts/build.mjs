// Compiles design-tokens.json (W3C DTCG) to dist/tokens.css: one `--ei-<path>` custom property per token.
// References such as {color.status.success.text} become var(--ei-color-status-success-text), so a
// per-Channel override of the target cascades to every token that points at it (WGT-07).
// Built-ins only; deterministic (sorted, LF).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REFERENCE = /^\{([^{}]+)\}$/;

const variableName = (tokenPath) => `--ei-${tokenPath.replace(/\./g, "-")}`;

function collect(node, trail, inheritedType, out) {
  const type = node.$type ?? inheritedType;
  if ("$value" in node) {
    out.push({ path: trail.join("."), type, value: node.$value });
    return;
  }
  for (const [key, child] of Object.entries(node)) {
    if (!key.startsWith("$")) collect(child, [...trail, key], type, out);
  }
}

function formatValue(token, known) {
  const reference = typeof token.value === "string" ? token.value.match(REFERENCE) : null;
  if (reference) {
    if (!known.has(reference[1]))
      throw new Error(`token ${token.path} references unknown token ${reference[1]}`);
    return `var(${variableName(reference[1])})`;
  }
  if (token.type === "dimension" && typeof token.value === "number") return `${token.value}px`;
  return String(token.value);
}

/** The CSS text for a token document. */
export function compileTokens(document) {
  const tokens = [];
  collect(document, [], undefined, tokens);
  const known = new Set(tokens.map((token) => token.path));
  const lines = tokens
    .map((token) => [variableName(token.path), formatValue(token, known)])
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const names = new Set(lines.map(([name]) => name));
  if (names.size !== lines.length)
    throw new Error("two tokens compile to the same CSS variable name");
  return `/* Generated from design-tokens.json by scripts/build.mjs. Do not edit. */\n:root {\n${lines.map(([n, v]) => `  ${n}: ${v};`).join("\n")}\n}\n`;
}

export function buildTokens() {
  const document = JSON.parse(fs.readFileSync(path.join(PACKAGE, "design-tokens.json"), "utf8"));
  const css = compileTokens(document);
  fs.mkdirSync(path.join(PACKAGE, "dist"), { recursive: true });
  fs.writeFileSync(path.join(PACKAGE, "dist", "tokens.css"), css);
  return css;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const css = buildTokens();
  console.log(
    `design-tokens: wrote dist/tokens.css (${css.split("\n").filter((l) => l.startsWith("  --")).length} variables)`,
  );
}
