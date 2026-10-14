// Pure helpers of the Node check runner: expand `dir/*.test.mjs` style patterns and read the TAP summary.
// Built-ins only (the root scripts must run without `npm install`).
import fs from "node:fs";
import path from "node:path";

const SKIPPED_DIRS = new Set(["node_modules", ".git", "dist"]);

function segmentRegex(segment) {
  const escaped = segment.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^/]*");
  return new RegExp(`^${escaped}$`);
}

function walk(root, relDir, segments, out) {
  const [segment, ...rest] = segments;
  const absolute = path.join(root, relDir);
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isDirectory()) return;
  const entries = fs
    .readdirSync(absolute, { withFileTypes: true })
    .sort((a, b) => a.name.localeCompare(b.name));
  if (segment === "**") {
    walk(root, relDir, rest, out);
    for (const entry of entries) {
      if (entry.isDirectory() && !SKIPPED_DIRS.has(entry.name))
        walk(root, path.posix.join(relDir, entry.name), segments, out);
    }
    return;
  }
  const matcher = segmentRegex(segment);
  for (const entry of entries) {
    if (!matcher.test(entry.name) || SKIPPED_DIRS.has(entry.name)) continue;
    const rel = path.posix.join(relDir, entry.name);
    if (rest.length === 0) {
      if (entry.isFile()) out.add(rel);
    } else if (entry.isDirectory()) {
      walk(root, rel, rest, out);
    }
  }
}

/** Files (posix paths relative to root, sorted) matching a pattern such as `a/*.test.mjs` or `a/**\/*.test.mjs`. */
export function expandPattern(root, pattern) {
  const out = new Set();
  walk(root, "", pattern.split("/"), out);
  return [...out].sort();
}

/**
 * Reads the totals of `node --test --test-reporter=tap`; null when the output has no summary.
 * `tests` does not count the pseudo-test Node reports for a file that registers no test at all
 * (a top-level "ok N - <file>.mjs" line); those are returned as `emptyFiles`.
 */
export function parseTapSummary(output) {
  const read = (name) => {
    const match = output.match(new RegExp(`^# ${name} (\\d+)$`, "m"));
    return match ? Number(match[1]) : null;
  };
  const tests = read("tests");
  if (tests === null) return null;
  const emptyFiles = (output.match(/^ok \d+ - \S+\.m?[jt]s$/gm) ?? []).length;
  return {
    tests: tests - emptyFiles,
    emptyFiles,
    pass: read("pass") ?? 0,
    fail: read("fail") ?? 0,
    skipped: read("skipped") ?? 0,
  };
}
