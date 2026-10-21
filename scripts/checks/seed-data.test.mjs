// EA-94 AC7: docs/dev/seed-data.md lists every Organization, Workspace, account, collection and folder
// exactly as the seed manifests (backend/src/ei_ai/seed/data/*.json) define them, and shows the shared
// test password of .env.example.
// Run:  node --test scripts/checks/seed-data.test.mjs
// Override the document under test (mutation checks): SEED_README_FILE=<path>
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ROOT } from "../lib/docker.mjs";
import { envFileValue } from "../lib/ensure-env.mjs";

const MANIFEST_DIR = path.join(ROOT, "backend", "src", "ei_ai", "seed", "data");
const PASSWORD_VARIABLE = "EI_AI_SEED_PASSWORD";
const PLATFORM_ADMIN_NOTE = "`platform_admin`: planned, not stored";
const NONE = "—";
const LOCAL_ONLY = "Local model only";
const ANY_MODEL = "Any model";

// Reads the document under test
// Input: none
// Output: string
const readSeedReadme = () =>
  fs.readFileSync(
    path.resolve(ROOT, process.env.SEED_README_FILE || "docs/dev/seed-data.md"),
    "utf8",
  );

// Reads every seed manifest
// Input: none
// Output: object[]
const loadManifests = () =>
  fs
    .readdirSync(MANIFEST_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => JSON.parse(fs.readFileSync(path.join(MANIFEST_DIR, file), "utf8")));

