// EA-24 AC2 (attacks 7, 8): infra/model/start-model.sh starts the model server only for a file whose
// sha256 matches LLM_MODEL_SHA256, and serves it under an alias derived from the file's ACTUAL hash.
// Runs the script with `sh`, a temporary model directory and stub `curl` / `llama-server` programs.
// Skipped (with the reason) when `sh` or `sha256sum` is missing (Windows without Git Bash); CI is Linux.
// Run:  node --test scripts/checks/model-start.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";

const SCRIPT = path.join(ROOT, "infra", "model", "start-model.sh");
const has = (program) => spawnSync("sh", ["-c", `command -v ${program}`]).status === 0;
const SKIP =
  spawnSync("sh", ["-c", "true"]).status !== 0 || !has("sha256sum")
    ? "needs sh and sha256sum (Linux, macOS with coreutils or Git Bash)"
    : false;

const posix = (p) => p.split(path.sep).join("/");
const sha256 = (text) => crypto.createHash("sha256").update(text).digest("hex");
const FILE = "model.gguf";
const URL =
  "https://huggingface.co/acme/model-GGUF/resolve/0123456789abcdef0123456789abcdef01234567/model.gguf";

function stub(dir, name, body) {
  const file = path.join(dir, name);
  fs.writeFileSync(file, `#!/bin/sh\n${body}\n`);
  fs.chmodSync(file, 0o755);
  return file;
}

/** A sandbox: model dir, stub bin dir (curl), stub server; returns paths and a runner. */
function sandbox({ fileContent, download = "downloaded-model", curlExit = 0 } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-model-start-"));
  const models = path.join(dir, "models");
  const bin = path.join(dir, "bin");
  fs.mkdirSync(models);
  fs.mkdirSync(bin);
  const serverArgs = path.join(dir, "server-args.txt");
  const curlArgs = path.join(dir, "curl-args.txt");
  stub(
    bin,
    "curl",
    [
      `printf '%s\\n' "$@" > '${posix(curlArgs)}'`,
      `if [ ${curlExit} -ne 0 ]; then exit ${curlExit}; fi`,
      'while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; fi; shift; done',
      `printf '%s' '${download}' > "$out"`,
    ].join("\n"),
  );
  const server = stub(dir, "llama-server", `printf '%s\\n' "$@" > '${posix(serverArgs)}'`);
  if (fileContent !== undefined) fs.writeFileSync(path.join(models, FILE), fileContent);
  const run = (env) =>
    spawnSync("sh", [posix(SCRIPT)], {
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${posix(bin)}:${process.env.PATH}`,
        MODEL_DIR: posix(models),
        LLAMA_SERVER_BIN: posix(server),
        LLM_MODEL_FILE: FILE,
        LLM_MODEL_URL: URL,
        LLM_ALIAS: "qwen3-4b-instruct-2507",
        ...env,
      },
    });
  const read = (file) =>
    fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim().split("\n") : null;
  return {
    models,
    run,
    serverArgs: () => read(serverArgs),
    curlArgs: () => read(curlArgs),
  };
}

test("mismatch_exits_1_with_the_message_and_never_runs_the_server", { skip: SKIP }, () => {
  const box = sandbox({ fileContent: "model-a" });
  const expected = sha256("something else");

  const result = box.run({ LLM_MODEL_SHA256: expected });

  assert.equal(result.status, 1);
  assert.match(
    result.stderr,
    new RegExp(`model file sha256 mismatch: expected ${expected}, got ${sha256("model-a")}`),
  );
  assert.equal(box.serverArgs(), null, "the server must not start");
  assert.ok(fs.existsSync(path.join(box.models, FILE)), "the file is not deleted");
});

test("match_runs_the_server_with_the_alias_of_the_actual_hash", { skip: SKIP }, () => {
  const box = sandbox({ fileContent: "model-a" });
  const actual = sha256("model-a");

  const result = box.run({ LLM_MODEL_SHA256: actual });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(box.serverArgs(), [
    "-m",
    `${posix(box.models)}/${FILE}`,
    "--alias",
    `qwen3-4b-instruct-2507@sha256-${actual.slice(0, 12)}`,
    "--host",
    "0.0.0.0",
    "--port",
    "8080",
    "-c",
    "8192",
    "-t",
    "6",
    "--jinja",
  ]);
  assert.equal(box.curlArgs(), null, "a present file is not downloaded again");
});

test("a_swapped_file_with_a_matching_env_sha_gets_a_new_alias", { skip: SKIP }, () => {
  // Attack 7: the file is replaced and LLM_MODEL_SHA256 edited to match; the alias must change.
  const box = sandbox({ fileContent: "model-b" });

  const result = box.run({ LLM_MODEL_SHA256: sha256("model-b") });

  assert.equal(result.status, 0, result.stderr);
  const alias = box.serverArgs()[box.serverArgs().indexOf("--alias") + 1];
  assert.equal(alias, `qwen3-4b-instruct-2507@sha256-${sha256("model-b").slice(0, 12)}`);
  assert.notEqual(alias, `qwen3-4b-instruct-2507@sha256-${sha256("model-a").slice(0, 12)}`);
});

test("a_missing_file_is_downloaded_through_a_partial_file", { skip: SKIP }, () => {
  const box = sandbox({ download: "downloaded-model" });

  const result = box.run({ LLM_MODEL_SHA256: sha256("downloaded-model") });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(box.curlArgs(), [
    "-fL",
    "--retry",
    "3",
    "-o",
    `${posix(box.models)}/${FILE}.partial`,
    URL,
  ]);
  assert.equal(fs.readFileSync(path.join(box.models, FILE), "utf8"), "downloaded-model");
  assert.ok(!fs.existsSync(path.join(box.models, `${FILE}.partial`)));
  assert.ok(box.serverArgs() !== null);
});

test("a_downloaded_file_with_the_wrong_hash_is_refused", { skip: SKIP }, () => {
  const box = sandbox({ download: "tampered" });

  const result = box.run({ LLM_MODEL_SHA256: sha256("downloaded-model") });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /model file sha256 mismatch/);
  assert.equal(box.serverArgs(), null);
});

test("a_failed_download_starts_nothing", { skip: SKIP }, () => {
  const box = sandbox({ curlExit: 22 });

  const result = box.run({ LLM_MODEL_SHA256: sha256("downloaded-model") });

  assert.notEqual(result.status, 0);
  assert.ok(!fs.existsSync(path.join(box.models, FILE)));
  assert.equal(box.serverArgs(), null);
});

test("a_missing_setting_is_refused", { skip: SKIP }, () => {
  const box = sandbox({ fileContent: "model-a" });

  const result = box.run({ LLM_MODEL_SHA256: "" });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /LLM_MODEL_SHA256/);
  assert.equal(box.serverArgs(), null);
});

test("a_hash_that_differs_only_in_its_last_hex_digit_is_refused", { skip: SKIP }, () => {
  // R1-4: the whole sha256 is compared, not the 12-character prefix the alias shows.
  const box = sandbox({ fileContent: "model-a" });
  const actual = sha256("model-a");
  const last = actual.at(-1) === "0" ? "1" : "0";

  const result = box.run({ LLM_MODEL_SHA256: `${actual.slice(0, -1)}${last}` });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /model file sha256 mismatch/);
  assert.equal(box.serverArgs(), null);
});
