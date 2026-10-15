// npm run check: everything CI runs, in one command (jobs frontend, backend, checks, tenant-isolation, stack).
//   npm run check                 all five jobs; the stack job starts the stack without the model and stops it
//   npm run check -- --skip-stack fast loop without Docker services (skips tenant-isolation and stack)
//   npm run check -- --native     run the backend tools on the host instead of the backend-tools container
// Prints PASS/FAIL and the duration of every step and job; exit code 1 when anything failed.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { STEP_MAX_BUFFER, buildPlan } from "./lib/check-plan.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const plan = buildPlan({
  skipStack: args.includes("--skip-stack"),
  native: args.includes("--native"),
});

const seconds = (since) => ((Date.now() - since) / 1000).toFixed(1);
const summary = [];
let failed = false;

for (const { job, steps } of plan) {
  console.log(`\n== job: ${job}`);
  const jobStarted = Date.now();
  let jobOk = true;
  for (const [label, argv] of steps) {
    const started = Date.now();
    const result = spawnSync(process.execPath, argv, {
      cwd: ROOT,
      encoding: "utf8",
      maxBuffer: STEP_MAX_BUFFER,
    });
    const ok = result.status === 0;
    console.log(`${ok ? "PASS" : "FAIL"} ${label} (${seconds(started)}s)`);
    if (!ok) {
      console.log(`${result.stdout}${result.stderr}`.trimEnd().split("\n").slice(-60).join("\n"));
      jobOk = false;
      failed = true; // keep going: the stack job must still run its final `down`
    }
  }
  summary.push(`${jobOk ? "PASS" : "FAIL"} job ${job}: ${seconds(jobStarted)}s`);
}

console.log(
  `\n== summary (jobs run in parallel in CI; the slowest job is the wall-clock time)\n${summary.join("\n")}`,
);
process.exit(failed ? 1 : 0);
