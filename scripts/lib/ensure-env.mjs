// Prepares .env from .env.example: every `NAME=__GENERATED__` line gets 32 random hex characters.
//  - no .env: it is created from the example;
//  - an .env without some of those variables (for example one that only holds MODEL_CACHE_VOLUME):
//    the missing generated variables are appended; existing lines and values are never changed
//    (they may hold the passwords of an existing database).
// envFileValue reads one variable back, for Node scripts that must agree with Compose (which reads .env).
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const PLACEHOLDER = /^([A-Z][A-Z0-9_]*)=__GENERATED__$/;
const ASSIGNMENT = /^([A-Z][A-Z0-9_]*)=/;

// A .env line as Compose reads it: optional spaces around `=`, a quoted value, or an unquoted value
// whose ` # comment` is dropped.
const DOTENV_LINE =
  /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(.*?))(?:\s+#.*)?\s*$/;

/** Generates the value of one __GENERATED__ variable (32 random hex characters). */
const generate = () => randomBytes(16).toString("hex");

/**
 * Value of `name` in `<root>/.env`, parsed like Compose (quotes, inline comments, the last duplicate
 * wins), or undefined when the file, the line or the value is missing.
 */
export function envFileValue(root, name) {
  const target = path.join(root, ".env");
  if (!fs.existsSync(target)) return undefined;
  let value;
  for (const line of fs.readFileSync(target, "utf8").replace(/\r\n/g, "\n").split("\n")) {
    const match = line.match(DOTENV_LINE);
    if (match?.[1] === name) value = match[2] ?? match[3] ?? match[4];
  }
  return value || undefined;
}

/** "created" when .env was written, "updated" when missing variables were appended, else "kept". */
export function ensureEnv(root) {
  const target = path.join(root, ".env");
  const example = path.join(root, ".env.example");
  if (!fs.existsSync(example)) throw new Error(`${example} is missing; cannot prepare .env`);
  const exampleLines = fs.readFileSync(example, "utf8").replace(/\r\n/g, "\n").split("\n");

  if (!fs.existsSync(target)) {
    const lines = exampleLines.map((line) => {
      const match = line.match(PLACEHOLDER);
      return match ? `${match[1]}=${generate()}` : line;
    });
    fs.writeFileSync(target, lines.join("\n"), { mode: 0o600 });
    return "created";
  }

  const existing = fs.readFileSync(target, "utf8");
  const present = new Set(
    existing
      .replace(/\r\n/g, "\n")
      .split("\n")
      .map((line) => line.match(ASSIGNMENT)?.[1])
      .filter(Boolean),
  );
  const missing = exampleLines
    .map((line) => line.match(PLACEHOLDER)?.[1])
    .filter((name) => name && !present.has(name));
  if (missing.length === 0) return "kept";
  const separator = existing === "" || existing.endsWith("\n") ? "" : "\n";
  const added = missing.map((name) => `${name}=${generate()}\n`).join("");
  fs.appendFileSync(target, separator + added);
  return "updated";
}
