// Backend tasks: npm run backend -- <lint|format|typecheck|test|openapi|openapi-export|test-integration|test-isolation|prepare> [--native]
// In the backend-tools container by default (no local Python needed); --native runs on the host
// (CI, or a local Python 3.12 with `pip install -e "backend[dev]"`).
import { runTask } from "./lib/run-task.mjs";
import { backendTaskName, tasks } from "./lib/tasks.mjs";

const args = process.argv.slice(2);
const native = args.includes("--native");
const [short] = args.filter((arg) => arg !== "--native");
const name = short ? backendTaskName(short) : "";

if (!tasks[name]) {
  const known = Object.keys(tasks)
    .filter((task) => task.startsWith("backend:"))
    .map((task) => task.slice("backend:".length));
  console.error(`usage: npm run backend -- <${known.join("|")}> [--native]`);
  process.exit(2);
}
process.exit(runTask(name, { native }));
