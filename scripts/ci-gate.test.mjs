// CI gate decision (owner decision 2026-10-21). Run: node --test scripts/ci-gate.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { decide } from "./ci-gate.mjs";

const mergeOnMain = {
  event: "push",
  ref: "refs/heads/main",
  defaultBranch: "main",
  parents: ["aaa", "bbb"],
  tree: "t1",
  mergedTree: "t1",
  mergedHeadGreen: true,
};

test("a_trivial_merge_of_a_green_branch_skips_ci_on_main", () => {
  assert.equal(decide(mergeOnMain).run, false);
});

test("a_branch_push_always_runs", () => {
  assert.equal(decide({ ...mergeOnMain, ref: "refs/heads/feature/EA-1-x" }).run, true);
});

test("a_manual_run_always_runs", () => {
  assert.equal(decide({ ...mergeOnMain, event: "workflow_dispatch" }).run, true);
});

test("a_non_merge_push_to_main_runs", () => {
  assert.equal(decide({ ...mergeOnMain, parents: ["aaa"] }).run, true);
});

test("a_merge_whose_tree_differs_from_the_branch_runs", () => {
  assert.equal(decide({ ...mergeOnMain, mergedTree: "t2" }).run, true);
  assert.equal(decide({ ...mergeOnMain, mergedTree: null }).run, true);
});

test("a_merge_of_a_branch_without_a_green_run_runs", () => {
  assert.equal(decide({ ...mergeOnMain, mergedHeadGreen: false }).run, true);
});

test("the_default_branch_comes_from_the_repository", () => {
  const facts = { ...mergeOnMain, ref: "refs/heads/dev", defaultBranch: "dev" };
  assert.equal(decide(facts).run, false);
  assert.equal(decide({ ...facts, ref: "refs/heads/main" }).run, true);
});
