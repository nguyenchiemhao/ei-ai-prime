// `npm run reset` must delete the database volume of the project Compose really uses (shell
// variable, then .env, then the name in compose.yaml), never another project's. These tests use a
// throwaway project; the real stack's volumes are never touched. Needs Docker.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { docker } from "./docker.mjs";
import { dbVolumeName, resetDatabase } from "./reset.mjs";

const SUFFIX = `${process.pid}-${Date.now()}`;
const FILE_PROJECT = `ei-ai-throwaway-file-${SUFFIX}`;
const ENV_PROJECT = `ei-ai-throwaway-env-${SUFFIX}`;

function project(envFile) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-reset-"));
  fs.writeFileSync(
    path.join(dir, "compose.yaml"),
    [
      `name: ${FILE_PROJECT}`,
      "services:",
      "  db:",
      "    image: alpine:latest",
      '    profiles: ["core"]',
      "    volumes:",
      "      - db-data:/data",
      "volumes:",
      "  db-data:",
      "",
    ].join("\n"),
  );
  if (envFile !== undefined) fs.writeFileSync(path.join(dir, ".env"), envFile);
  return dir;
}

const volumeExists = (name) => docker(["volume", "inspect", name], { capture: true }).code === 0;
const cleanEnv = () => {
  const env = { ...process.env };
  delete env.COMPOSE_PROJECT_NAME;
  return env;
};

test("db_volume_name_comes_from_the_name_in_compose_yaml", () => {
  assert.equal(dbVolumeName(project(), cleanEnv()), `${FILE_PROJECT}_db-data`);
});

test("db_volume_name_follows_a_project_name_set_only_in_dot_env", () => {
  const dir = project(`COMPOSE_PROJECT_NAME=${ENV_PROJECT}\n`);

  assert.equal(dbVolumeName(dir, cleanEnv()), `${ENV_PROJECT}_db-data`);
});

test("db_volume_name_prefers_the_shell_variable_over_dot_env", () => {
  const dir = project(`COMPOSE_PROJECT_NAME=${ENV_PROJECT}\n`);

  const name = dbVolumeName(dir, { ...process.env, COMPOSE_PROJECT_NAME: "from-shell" });

  assert.equal(name, "from-shell_db-data");
});

test("reset_deletes_only_the_volume_of_the_project_named_in_dot_env", () => {
  const dir = project(`COMPOSE_PROJECT_NAME=${ENV_PROJECT}\n`);
  const target = `${ENV_PROJECT}_db-data`;
  const other = `${FILE_PROJECT}_db-data`;
  for (const name of [target, other]) docker(["volume", "create", name], { capture: true });
  try {
    const result = resetDatabase(dir, cleanEnv(), { capture: true });

    assert.equal(result.code, 0, result.message);
    assert.equal(volumeExists(target), false, "the project's own db volume is deleted");
    assert.equal(volumeExists(other), true, "another project's db volume is untouched");
  } finally {
    for (const name of [target, other])
      docker(["volume", "rm", "--force", name], { capture: true });
  }
});

test("reset_reports_nothing_to_do_when_the_volume_does_not_exist", () => {
  const dir = project(`COMPOSE_PROJECT_NAME=${ENV_PROJECT}\n`);

  const result = resetDatabase(dir, cleanEnv(), { capture: true });

  assert.equal(result.code, 0);
  assert.match(result.message, /Nothing to reset/);
});
