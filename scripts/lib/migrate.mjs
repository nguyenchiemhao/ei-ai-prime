// The database migration step (FND-01): `ei-ai db upgrade` in the one-shot `migrate` service
// (Alembic to head, then the schema guard). Used by `npm run up`, `npm run migrate` and the
// integration test task. The caller makes sure the db service is healthy first.
import { compose } from "./docker.mjs";

export const MIGRATE_FAILED_HINT =
  "Migrations failed. If this database was created before FND-01 (no ei_ai_migrator role), " +
  "run `npm run reset` once (it deletes only the local database).";

/** Compose arguments of the steps, in order. Pure, so a test can pin them. */
export function migrateSteps() {
  return [
    ["--profile", "tools", "build", "migrate"],
    ["--profile", "core", "--profile", "tools", "run", "--rm", "-T", "migrate"],
  ];
}

/** Runs the steps; returns 0 or the failing exit code (the hint is printed on failure). */
export function runMigrations() {
  for (const args of migrateSteps()) {
    const { code } = compose(args);
    if (code !== 0) {
      console.error(`\n${MIGRATE_FAILED_HINT}`);
      return code;
    }
  }
  return 0;
}
