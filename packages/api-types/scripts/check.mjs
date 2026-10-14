// Fails when src/schema.d.ts differs from what openapi-typescript generates from openapi.json.
// OPENAPI_FILE / SCHEMA_FILE override the inputs (used by the tests). Exit 0 = in sync.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const openapi = process.env.OPENAPI_FILE || path.join(PACKAGE, "openapi.json");
const committed = process.env.SCHEMA_FILE || path.join(PACKAGE, "src/schema.d.ts");

const require = createRequire(import.meta.url);
const packageJson = require.resolve("openapi-typescript/package.json");
const { bin } = require(packageJson);
const cli = path.join(
  path.dirname(packageJson),
  typeof bin === "string" ? bin : bin["openapi-typescript"],
);

const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-schema-")), "schema.d.ts");
const result = spawnSync(process.execPath, [cli, openapi, "-o", out], { encoding: "utf8" });
if (result.status !== 0) {
  console.error(`openapi-typescript failed:\n${result.stdout}${result.stderr}`);
  process.exit(1);
}
if (fs.readFileSync(out, "utf8") !== fs.readFileSync(committed, "utf8").replace(/\r\n/g, "\n")) {
  console.error(
    "packages/api-types/src/schema.d.ts is out of date. Regenerate it with: npm run generate -w @ei-ai/api-types",
  );
  process.exit(1);
}
console.log("api-types: schema.d.ts matches openapi.json");
