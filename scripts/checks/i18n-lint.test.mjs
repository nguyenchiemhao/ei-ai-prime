// Coding rule 7: user-facing text goes through the message catalog. The ESLint rule must catch not only
// literal JSX text but also user-facing attributes and string literals in JSX expressions.
// The fixtures are linted from stdin with the path of a widget/admin source file.
// Run:  node --test scripts/checks/i18n-lint.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";

const ESLINT = path.join(ROOT, "node_modules/eslint/bin/eslint.js");

function lint(jsx, file = "apps/widget/src/Fixture.tsx") {
  const source = `export const Fixture = (t: (key: string) => string) => (\n  ${jsx}\n);\n`;
  const result = spawnSync(process.execPath, [ESLINT, "--stdin", "--stdin-filename", file], {
    cwd: ROOT,
    input: source,
    encoding: "utf8",
  });
  return { code: result.status, output: `${result.stdout}${result.stderr}` };
}

test("i18n_lint_accepts_text_from_the_catalog_and_non_user_facing_attributes", () => {
  const { code, output } = lint(
    '<div className="box" class="box" role="log" data-state="ok" aria-live="polite" aria-label={t("a")}>{t("b")}</div>',
  );
  assert.equal(code, 0, output);
});

for (const [name, jsx] of [
  ["literal_jsx_text", "<p>Hello</p>"],
  ["aria_label_literal", '<div aria-label="Conversation" />'],
  ["title_literal", '<button title="Close" />'],
  ["placeholder_literal", '<input placeholder="Search" />'],
  ["alt_literal", '<img alt="Logo" src={t("x")} />'],
  ["string_literal_expression", '<p>{"Administration"}</p>'],
]) {
  test(`i18n_lint_rejects_${name}`, () => {
    const { code, output } = lint(jsx);
    assert.equal(code, 1, `expected an ESLint error for ${jsx}\n${output}`);
    assert.match(output, /i18next\/no-literal-string/);
  });
}

test("i18n_lint_also_covers_the_admin_app", () => {
  assert.equal(lint('<div aria-label="Language" />', "apps/admin/src/Fixture.tsx").code, 1);
});
