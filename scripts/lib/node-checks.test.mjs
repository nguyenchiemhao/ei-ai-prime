// Unit tests for scripts/lib/node-checks.mjs (pattern expansion and TAP summary parsing).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expandPattern, parseTapSummary } from "./node-checks.mjs";

function tree(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-glob-"));
  for (const file of files) {
    fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    fs.writeFileSync(path.join(root, file), "");
  }
  return root;
}

test("expand_pattern_matches_files_in_one_directory_only", () => {
  const root = tree(["a/x.test.mjs", "a/y.test.mjs", "a/y.txt", "a/deep/z.test.mjs"]);
  assert.deepEqual(expandPattern(root, "a/*.test.mjs"), ["a/x.test.mjs", "a/y.test.mjs"]);
});

test("expand_pattern_double_star_recurses", () => {
  const root = tree(["s/a.test.mjs", "s/b/c.test.mjs", "s/b/c/d.test.mjs", "s/b/e.mjs"]);
  assert.deepEqual(expandPattern(root, "s/**/*.test.mjs"), [
    "s/a.test.mjs",
    "s/b/c.test.mjs",
    "s/b/c/d.test.mjs",
  ]);
});

test("expand_pattern_star_in_a_middle_segment", () => {
  const root = tree([
    "packages/one/test/a.test.mjs",
    "packages/two/test/b.test.mjs",
    "packages/two/src/c.test.mjs",
  ]);
  assert.deepEqual(expandPattern(root, "packages/*/test/*.test.mjs"), [
    "packages/one/test/a.test.mjs",
    "packages/two/test/b.test.mjs",
  ]);
});

test("expand_pattern_skips_node_modules_and_returns_empty_for_missing_dir", () => {
  const root = tree(["s/node_modules/x/a.test.mjs", "s/ok.test.mjs"]);
  assert.deepEqual(expandPattern(root, "s/**/*.test.mjs"), ["s/ok.test.mjs"]);
  assert.deepEqual(expandPattern(root, "missing/*.test.mjs"), []);
});

test("parse_tap_summary_reads_tests_pass_fail_skipped", () => {
  const output =
    "TAP version 13\n# tests 25\n# suites 0\n# pass 24\n# fail 1\n# cancelled 0\n# skipped 0\n# todo 0\n";
  assert.deepEqual(parseTapSummary(output), {
    tests: 25,
    emptyFiles: 0,
    pass: 24,
    fail: 1,
    skipped: 0,
  });
});

test("parse_tap_summary_does_not_count_a_file_without_tests", () => {
  const output =
    "ok 1 - scripts\\\\x\\\\empty.test.mjs\nok 2 - a_real_test\n# tests 2\n# pass 2\n# fail 0\n# skipped 0\n";
  assert.deepEqual(parseTapSummary(output), {
    tests: 1,
    emptyFiles: 1,
    pass: 2,
    fail: 0,
    skipped: 0,
  });
});

test("parse_tap_summary_returns_null_when_there_is_no_summary", () => {
  assert.equal(parseTapSummary("nothing here"), null);
});
