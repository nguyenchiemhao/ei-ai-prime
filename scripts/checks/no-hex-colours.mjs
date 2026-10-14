// Fails when an app component or stylesheet hard-codes a colour (hex, rgb(), rgba(), hsl(), hsla()).
// Colours come from the compiled design tokens (`var(--ei-...)`) only (coding rules section 2).
// Scans apps/*/src/**/*.{ts,tsx,css} and apps/*/index.html; test files (*.test.*) are skipped.
// APPS_DIR overrides the apps folder (used by the fixtures). Built-ins only.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SCANNED = /\.(ts|tsx|css|html)$/;
const LITERAL =
  /(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])|\b(?:rgba?|hsla?)\(/g;

/** Colour literals in a text: [{ line (1-based), match }]. */
export function findColourLiterals(text) {
  const hits = [];
  text.split("\n").forEach((content, index) => {
    for (const match of content.matchAll(LITERAL)) hits.push({ line: index + 1, match: match[0] });
  });
  return hits;
}

function* files(directory) {
  if (!fs.existsSync(directory)) return;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) yield* files(full);
    else if (SCANNED.test(entry.name) && !/\.test\./.test(entry.name)) yield full;
  }
}

function* appFiles(appsDir) {
  for (const app of fs
    .readdirSync(appsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())) {
    yield* files(path.join(appsDir, app.name, "src"));
    const index = path.join(appsDir, app.name, "index.html");
    if (fs.existsSync(index)) yield index;
  }
}

function main() {
  const appsDir = path.resolve(process.env.APPS_DIR || path.join(ROOT, "apps"));
  let violations = 0;
  for (const file of appFiles(appsDir)) {
    for (const { line, match } of findColourLiterals(fs.readFileSync(file, "utf8"))) {
      console.error(
        `${path.relative(appsDir, file).split(path.sep).join("/")}:${line} hard-coded colour ${match} (use a var(--ei-...) token)`,
      );
      violations += 1;
    }
  }
  if (violations > 0) {
    console.error(`${violations} hard-coded colour(s) found`);
    process.exit(1);
  }
  console.log("no hard-coded colours in app sources");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