// Splits the document into the `## <Organization>` sections (the ones with a "### Workspaces" table)
// Input: text (string)
// Output: { title: string, body: string }[]
const organizationSections = (text) =>
  text
    .split(/^## /m)
    .slice(1)
    .map((chunk) => ({ title: chunk.split("\n")[0].trim(), body: chunk }))
    .filter((section) => /^### Workspaces$/m.test(section.body));

// Reads the rows of the `### <title>` table of a section: header first, cells trimmed, backticks removed
// Input: body (string), title (string)
// Output: string[][] (empty when the table is missing)
const tableCells = (body, title) => {
  const block = body.match(new RegExp(`^### ${title}\\n([\\s\\S]*?)(?=^### |(?![\\s\\S]))`, "m"));
  if (!block) return [];
  const lines = block[1].split("\n").filter((line) => line.startsWith("|"));
  return lines
    .filter((_, index) => index !== 1)
    .map((line) =>
      line
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((cell) => cell.trim().replace(/`/g, "")),
    );
};

// Lists every folder of a collection as a path joined by " / " (intermediate folders included)
// Input: folders (object[] | undefined), parents (string[])
// Output: string[]
const folderPaths = (folders = [], parents = []) =>
  folders.flatMap((folder) => {
    const here = [...parents, folder.name];
    return [here.join(" / "), ...folderPaths(folder.folders, here)];
  });

// Builds the rows the README must show for one manifest
// Input: manifest (object)
// Output: { workspaces, accounts, collections, folders } (string[][] each, header excluded)
const expectedRows = (manifest) => {
  const names = manifest.workspaces.map((workspace) => workspace.name);
  const collectionRows = manifest.workspaces.flatMap((workspace) =>
    workspace.collections.map((collection) => ({ workspace: workspace.name, collection })),
  );
  return {
    workspaces: manifest.workspaces.map((workspace) => [
      workspace.name,
      String(manifest.members.filter((member) => member.workspaces?.[workspace.name]).length),
      String(workspace.collections.length),
    ]),
    accounts: manifest.members.map((member) => [
      member.name,
      member.email,
      member.org_role ?? NONE,
      ...names.map((name) => member.workspaces?.[name] ?? NONE),
      member.shared_password === false ? "no" : "yes",
    ]),
    collections: collectionRows.map(({ workspace, collection }) => [
      workspace,
      collection.name,
      collection.subtitle ?? NONE,
      collection.access_level,
      collection.groups?.join(", ") ?? NONE,
      collection.local_only ? LOCAL_ONLY : ANY_MODEL,
    ]),
    folders: collectionRows.flatMap(({ workspace, collection }) =>
      folderPaths(collection.folders).map((folder) => [workspace, collection.name, folder]),
    ),
  };
};

// Compares expected and actual rows both ways and names every row that differs
// Input: label (string), expected (string[][]), actual (string[][])
// Output: string[] (empty when equal)
const diffRows = (label, expected, actual) => {
  const expectedKeys = new Set(expected.map((row) => row.join(" | ")));
  const actualKeys = new Set(actual.map((row) => row.join(" | ")));
  return [
    ...[...expectedKeys]
      .filter((key) => !actualKeys.has(key))
      .map((key) => `${label}: README lacks the row "${key}"`),
    ...[...actualKeys]
      .filter((key) => !expectedKeys.has(key))
      .map((key) => `${label}: README has a row the manifests do not seed "${key}"`),
  ];
};

// Header the accounts table must have for one manifest
// Input: manifest (object)
// Output: string[]
const accountsHeader = (manifest) => [
  "Name",
  "Email",
  "Organization role",
  ...manifest.workspaces.map((workspace) => `Role in ${workspace.name}`),
  "Shared password",
  "What it can do",
];

// Compares one table kind of every manifest with the README
// Input: text (string), manifests (object[]), kind ("workspaces" | "accounts" | "collections" | "folders")
// Output: string[] (problems, empty when equal)
const compareTable = (text, manifests, kind) => {
  const sections = organizationSections(text);
  const tableTitle = kind[0].toUpperCase() + kind.slice(1);
  return manifests.flatMap((manifest) => {
    const section = sections.find((candidate) => candidate.title === manifest.organization);
    if (!section) return [];
    const [header = [], ...actual] = tableCells(section.body, tableTitle);
    const problems = diffRows(
      `${manifest.organization} / ${kind}`,
      expectedRows(manifest)[kind],
      actual.map((row) => (kind === "accounts" ? row.slice(0, -1) : row)),
    );
    const expectedHeader = accountsHeader(manifest).join(" | ");
    if (kind === "accounts" && header.join(" | ") !== expectedHeader)
      problems.push(`${manifest.organization} / accounts: header must be "${expectedHeader}"`);
    return problems;
  });
};

// Compares the Organization sections (names and ids) with the manifests
// Input: text (string), manifests (object[])
// Output: string[]
const compareOrganizations = (text, manifests) => {
  const sections = organizationSections(text);
  const problems = diffRows(
    "organizations",
    manifests.map((manifest) => [manifest.organization]),
    sections.map((section) => [section.title]),
  );
  for (const manifest of manifests) {
    const section = sections.find((candidate) => candidate.title === manifest.organization);
    if (section && !section.body.includes(`\`${manifest.organization_id}\``))
      problems.push(
        `${manifest.organization}: README does not show the id ${manifest.organization_id}`,
      );
  }
  return problems;
};

// Reads the shared test password shown under "## Shared test password" (the first backticked word that is not the variable name)
// Input: text (string)
// Output: string | undefined
const documentedPassword = (text) => {
  const body = text.match(/^## Shared test password\n([\s\S]*?)(?=^## |(?![\s\S]))/m)?.[1] ?? "";
  const words = [...body.matchAll(/`([^`\s]+)`/g)].map((match) => match[1]);
  return words.find((word) => word !== PASSWORD_VARIABLE);
};

const manifests = loadManifests();

test("readme_lists_exactly_the_seeded_organizations", () => {
  const problems = compareOrganizations(readSeedReadme(), manifests);
  assert.deepEqual(problems, [], problems.join("\n"));
});

test("readme_lists_exactly_the_seeded_workspaces", () => {
  const problems = compareTable(readSeedReadme(), manifests, "workspaces");
  assert.deepEqual(problems, [], problems.join("\n"));
});

test("readme_lists_exactly_the_seeded_accounts", () => {
  const problems = compareTable(readSeedReadme(), manifests, "accounts");
  assert.deepEqual(problems, [], problems.join("\n"));
});

test("readme_lists_exactly_the_seeded_collections", () => {
  const problems = compareTable(readSeedReadme(), manifests, "collections");
  assert.deepEqual(problems, [], problems.join("\n"));
});

test("readme_lists_exactly_the_seeded_folders", () => {
  const problems = compareTable(readSeedReadme(), manifests, "folders");
  assert.deepEqual(problems, [], problems.join("\n"));
});

test("readme_marks_platform_admin_as_planned_on_the_sysadmin_row", () => {
  const rows = readSeedReadme()
    .split("\n")
    .filter((line) => line.startsWith("|") && line.includes("sysadmin@mekongdevworks.example"));
  assert.ok(rows.length >= 1, "no sysadmin row in the README");
  for (const row of rows)
    assert.ok(row.includes(PLATFORM_ADMIN_NOTE), `row lacks the note: ${row}`);
});

test("readme_has_the_documented_sections", () => {
  const text = readSeedReadme();
  for (const title of [
    "Shared test password",
    "Sign-in and Organizations",
    "Not seeded yet",
    "Extending the seed",
  ])
    assert.match(text, new RegExp(`^## ${title}$`, "m"), `missing section "${title}"`);
  assert.match(text, /ei-ai user link/, "say how to get a set-password link");
});

test("readme_password_matches_env_example", () => {
  const text = readSeedReadme();
  const expected = envFileValue(ROOT, PASSWORD_VARIABLE, ".env.example");
  assert.ok(expected, `.env.example has no ${PASSWORD_VARIABLE}`);
  assert.equal(documentedPassword(text), expected, "the password shown in the README differs");
  assert.ok(text.includes(`\`${PASSWORD_VARIABLE}\``), `name ${PASSWORD_VARIABLE} in the README`);
});

test("root_readme_links_seed_data", () => {
  const readme = fs.readFileSync(path.join(ROOT, "README.md"), "utf8");
  const section = readme.match(/^## Seed data\n([\s\S]*?)(?=^## |(?![\s\S]))/m)?.[1] ?? "";
  assert.ok(
    section.includes("(docs/dev/seed-data.md)"),
    "Seed data must link docs/dev/seed-data.md",
  );
});

test("mutations_fail", () => {
  const text = readSeedReadme();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "seed-data-"));
  // [description, mutation, comparison, text the problem must name]
  const cases = [
    [
      "one account role changed",
      (value) =>
        value.replace(/(\| linh\.tran@\S+ \| `org_admin` \| )`workspace_admin`/, "$1`viewer`"),
      (value) => compareTable(value, manifests, "accounts"),
      "linh.tran@mekongdevworks.example",
    ],
    [
      "one folder removed",
      (value) => value.replace(/^.*Labor contracts.*\n/m, ""),
      (value) => compareTable(value, manifests, "folders"),
      "Templates / Contracts / Labor contracts",
    ],
    [
      "one extra collection",
      (value) =>
        value.replace(
          /^(\| Customer Care \| Store Policies.*)$/m,
          "$1\n| Customer Care | Extra Collection | — | `public` | — | Any model |",
        ),
      (value) => compareTable(value, manifests, "collections"),
      "Extra Collection",
    ],
  ];
  try {
    for (const [description, mutate, compare, named] of cases) {
      const file = path.join(dir, "seed-data.md");
      const mutated = mutate(text);
      assert.notEqual(mutated, text, `${description}: the mutation did not change the README`);
      fs.writeFileSync(file, mutated);
      const problems = compare(fs.readFileSync(file, "utf8"));
      assert.ok(problems.length > 0, `${description}: the check did not fail`);
      assert.ok(
        problems.some((problem) => problem.includes(named)),
        `${description}: no problem names "${named}": ${problems.join("; ")}`,
      );
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
