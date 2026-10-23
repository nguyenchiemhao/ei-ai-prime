import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { demoOrganizationIds, partitionSteps } from "./seed-partitions.mjs";

const MEKONG = "0192a000-0000-7000-8000-00000000ea21";
const SONG_HAN = "0192a000-0000-7000-8000-00000000ea94";
const MANIFESTS = path.join("backend", "src", "ei_ai", "seed", "data");

test("reads_the_sorted_organization_ids_of_the_manifests", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-seed-partitions-"));
  fs.writeFileSync(path.join(dir, "b.json"), JSON.stringify({ organization_id: SONG_HAN }));
  fs.writeFileSync(path.join(dir, "a.json"), JSON.stringify({ organization_id: MEKONG }));
  fs.writeFileSync(path.join(dir, "notes.txt"), "not a manifest");

  assert.deepEqual(demoOrganizationIds(dir), [MEKONG, SONG_HAN]);
});

test("finds_both_demo_organizations_in_the_repo_manifests", () => {
  assert.deepEqual(demoOrganizationIds(MANIFESTS), [MEKONG, SONG_HAN]);
});

test("builds_one_migrate_step_per_organization", () => {
  const base = ["--profile", "core", "--profile", "tools", "run", "--rm", "-T", "migrate"];
  const tail = ["ei-ai", "db", "vector-partition", "--org"];

  assert.deepEqual(partitionSteps([MEKONG, SONG_HAN]), [
    [...base, ...tail, MEKONG],
    [...base, ...tail, SONG_HAN],
  ]);
});
