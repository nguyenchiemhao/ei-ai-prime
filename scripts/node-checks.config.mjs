// The repository Node checks, run by `node scripts/run-node-checks.mjs` (locally and in CI).
// `pattern` = test files (dir/*.test.mjs or dir/**/*.test.mjs); `command` = a validator that must exit 0.
export default [
  { name: "design (DSN-01)", pattern: "docs/design/checks/*.test.mjs" },
  { name: "architecture (ADR, licence review)", pattern: "docs/architecture/checks/*.test.mjs" },
  { name: "EVL-01 data set", pattern: "eval/datasets/mekong-devworks/checks/*.test.mjs" },
  {
    name: "EVL-01 validate.mjs",
    command: ["node", "eval/datasets/mekong-devworks/tools/validate.mjs"],
  },
  { name: "packages", pattern: "packages/*/test/*.test.mjs" },
  { name: "scripts and repo checks", pattern: "scripts/**/*.test.mjs" },
  { name: "skill scripts", pattern: ".claude/skills/*/scripts/*.test.mjs" },
];
