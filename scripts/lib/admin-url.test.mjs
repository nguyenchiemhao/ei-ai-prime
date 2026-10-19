import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { adminUrl } from "./admin-url.mjs";

function root(dotEnv) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ei-ai-admin-url-"));
  if (dotEnv !== undefined) fs.writeFileSync(path.join(dir, ".env"), dotEnv);
  return dir;
}

test("defaults_to_port_3000", () => {
  assert.equal(adminUrl(root(), {}), "http://localhost:3000");
  assert.equal(adminUrl(root("ADMIN_PORT=\n"), {}), "http://localhost:3000");
});

test("follows_admin_port_from_dot_env_like_compose", () => {
  assert.equal(adminUrl(root("ADMIN_PORT=3100\n"), {}), "http://localhost:3100");
});

test("a_shell_admin_port_wins_over_dot_env_like_compose", () => {
  assert.equal(
    adminUrl(root("ADMIN_PORT=3100\n"), { ADMIN_PORT: "3200" }),
    "http://localhost:3200",
  );
});

test("admin_url_is_the_explicit_override", () => {
  const env = { ADMIN_URL: "http://127.0.0.1:9999", ADMIN_PORT: "3200" };
  assert.equal(adminUrl(root("ADMIN_PORT=3100\n"), env), "http://127.0.0.1:9999");
});

test("an_empty_shell_admin_port_means_the_default_like_compose", () => {
  assert.equal(adminUrl(root("ADMIN_PORT=3100\n"), { ADMIN_PORT: "" }), "http://localhost:3000");
});

test("a_quoted_or_commented_dot_env_port_is_read_like_compose", () => {
  assert.equal(adminUrl(root('ADMIN_PORT="3100"\n'), {}), "http://localhost:3100");
  assert.equal(adminUrl(root("ADMIN_PORT=3100 # moved\n"), {}), "http://localhost:3100");
});
