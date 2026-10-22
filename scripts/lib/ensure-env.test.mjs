import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ensureEnv, envFileValue } from "./ensure-env.mjs";

const EXAMPLE = [
  "# comment with __GENERATED__ in it stays untouched on comment lines",
  "POSTGRES_PASSWORD=__GENERATED__",
  "APP_DB_PASSWORD=__GENERATED__",
  "EI_AI_MASTER_KEY=__GENERATED_KEY__",
  "LLM_ALIAS=",
  "",
].join("\n");

function project(files = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-env-"));
  fs.writeFileSync(path.join(root, ".env.example"), EXAMPLE);
  for (const [name, content] of Object.entries(files)) {
    fs.writeFileSync(path.join(root, name), content);
  }
  return root;
}

const parse = (text) =>
  Object.fromEntries(
    text
      .split("\n")
      .filter((line) => /^[A-Z_]+=/.test(line))
      .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]),
  );

test("ensure_env_creates_the_file_without_a_placeholder_left", () => {
  const root = project();

  assert.equal(ensureEnv(root), "created");

  const text = fs.readFileSync(path.join(root, ".env"), "utf8");
  const values = parse(text);
  assert.match(values.POSTGRES_PASSWORD, /^[0-9a-f]{32}$/);
  assert.match(values.APP_DB_PASSWORD, /^[0-9a-f]{32}$/);
  assert.equal(values.LLM_ALIAS, "");
  assert.ok(!/^[A-Z_]+=__GENERATED__$/m.test(text));
  assert.ok(
    text.startsWith("# comment with __GENERATED__"),
    "comment lines are copied as they are",
  );
});

test("ensure_env_generates_unique_values_per_variable_and_per_run", () => {
  const first = project();
  const second = project();

  ensureEnv(first);
  ensureEnv(second);

  const a = parse(fs.readFileSync(path.join(first, ".env"), "utf8"));
  const b = parse(fs.readFileSync(path.join(second, ".env"), "utf8"));
  assert.notEqual(a.POSTGRES_PASSWORD, a.APP_DB_PASSWORD);
  assert.notEqual(a.POSTGRES_PASSWORD, b.POSTGRES_PASSWORD);
});

test("ensure_env_adds_missing_generated_variables_to_an_existing_env_and_keeps_its_values", () => {
  const original = "MODEL_CACHE_VOLUME=ei-ai-stack-spike_model-cache";
  const root = project({ ".env": original });

  assert.equal(ensureEnv(root), "updated");

  const text = fs.readFileSync(path.join(root, ".env"), "utf8");
  const values = parse(text);
  assert.equal(values.MODEL_CACHE_VOLUME, "ei-ai-stack-spike_model-cache");
  assert.match(values.POSTGRES_PASSWORD, /^[0-9a-f]{32}$/);
  assert.match(values.APP_DB_PASSWORD, /^[0-9a-f]{32}$/);
  assert.ok(text.startsWith(original + "\n"), "the existing line stays first and unchanged");
  assert.equal(ensureEnv(root), "kept", "a second run changes nothing");
});

test("ensure_env_adds_only_the_variable_that_is_missing", () => {
  const root = project({ ".env": "POSTGRES_PASSWORD=mine\n" });

  assert.equal(ensureEnv(root), "updated");

  const values = parse(fs.readFileSync(path.join(root, ".env"), "utf8"));
  assert.equal(values.POSTGRES_PASSWORD, "mine");
  assert.match(values.APP_DB_PASSWORD, /^[0-9a-f]{32}$/);
});

test("ensure_env_keeps_an_existing_env_file_untouched", () => {
  const original = "POSTGRES_PASSWORD=mine\nAPP_DB_PASSWORD=mine2\nEI_AI_MASTER_KEY=mine3\n";
  const root = project({ ".env": original });

  assert.equal(ensureEnv(root), "kept");

  assert.equal(fs.readFileSync(path.join(root, ".env"), "utf8"), original);
});

test("ensure_env_fails_when_the_example_is_missing", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-env-"));

  assert.throws(() => ensureEnv(root), /\.env\.example/);
});

test("env_file_value_reads_one_variable_of_dot_env", () => {
  const root = project({ ".env": "# ADMIN_PORT=1\nADMIN_PORT=3100\r\nEMPTY=\nOTHER=x=y\n" });
  assert.equal(envFileValue(root, "ADMIN_PORT"), "3100");
  assert.equal(envFileValue(root, "OTHER"), "x=y");
  assert.equal(envFileValue(root, "EMPTY"), undefined);
  assert.equal(envFileValue(root, "MISSING"), undefined);
  assert.equal(envFileValue(project(), "ADMIN_PORT"), undefined, "no .env at all");
});

test("env_file_value_parses_like_compose", () => {
  const root = project({
    ".env": [
      'DOUBLE="3100"',
      "SINGLE='3200'",
      "COMMENTED=3300 # moved off 3000",
      'HASH_IN_QUOTES="a # b"',
      "HASH_NO_SPACE=a#b",
      "DUP=first",
      "DUP=last",
      "SPACED = 3400",
      "",
    ].join("\n"),
  });
  assert.equal(envFileValue(root, "DOUBLE"), "3100");
  assert.equal(envFileValue(root, "SINGLE"), "3200");
  assert.equal(envFileValue(root, "COMMENTED"), "3300");
  assert.equal(envFileValue(root, "HASH_IN_QUOTES"), "a # b");
  assert.equal(envFileValue(root, "HASH_NO_SPACE"), "a#b");
  assert.equal(envFileValue(root, "DUP"), "last");
  assert.equal(envFileValue(root, "SPACED"), "3400");
});

test("generates_a_64_hex_master_key", () => {
  const created = project();
  assert.equal(ensureEnv(created), "created");
  const values = parse(fs.readFileSync(path.join(created, ".env"), "utf8"));
  assert.match(values.EI_AI_MASTER_KEY, /^[0-9a-f]{64}$/);
  assert.match(values.POSTGRES_PASSWORD, /^[0-9a-f]{32}$/, "__GENERATED__ stays 32 hex");

  const appended = project({ ".env": "POSTGRES_PASSWORD=mine\nAPP_DB_PASSWORD=mine2\n" });
  assert.equal(ensureEnv(appended), "updated");
  const added = parse(fs.readFileSync(path.join(appended, ".env"), "utf8"));
  assert.match(added.EI_AI_MASTER_KEY, /^[0-9a-f]{64}$/);
  assert.equal(added.POSTGRES_PASSWORD, "mine");

  const kept = "EI_AI_MASTER_KEY=existing\nPOSTGRES_PASSWORD=a\nAPP_DB_PASSWORD=b\n";
  const existing = project({ ".env": kept });
  assert.equal(ensureEnv(existing), "kept");
  assert.equal(fs.readFileSync(path.join(existing, ".env"), "utf8"), kept);
});
