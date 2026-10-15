// EA-13 (SET-03) AC2, AC6: the root README covers setup, tests, folder structure and AC verification, and
// what it documents (commands, URLs, ports, memory limits, versions) matches the repository.
// Run:  node --test scripts/checks/readme.test.mjs
// Override the README under test (mutation checks): README_FILE=<path>
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";
import { MIN_COMPOSE_VERSION } from "../lib/compose-version.mjs";
import { tasks } from "../lib/tasks.mjs";

const readme = fs.readFileSync(path.resolve(ROOT, process.env.README_FILE || "README.md"), "utf8");
const compose = fs.readFileSync(path.join(ROOT, "compose.yaml"), "utf8");
const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

const REQUIRED_SECTIONS = [
  "What this is",
  "Prerequisites",
  "Quick start",
  "Seed data",
  "Running tests and checks",
  "Folder structure",
  "Verify acceptance criteria locally",
  "Writing isolation tests",
  "CI",
  "Memory budget",
  "Troubleshooting",
  "Conventions",
];

/** Text of the `## <title>` section (up to the next `## `). */
function section(title) {
  const match = readme.match(new RegExp(`^## ${title}\\n([\\s\\S]*?)(?=^## |(?![\\s\\S]))`, "m"));
  assert.ok(match, `README has no "## ${title}" section`);
  return match[1];
}

/** Published host ports by service from the raw compose file: { admin: 3000, ... }. */
function composePorts() {
  const ports = {};
  let service = null;
  for (const line of compose.split("\n")) {
    const header = line.match(/^ {2}([a-z][a-z-]*):\s*$/);
    if (header) service = header[1];
    const port = line.match(/^\s+- "127\.0\.0\.1:(\d+):\d+"/);
    if (port && service) ports[service] = Number(port[1]);
  }
  return ports;
}

