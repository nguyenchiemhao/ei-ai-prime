import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { seedCommand, seedPassword } from "./seed-password.mjs";

const NAME = "EI_AI_SEED_PASSWORD";

function root(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-seed-password-"));
  for (const [file, text] of Object.entries(files)) fs.writeFileSync(path.join(dir, file), text);
  return dir;
}

test("reads_the_value_from_env_file", () => {
  const dir = root({
    ".env": `${NAME}=From-Env-File-1\n`,
    ".env.example": `${NAME}=From-Example-1\n`,
  });
  assert.equal(seedPassword(dir), "From-Env-File-1");
});

test("falls_back_to_env_example_when_env_lacks_it", () => {
  const dir = root({ ".env": "ADMIN_PORT=3100\n", ".env.example": `${NAME}=From-Example-1\n` });
  assert.equal(seedPassword(dir), "From-Example-1");
});

test("undefined_when_neither_has_it", () => {
  assert.equal(
    seedPassword(root({ ".env": "ADMIN_PORT=3100\n", ".env.example": "X=1\n" })),
    undefined,
  );
  assert.equal(seedPassword(root({})), undefined);
});

test("seed_password_is_passed_by_environment_not_argv", () => {
  const command = seedCommand();
  assert.ok(command.includes(NAME));
  assert.ok(command.every((part) => !part.includes("=")));
  assert.deepEqual(command.slice(-3), ["ei-ai", "seed", "demo"]);
});
