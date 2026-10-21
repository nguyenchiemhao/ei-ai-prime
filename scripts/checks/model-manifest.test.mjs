// EA-24 AC2: the platform model manifest and the compose defaults of the model server pin the same
// file. The manifest's chat entry must name the served alias, the sha256 and the Hugging Face
// revision/file the model service starts with; otherwise every local call would fail with
// PINNED_VERSION_UNAVAILABLE (or, worse, pin a file nobody verified).
// Needs Docker with Compose (like compose.test.mjs).
// Run:  node --test scripts/checks/model-manifest.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ROOT, compose } from "../lib/docker.mjs";

const MANIFEST = path.join(
  ROOT,
  "backend",
  "src",
  "ei_ai",
  "model_gateway",
  "data",
  "local-models.json",
);
const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
const chat = manifest.models.filter((entry) => entry.kind === "chat");

function modelDefaults() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-manifest-"));
  const file = path.join(dir, "test.env");
  const dummy = [
    "POSTGRES_PASSWORD",
    "APP_DB_PASSWORD",
    "MIGRATION_DB_PASSWORD",
    "SIGNIN_DB_PASSWORD",
  ];
  fs.writeFileSync(file, dummy.map((name) => `${name}=dummy`).join("\n") + "\n");
  const env = { ...process.env };
  for (const name of ["LLM_ALIAS", "LLM_MODEL_FILE", "LLM_MODEL_URL", "LLM_MODEL_SHA256"])
    delete env[name];
  const result = compose(["--env-file", file, "--profile", "model", "config", "--format", "json"], {
    capture: true,
    env,
  });
  assert.equal(result.code, 0, result.stderr);
  return JSON.parse(result.stdout).services.model.environment;
}

test("manifest_has_one_local_chat_entry", () => {
  assert.equal(chat.length, 1);
  assert.equal(chat[0].deployment, "local");
});

test("manifest_chat_entry_pins_the_file_the_model_service_starts", () => {
  const defaults = modelDefaults();
  const [entry] = chat;
  assert.equal(entry.model_id, defaults.LLM_ALIAS);
  assert.equal(entry.digest, `sha256:${defaults.LLM_MODEL_SHA256}`);
  const match = defaults.LLM_MODEL_URL.match(
    /^https:\/\/huggingface\.co\/([^/]+\/[^/]+)\/resolve\/([0-9a-f]{40})\/(.+)$/,
  );
  assert.ok(match, `unexpected LLM_MODEL_URL ${defaults.LLM_MODEL_URL}`);
  const [, repo, revision, file] = match;
  assert.equal(file, defaults.LLM_MODEL_FILE);
  assert.equal(entry.source_revision, `${repo}@${revision}/${file}`);
});

test("every_manifest_entry_is_pinned_by_sha256_and_a_commit", () => {
  for (const entry of manifest.models) {
    assert.match(entry.digest, /^sha256:[0-9a-f]{64}$/, entry.model_id);
    assert.match(
      entry.source_revision,
      /^[^@\s]+\/[^@\s]+@[0-9a-f]{40}\/\S+\.gguf$/,
      entry.model_id,
    );
  }
});