test("has_required_sections", () => {
  const headings = [...readme.matchAll(/^## (.+)$/gm)].map((m) => m[1]);
  for (const title of REQUIRED_SECTIONS) {
    assert.ok(headings.includes(title), `missing section "${title}"`);
    assert.ok(section(title).trim().length > 80, `section "${title}" is nearly empty`);
  }
});

test("every_npm_run_command_exists", () => {
  const commands = [...readme.matchAll(/npm run ([a-z][a-z0-9:-]*)( -- ([a-z-]+))?/g)];
  assert.ok(commands.length >= 10, "expected the README to document the npm run commands");
  for (const [, name, , task] of commands) {
    assert.ok(
      packageJson.scripts[name],
      `README documents "npm run ${name}", which is not a root script`,
    );
    if (name === "backend" && task)
      assert.ok(
        tasks[`backend:${task}`],
        `README documents "npm run backend -- ${task}", which is not a backend task`,
      );
  }
  assert.ok(
    /`npm test`/.test(readme) && packageJson.scripts.test,
    "npm test is documented and exists",
  );
});

test("every_root_script_is_documented", () => {
  for (const name of Object.keys(packageJson.scripts).filter(
    (n) => !["prebuild", "test"].includes(n),
  )) {
    assert.ok(
      readme.includes(`npm run ${name}`),
      `root script "${name}" is not documented in the README`,
    );
  }
});

test("folder_table_lists_every_top_level_directory", () => {
  const files = spawnSync("git", ["ls-files", "-co", "--exclude-standard"], {
    cwd: ROOT,
    encoding: "utf8",
  }).stdout.split("\n");
  const directories = [
    ...new Set(files.filter((file) => file.includes("/")).map((file) => file.split("/")[0])),
  ];
  assert.ok(directories.length >= 8);
  const table = section("Folder structure");
  for (const directory of directories) {
    assert.ok(
      table.includes(`\`${directory}/\``),
      `top-level directory "${directory}/" is not in the folder table`,
    );
  }
});

test("documented_urls_match_compose_ports", () => {
  const ports = Object.values(composePorts());
  assert.deepEqual([...ports].sort(), [3000, 3001, 8000]);
  const vitePorts = ["admin", "widget"].map((app) =>
    Number(
      fs
        .readFileSync(path.join(ROOT, `apps/${app}/vite.config.ts`), "utf8")
        .match(/port: (\d+)/)?.[1] ?? 5173,
    ),
  );
  const documented = [...readme.matchAll(/localhost:(\d+)/g)].map((m) => Number(m[1]));
  assert.ok(documented.length >= 3);
  for (const port of documented)
    assert.ok(
      [...ports, ...vitePorts].includes(port),
      `README documents localhost:${port}, which no service publishes`,
    );
});

test("admin_url_in_readme_matches_compose_port", () => {
  const { admin, widget, api } = composePorts();
  const quickStart = section("Quick start");
  assert.ok(
    quickStart.includes(`http://localhost:${admin}`),
    `Quick start must name http://localhost:${admin} (admin)`,
  );
  assert.ok(
    quickStart.includes(`http://localhost:${widget}`),
    `Quick start must name http://localhost:${widget} (widget)`,
  );
  assert.ok(
    quickStart.includes(`http://localhost:${api}/healthz`),
    `Quick start must name http://localhost:${api}/healthz`,
  );
});

test("prerequisites_name_docker_node_and_wslconfig", () => {
  const text = section("Prerequisites");
  assert.match(text, /Docker/);
  assert.ok(
    text.includes(`Docker Compose **${MIN_COMPOSE_VERSION} or newer**`),
    `Prerequisites must say "Docker Compose **${MIN_COMPOSE_VERSION} or newer**"`,
  );
  assert.ok(
    text.includes(packageJson.engines.node.replace(">=", "")),
    "Prerequisites must name the minimum Node version",
  );
  assert.match(text, /\.wslconfig/);
  assert.match(text, /memory=10GB/);
  assert.match(text, /wsl --shutdown/);
});

test("memory_table_matches_compose_limits", () => {
  const table = section("Memory budget");
  const services = [
    ...compose.matchAll(/^ {2}([a-z][a-z-]*):\n(?:(?! {2}[a-z]).*\n)*? {4}mem_limit: (\S+)/gm),
  ];
  assert.ok(services.length >= 6, "expected a mem_limit for each running service");
  for (const [, service, limit] of services) {
    assert.match(
      table,
      new RegExp(`\\| \`${service}\` \\| ${limit.replace(/(\d+)([gm])/, "$1 ?$2")}`, "i"),
      `Memory budget table: ${service} must show the limit ${limit}`,
    );
  }
});

test("make_up_in_older_tickets_means_npm_run_up", () => {
  assert.match(readme, /`make up`.*`npm run up`/);
  assert.match(readme, /`make seed`.*`npm run seed`/);
});

test("no_secret_values_are_shown", () => {
  assert.doesNotMatch(readme, /(PASSWORD|SECRET|TOKEN)=(?!__GENERATED__)\S{8,}/);
});

test("no_placeholder_is_left", () => {
  assert.doesNotMatch(readme, /@@[A-Z]+@@|\bTBD\b|\bTODO\b/);
});

test("every_compose_version_in_the_readme_is_the_minimum", () => {
  const mentions = readme
    .split("\n")
    .filter((line) => /Compose|exactly/.test(line))
    .flatMap((line) => [...line.matchAll(/\b(\d+\.\d+\.\d+)\b/g)].map((match) => match[1]));
  assert.ok(mentions.length >= 2, "expected the minimum version in Prerequisites and the CI table");
  for (const version of mentions) {
    assert.equal(version, MIN_COMPOSE_VERSION, `stale Compose version ${version}`);
  }
});

test("e2e_setup_is_documented", () => {
  const text = section("Running tests and checks");
  assert.ok(text.includes("`playwright.config.ts`"), "name playwright.config.ts");
  assert.ok(text.includes("npx playwright install chromium"), "document the browser install");
  assert.ok(text.includes("npm run e2e"), "document the E2E command");
  assert.ok(text.includes("ADMIN_URL"), "document the base URL variable");
});

// EA-19 (FND-02) DoD: a developer who adds a route, a table, a job or a cache key learns here what the
// tenant-isolation suite expects.
test("writing_isolation_tests_section_documents_the_suite", () => {
  const text = section("Writing isolation tests");
  for (const required of [
    "npm run backend -- test-isolation",
    "tests/integration/isolation/cases.py",
    "ResourceRoute",
    "OwnTenantRoute",
    "PublicRoute",
    "JobCase",
    "route has no isolation test declared",
    "TenantCache",
    "run_tenant_job",
    "envelope_for",
    "tenant-isolation",
    "ei_ai/jobs/__init__.py",
    "create_valkey_client",
    "CACHE_PUBLIC_API",
    "uuid4",
  ]) {
    assert.ok(text.includes(required), `the section does not mention ${required}`);
  }
});
