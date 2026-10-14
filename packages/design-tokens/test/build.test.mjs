// EA-13 (SET-03) AC7: the design-token JSON compiles to CSS custom properties.
// Run:  node --test packages/design-tokens/test/build.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compileTokens } from "../scripts/build.mjs";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const tokens = JSON.parse(fs.readFileSync(path.join(PACKAGE, "design-tokens.json"), "utf8"));

function leafCount(node) {
  if (node !== null && typeof node === "object") {
    if ("$value" in node) return 1;
    return Object.entries(node).reduce(
      (sum, [key, child]) => sum + (key.startsWith("$") ? 0 : leafCount(child)),
      0,
    );
  }
  return 0;
}

const css = compileTokens(tokens);
const declarations = [...css.matchAll(/^ {2}(--ei-[a-z0-9-]+): (.+);$/gm)].map((m) => [m[1], m[2]]);
const variables = new Map(declarations);

test("every_token_becomes_one_css_variable", () => {
  assert.equal(leafCount(tokens), 90);
  assert.equal(declarations.length, 90);
  assert.equal(variables.size, 90, "duplicate variable names");
});

test("references_compile_to_var", () => {
  assert.equal(
    variables.get("--ei-color-access-public-text"),
    "var(--ei-color-status-success-text)",
  );
  assert.equal(
    variables.get("--ei-color-access-restricted-bg"),
    "var(--ei-color-status-warning-bg)",
  );
  assert.ok(!css.includes("{color."), "an unresolved {reference} is left in the output");
});

test("required_values_survive_compilation", () => {
  assert.equal(variables.get("--ei-color-text-primary"), "#16181D");
  assert.equal(variables.get("--ei-color-surface-page"), "#F7F7F8");
  assert.equal(variables.get("--ei-color-brand-default"), "#0E7C6B");
  assert.equal(variables.get("--ei-size-target-min"), "44px");
  assert.equal(variables.get("--ei-font-weight-semibold"), "600");
  assert.equal(variables.get("--ei-font-line-height-tight"), "1.45");
  assert.match(variables.get("--ei-font-family-sans"), /IBM Plex Sans/);
  assert.match(variables.get("--ei-font-family-mono"), /IBM Plex Mono/);
});

test("output_is_deterministic", () => {
  assert.equal(compileTokens(tokens), css);
  assert.ok(!css.includes("\r"), "output must use LF");
  assert.ok(css.endsWith("}\n"));
  const names = declarations.map(([name]) => name);
  assert.deepEqual(names, [...names].sort(), "variables are not sorted");
  assert.match(css, /^:root \{$/m);
});

test("a_dangling_reference_fails_the_build", () => {
  const broken = { color: { $type: "color", a: { $value: "{color.missing}" } } };
  assert.throws(() => compileTokens(broken), /color\.missing/);
});

test("build_script_writes_dist_tokens_css", async () => {
  const out = path.join(PACKAGE, "dist", "tokens.css");
  const { buildTokens } = await import("../scripts/build.mjs");
  buildTokens();
  assert.equal(fs.readFileSync(out, "utf8"), css);
});
