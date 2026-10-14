// EA-13 (SET-03) AC7: a check fails on hard-coded colours in app components and styles.
// Fixtures: scripts/test-fixtures/no-hex/{clean,tsx-hex,css-hex}. Run:
//   node --test scripts/checks/no-hex-colours.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findColourLiterals } from "./no-hex-colours.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const CHECK = path.join(ROOT, "scripts/checks/no-hex-colours.mjs");
const fixture = (name) => path.join(ROOT, "scripts/test-fixtures/no-hex", name);

function run(appsDir) {
  const env = appsDir ? { ...process.env, APPS_DIR: appsDir } : process.env;
  const result = spawnSync(process.execPath, [CHECK], { cwd: ROOT, encoding: "utf8", env });
  return { code: result.status, output: `${result.stdout}${result.stderr}` };
}

test("clean_apps_pass", () => {
  const { code, output } = run(fixture("clean"));
  assert.equal(code, 0, output);
});

test("the_real_apps_pass", () => {
  const { code, output } = run();
  assert.equal(code, 0, output);
});

test("fixture_with_hex_in_tsx_fails", () => {
  const { code, output } = run(fixture("tsx-hex"));
  assert.equal(code, 1);
  assert.match(output, /admin\/src\/App\.tsx:2/);
  assert.match(output, /#16181D/);
});

test("fixture_with_hex_in_css_fails", () => {
  const { code, output } = run(fixture("css-hex"));
  assert.equal(code, 1);
  assert.match(output, /widget\/src\/styles\.css:3/);
  assert.match(output, /widget\/src\/styles\.css:5/, "rgba() literal is reported too");
});

test("find_colour_literals_detects_every_notation_and_ignores_look_alikes", () => {
  const hits = (text) => findColourLiterals(text).map((hit) => hit.match);
  assert.deepEqual(hits("a { color: #fff; b: #ABCD; c: #12345678; d: #123456 }"), [
    "#fff",
    "#ABCD",
    "#12345678",
    "#123456",
  ]);
  assert.deepEqual(hits("x: rgb(1,2,3); y: rgba(1,2,3,.5); z: hsl(1 2% 3%); w: hsla(1,2%,3%,.5)"), [
    "rgb(",
    "rgba(",
    "hsl(",
    "hsla(",
  ]);
  assert.deepEqual(hits('&#169; href="#top" id=#12 var(--ei-color-text-primary) rgbValue'), []);
});
