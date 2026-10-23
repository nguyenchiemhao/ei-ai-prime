// `npm run seed` also creates the vector partition of each demo Organization (EA-35 R18), so the
// demo can index documents right after seeding. The seed runs in `api`; the partition needs the
// migrator role, which only the `migrate` service has.
import fs from "node:fs";
import path from "node:path";
import { compose } from "./docker.mjs";

/** Sorted `organization_id`s of the demo manifests (`*.json`) in `manifestDir`. */
export function demoOrganizationIds(manifestDir) {
  return fs
    .readdirSync(manifestDir)
    .filter((file) => file.endsWith(".json"))
    .map(
      (file) => JSON.parse(fs.readFileSync(path.join(manifestDir, file), "utf8")).organization_id,
    )
    .sort();
}

/** Compose arguments of the partition steps, one per Organization id. Pure, so a test can pin them. */
export function partitionSteps(ids) {
  return ids.map((id) => [
    "--profile",
    "core",
    "--profile",
    "tools",
    "run",
    "--rm",
    "-T",
    "migrate",
    "ei-ai",
    "db",
    "vector-partition",
    "--org",
    id,
  ]);
}

/** Runs the steps; returns 0 or the exit code of the first failing step. */
export function runPartitionSteps(manifestDir) {
  for (const args of partitionSteps(demoOrganizationIds(manifestDir))) {
    const { code } = compose(args);
    if (code !== 0) return code;
  }
  return 0;
}
