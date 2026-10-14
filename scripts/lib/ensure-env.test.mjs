import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ensureEnv } from "./ensure-env.mjs";

const EXAMPLE = [
  "# comment with __GENERATED__ in it stays untouched on comment lines",
  "POSTGRES_PASSWORD=__GENERATED__",
  "APP_DB_PASSWORD=__GENERATED__",
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
  const original = "POSTGRES_PASSWORD=mine\nAPP_DB_PASSWORD=mine2\n";
  const root = project({ ".env": original });

  assert.equal(ensureEnv(root), "kept");

  assert.equal(fs.readFileSync(path.join(root, ".env"), "utf8"), original);
});

test("ensure_env_fails_when_the_example_is_missing", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-env-"));

  assert.throws(() => ensureEnv(root), /\.env\.example/);
});
