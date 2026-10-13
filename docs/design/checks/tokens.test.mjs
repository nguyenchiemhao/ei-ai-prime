// EA-85 (DSN-01) AC3, AC4: checks of docs/design/tokens/design-tokens.json (W3C design-token format)
// and of the contrast table in docs/design/tokens/README.md.
// AC3: the file is valid, every reference resolves, and the required tokens hold the EA-85 values.
// AC4: every pair in the README recomputes to its stated WCAG 2.x contrast ratio and meets its minimum,
//      and every text pair in use is listed.
//
// Run:  node --test docs/design/checks/tokens.test.mjs
// Override the files under test (used for mutation checks): TOKENS_FILE=<path> TOKENS_README=<path>
// (Node 22: pass the file path; `node --test <directory>` does not work.) No network, no dependencies.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const TOKENS_FILE = path.resolve(ROOT, process.env.TOKENS_FILE || "docs/design/tokens/design-tokens.json");
const README_FILE = path.resolve(ROOT, process.env.TOKENS_README || "docs/design/tokens/README.md");

const REQUIRED_VALUES = {
  "color.text.primary": "#16181D",
  "color.text.secondary": "#3F4752",
  "color.text.muted": "#555E6B",
  "color.border.default": "#E1E4E8",
  "color.border.strong": "#C9CED4",
  "color.surface.page": "#F7F7F8",
  "color.accent.default": "#2346C7",
  "color.accent.hover": "#1D3BAA",
  "color.accent.tint": "#E8EEFC",
  "color.brand.default": "#0E7C6B",
  "color.brand.text": "#0B6B5C",
  "color.brand.tint": "#F1F7F5",
  "color.status.success.text": "#1E6B34",
  "color.status.success.bg": "#E6F4EA",
  "color.status.warning.text": "#8A4205",
  "color.status.warning.strong": "#9A4A06",
  "color.status.warning.bg": "#FDF0E1",
  "color.border.field": "#8A929C",
  "size.target.min": "44px",
};
// Text pairs used on the canvas (minimum 4.5). Non-text pairs (minimum 3) are listed separately.
const REQUIRED_TEXT_PAIRS = [
  ["text.primary", "surface.card"], ["text.primary", "surface.page"], ["text.secondary", "surface.card"],
  ["text.secondary", "surface.muted"], ["text.muted", "surface.card"], ["text.muted", "surface.page"],
  ["text.muted", "surface.subtle"], ["text.muted", "surface.widget-canvas"], ["text.subtle", "surface.card"],
  ["text.subtle", "surface.subtle"], ["text.on-accent", "accent.default"], ["accent.default", "surface.card"],
  ["accent.hover", "accent.tint"], ["accent.hover", "accent.chip-bg"], ["text.on-accent", "brand.default"],
  ["brand.text", "surface.card"], ["brand.text", "brand.tint"], ["status.success.text", "status.success.bg"],
  ["status.warning.text", "status.warning.bg"], ["status.warning.strong", "status.warning.bg"],
  ["status.warning.deep", "status.warning.bg"], ["text.on-code", "surface.code"], ["text.nav", "surface.card"],
];
const REQUIRED_NON_TEXT_PAIRS = [["border.field", "surface.card"], ["accent.default", "surface.card"]];
const MINIMUMS = [4.5, 3];

const tokens = () => JSON.parse(fs.readFileSync(TOKENS_FILE, "utf8"));
const readme = () => fs.readFileSync(README_FILE, "utf8");

/** Flatten the token tree into { "a.b.c": { $value, $type } }, inheriting the group $type. */
function flatten(node, trail = [], inheritedType = undefined, out = {}) {
  const type = node.$type ?? inheritedType;
  if (Object.prototype.hasOwnProperty.call(node, "$value")) {
    out[trail.join(".")] = { $value: node.$value, $type: type };
    return out;
  }
  for (const [key, child] of Object.entries(node)) {
    if (key.startsWith("$")) continue;
    assert.equal(typeof child, "object", `${[...trail, key].join(".")}: group or token expected`);
    flatten(child, [...trail, key], type, out);
  }
  return out;
}

