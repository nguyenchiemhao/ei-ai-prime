// Runs one named task of scripts/lib/tasks.mjs: node scripts/task.mjs <task> [--native]
// This is what the CI workflow calls, so CI and `npm run check` execute the same commands.
import { runTask } from "./lib/run-task.mjs";

const args = process.argv.slice(2);
const [name] = args.filter((arg) => arg !== "--native");
if (!name) {
  console.error("usage: node scripts/task.mjs <task> [--native]");
  process.exit(2);
}
process.exit(runTask(name, { native: args.includes("--native") }));
