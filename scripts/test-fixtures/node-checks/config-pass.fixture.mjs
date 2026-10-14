export default [
  { name: "fixture-pass", pattern: "scripts/test-fixtures/node-checks/pass/*.fixture.mjs" },
  { name: "fixture-command", command: ["node", "-e", "process.exit(0)"] },
];