function resolve(flat, pathName, seen = new Set()) {
  assert.ok(!seen.has(pathName), `reference cycle at ${pathName}`);
  seen.add(pathName);
  const tok = flat[pathName];
  assert.ok(tok, `unknown token ${pathName}`);
  const ref = typeof tok.$value === "string" && tok.$value.match(/^\{([^}]+)\}$/);
  return ref ? resolve(flat, ref[1], seen) : tok.$value;
}

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (fg, bg) => {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
};

test("AC3: token file is valid DTCG, every reference resolves", () => {
  const root = tokens();
  assert.ok(root.$description && root.$description.includes("DSN-01"), "root $description");
  const flat = flatten(root);
  assert.ok(Object.keys(flat).length > 80, "token count");
  for (const [name, tok] of Object.entries(flat)) {
    assert.ok(tok.$type, `${name}: $type`);
    const resolved = resolve(flat, name);
    if (tok.$type === "color") assert.match(resolved, /^#[0-9A-F]{6}$/, `${name}: colour value`);
    if (tok.$type === "dimension") assert.match(String(resolved), /^\d+(\.\d+)?px$/, `${name}: dimension value`);
    if (tok.$type === "fontFamily") assert.equal(typeof resolved, "string", `${name}: font family`);
    if (tok.$type === "number") assert.equal(typeof resolved, "number", `${name}: number`);
  }
});

test("AC3: required tokens hold the EA-85 values", () => {
  const flat = flatten(tokens());
  for (const [name, expected] of Object.entries(REQUIRED_VALUES)) assert.equal(resolve(flat, name), expected, name);
  assert.match(resolve(flat, "font.family.sans"), /IBM Plex Sans/);
  assert.match(resolve(flat, "font.family.mono"), /IBM Plex Mono/);
});

/** README rows: | `fg` | `bg` | 17.76 | 4.5 | Used for | */
function readmePairs() {
  const rows = [];
  for (const line of readme().split("\n")) {
    const cells = line.split("|").slice(1, -1).map((c) => c.trim().replace(/`/g, ""));
    if (cells.length === 5 && /^\d+(\.\d+)?$/.test(cells[2]) && MINIMUMS.includes(Number(cells[3]))) {
      rows.push({ fg: cells[0], bg: cells[1], stated: Number(cells[2]), min: Number(cells[3]) });
    }
  }
  return rows;
}

test("AC4: README pairs recompute and pass", () => {
  const flat = flatten(tokens());
  const rows = readmePairs();
  assert.ok(rows.length >= REQUIRED_TEXT_PAIRS.length + REQUIRED_NON_TEXT_PAIRS.length, "README pair count");
  for (const r of rows) {
    const computed = ratio(resolve(flat, `color.${r.fg}`), resolve(flat, `color.${r.bg}`));
    assert.ok(Math.abs(computed - r.stated) <= 0.01, `${r.fg} on ${r.bg}: stated ${r.stated}, computed ${computed.toFixed(2)}`);
    assert.ok(computed >= r.min, `${r.fg} on ${r.bg}: ${computed.toFixed(2)} is below ${r.min}`);
  }
});

test("AC4: every text pair in use is listed", () => {
  const rows = readmePairs();
  for (const [fg, bg] of REQUIRED_TEXT_PAIRS) {
    assert.ok(rows.some((r) => r.fg === fg && r.bg === bg && r.min === 4.5), `missing text pair ${fg} on ${bg} (minimum 4.5)`);
  }
  for (const [fg, bg] of REQUIRED_NON_TEXT_PAIRS) {
    assert.ok(rows.some((r) => r.fg === fg && r.bg === bg && r.min === 3), `missing non-text pair ${fg} on ${bg} (minimum 3)`);
  }
});
