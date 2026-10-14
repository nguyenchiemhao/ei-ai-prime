// The migrate step is pinned: build the image, then run the one-shot service against a healthy db.
import test from "node:test";
import assert from "node:assert/strict";
import { MIGRATE_FAILED_HINT, migrateSteps } from "./migrate.mjs";

test("migrate_steps_build_then_run_the_one_shot_service", () => {
  assert.deepEqual(migrateSteps(), [
    ["--profile", "tools", "build", "migrate"],
    ["--profile", "core", "--profile", "tools", "run", "--rm", "-T", "migrate"],
  ]);
});

test("migrate_failure_hint_names_the_reset_for_databases_created_before_the_migrator_role", () => {
  assert.match(MIGRATE_FAILED_HINT, /ei_ai_migrator/);
  assert.match(MIGRATE_FAILED_HINT, /npm run reset/);
});
