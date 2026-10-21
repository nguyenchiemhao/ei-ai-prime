// CI gate (owner decision 2026-10-21): CI runs on every branch push; a push to the default branch
// skips the five check jobs only when the pushed commit is a merge whose tree is identical to the
// merged branch head and that head already has a successful CI run (the same tree was checked).
//   node scripts/ci-gate.mjs      writes `run=true|false` to $GITHUB_OUTPUT and prints the reason
// Any doubt (no token, API error, not a merge, trees differ) means run=true.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/**
 * The decision, without I/O.
 * @param {{event: string, ref: string, defaultBranch: string, parents: string[],
 *          tree: string, mergedTree: string | null, mergedHeadGreen: boolean}} facts
 * @returns {{run: boolean, reason: string}}
 */
export function decide({ event, ref, defaultBranch, parents, tree, mergedTree, mergedHeadGreen }) {
  if (event !== "push") return { run: true, reason: `event ${event}` };
  if (ref !== `refs/heads/${defaultBranch}`) return { run: true, reason: `branch push ${ref}` };
  if (parents.length !== 2) return { run: true, reason: "not a merge commit" };
  if (!mergedTree || tree !== mergedTree)
    return { run: true, reason: "merge tree differs from the merged branch head" };
  if (!mergedHeadGreen)
    return { run: true, reason: `no successful CI run for the merged head ${parents[1]}` };
  return { run: false, reason: `same tree as ${parents[1]}, which already passed CI` };
}

const git = (...args) => execFileSync("git", args, { encoding: "utf8" }).trim();

/** True when the CI workflow has a successful run for `sha`; false on any doubt. */
async function hasGreenRun(sha) {
  const { GITHUB_API_URL, GITHUB_REPOSITORY, GITHUB_TOKEN } = process.env;
  if (!GITHUB_API_URL || !GITHUB_REPOSITORY || !GITHUB_TOKEN) return false;
  const url = `${GITHUB_API_URL}/repos/${GITHUB_REPOSITORY}/actions/workflows/ci.yml/runs?head_sha=${sha}&status=success&per_page=1`;
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${GITHUB_TOKEN}`, Accept: "application/vnd.github+json" },
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) return false;
    const body = await response.json();
    return Number(body.total_count) > 0;
  } catch {
    return false;
  }
}

async function main() {
  const parents = git("rev-list", "--parents", "-n", "1", "HEAD").split(" ").slice(1);
  const event = process.env.GITHUB_EVENT_NAME ?? "";
  const ref = process.env.GITHUB_REF ?? "";
  const defaultBranch = process.env.DEFAULT_BRANCH || "main";
  let mergedTree = null;
  let mergedHeadGreen = false;
  if (event === "push" && ref === `refs/heads/${defaultBranch}` && parents.length === 2) {
    try {
      mergedTree = git("rev-parse", `${parents[1]}^{tree}`);
    } catch {
      mergedTree = null;
    }
    mergedHeadGreen = await hasGreenRun(parents[1]);
  }
  const { run, reason } = decide({
    event,
    ref,
    defaultBranch,
    parents,
    tree: git("rev-parse", "HEAD^{tree}"),
    mergedTree,
    mergedHeadGreen,
  });
  console.log(`ci-gate: run=${run} (${reason})`);
  if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `run=${run}\n`);
}

if (path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) await main();
